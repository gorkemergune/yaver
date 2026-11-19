"""Proposals waiting for the user's confirmation: a pasted or photographed weekly schedule,
or events read from an image (exam notice, event poster). Shown as a table, written only
after "evet"."""

import datetime as dt
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.enums import ProposalKind, ProposalStatus
from app.db.types import str_enum


class Proposal(TimestampMixin, Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[ProposalKind] = mapped_column(
        str_enum(ProposalKind, "proposal_kind"),
        default=ProposalKind.SCHEDULE,
        server_default=ProposalKind.SCHEDULE.value,
    )
    status: Mapped[ProposalStatus] = mapped_column(
        str_enum(ProposalStatus, "proposal_status"),
        default=ProposalStatus.PENDING,
        server_default=ProposalStatus.PENDING.value,
    )
    source_text: Mapped[str] = mapped_column(Text)  # the pasted text, or "[görsel #id]"
    # schedule: [{kind, title, course, weekdays, start_time, end_time, location}]
    # events:   [{kind, title, course, date, start_time, end_time, location}]
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB(none_as_null=True))
    unclear: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    parsed_by: Mapped[str] = mapped_column(String(100))  # provider/model
    applied_at: Mapped[dt.datetime | None]
