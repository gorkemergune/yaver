"""Bug reports: the user's 👎 "Hatalı" on an answer (web chat, desktop mini chat).

A report keeps what is needed to see what went wrong without the chat open: the user's
message, the answer, who answered, the tools run (with their errors), the routing and the
log lines of those seconds. Not user data the team works with (no change_log / undo).
Exported read-only by scripts/export-bugs.ps1 to docs/bugs/ (gitignored).
"""

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BugReport(TimestampMixin, Base):
    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    # the answer reported; NULL when it failed before it was stored (a stream error)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    agent_id: Mapped[str | None] = mapped_column(String(50))  # who answered
    user_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    reply_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, default="", server_default="")  # the user's words
    # [{agent_id, tool, error}] in order, and the routing: [[intent, owner], ...]
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    intents: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    errors: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    log_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    source: Mapped[str] = mapped_column(String(20), default="web", server_default="web")
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
