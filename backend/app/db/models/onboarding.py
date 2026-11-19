"""Proposals waiting for the user's confirmation (pasted schedule -> table -> "evet")."""

import datetime as dt
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.enums import ProposalStatus
from app.db.types import str_enum


class ScheduleProposal(TimestampMixin, Base):
    __tablename__ = "schedule_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[ProposalStatus] = mapped_column(
        str_enum(ProposalStatus, "proposal_status"),
        default=ProposalStatus.PENDING,
        server_default=ProposalStatus.PENDING.value,
    )
    source_text: Mapped[str] = mapped_column(Text)
    # Parsed weekly entries: [{kind, title, course, weekdays, start_time, end_time, location}]
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB(none_as_null=True))
    unclear: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    parsed_by: Mapped[str] = mapped_column(String(100))  # provider/model
    applied_at: Mapped[dt.datetime | None]
