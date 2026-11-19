"""Chat history."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin
from app.db.models.enums import MessageRole
from app.db.types import str_enum


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200))


class Message(CreatedAtMixin, Base):
    """One chat message. Messages are append-only (no updated_at)."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole, "message_role"))
    # Which yaver produced this message: an id from config/agents.yaml ("yaver", "academic",
    # ...). Free text on purpose: the team is user-configurable. NULL for user messages.
    agent_id: Mapped[str | None] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Normalized tool calls requested by the assistant (see llm/router), or the tool result.
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    tool_call_id: Mapped[str | None] = mapped_column(String(100))
    # Undo handle: every change made while answering this message shares this id.
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
