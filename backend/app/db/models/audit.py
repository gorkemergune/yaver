"""Undo log and LLM usage accounting."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin
from app.db.models.enums import ChangeOp
from app.db.types import str_enum


class ChangeLog(CreatedAtMixin, Base):
    """Before/after snapshot of every mutation made by an agent tool (undo source)."""

    __tablename__ = "change_log"
    __table_args__ = (
        CheckConstraint(
            "(op = 'create' AND before_json IS NULL AND after_json IS NOT NULL)"
            " OR (op = 'update' AND before_json IS NOT NULL AND after_json IS NOT NULL)"
            " OR (op = 'delete' AND before_json IS NOT NULL AND after_json IS NULL)",
            name="op_snapshots",
        ),
        Index("ix_change_log_entity_entity_id", "entity", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    entity: Mapped[str] = mapped_column(String(50))  # table name, e.g. "recurring_blocks"
    entity_id: Mapped[int]
    op: Mapped[ChangeOp] = mapped_column(str_enum(ChangeOp, "change_op"))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    agent_id: Mapped[str | None] = mapped_column(String(50))
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    undone_at: Mapped[dt.datetime | None]


class LlmUsage(CreatedAtMixin, Base):
    """One LLM API call: tokens and cost, for the monthly budget guard."""

    __tablename__ = "llm_usage"
    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0"
            " AND cached_input_tokens >= 0 AND cache_write_tokens >= 0",
            name="tokens_non_negative",
        ),
        CheckConstraint("cost_usd >= 0", name="cost_non_negative"),
        Index("ix_llm_usage_created_at", "created_at"),
        Index("ix_llm_usage_provider_created_at", "provider", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    tier: Mapped[str] = mapped_column(String(20))  # fast | fallback | smart | local
    purpose: Mapped[str] = mapped_column(String(50))  # chat | briefing | weekly_plan | ...
    agent_id: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal(0), server_default="0"
    )
    latency_ms: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
