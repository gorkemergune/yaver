"""Chat history."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin
from app.db.models.enums import ConversationMode, MessageRole
from app.db.types import str_enum


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200))
    # "onboarding": messages go to the setup assistant until it calls finish_onboarding.
    mode: Mapped[ConversationMode] = mapped_column(
        str_enum(ConversationMode, "conversation_mode"),
        default=ConversationMode.CHAT,
        server_default=ConversationMode.CHAT.value,
    )


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
    # What the code read from the message's images ("[Görsel 1: ders programı -> öneri #7]
    # + table"): replayed to the model with the history, not shown in the chat.
    context: Mapped[str | None] = mapped_column(Text)


class Attachment(CreatedAtMixin, Base):
    """An uploaded image. Stored re-encoded (no EXIF / location, long edge <= the limit)
    under UPLOAD_DIR; linked to the user message once it is sent."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(300))  # relative to UPLOAD_DIR
    mime: Mapped[str] = mapped_column(String(50))
    width: Mapped[int]
    height: Mapped[int]
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
