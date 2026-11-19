"""Tasks, follow-ups and long-lived memories."""

import datetime as dt

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.enums import (
    FollowupCheckRule,
    FollowupStatus,
    TaskScope,
    TaskSource,
    TaskStatus,
)
from app.db.types import str_enum


class Task(TimestampMixin, Base):
    """A to-do for a specific day (`date`) or a week (`week_start`, always a Monday)."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'day' AND date IS NOT NULL AND week_start IS NULL)"
            " OR (scope = 'week' AND week_start IS NOT NULL AND date IS NULL)",
            name="scope_fields",
        ),
        CheckConstraint(
            "week_start IS NULL OR EXTRACT(ISODOW FROM week_start) = 1", name="week_start_monday"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    scope: Mapped[TaskScope] = mapped_column(str_enum(TaskScope, "task_scope"))
    date: Mapped[dt.date | None] = mapped_column(index=True)
    week_start: Mapped[dt.date | None] = mapped_column(index=True)
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus, "task_status"),
        default=TaskStatus.TODO,
        server_default=TaskStatus.TODO.value,
    )
    source: Mapped[TaskSource] = mapped_column(
        str_enum(TaskSource, "task_source"),
        default=TaskSource.USER,
        server_default=TaskSource.USER.value,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[dt.datetime | None]


class Followup(TimestampMixin, Base):
    """Something to keep asking about until it resolves ("hackathon kabulü geldi mi?")."""

    __tablename__ = "followups"
    __table_args__ = (
        CheckConstraint(
            "check_rule <> 'every_n_days' OR every_n_days IS NOT NULL", name="every_n_days_set"
        ),
        CheckConstraint("every_n_days IS NULL OR every_n_days > 0", name="every_n_days_positive"),
        CheckConstraint("check_rule <> 'on_date' OR check_on IS NOT NULL", name="check_on_set"),
        Index("ix_followups_status_next_check_at", "status", "next_check_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[FollowupStatus] = mapped_column(
        str_enum(FollowupStatus, "followup_status"),
        default=FollowupStatus.WAITING,
        server_default=FollowupStatus.WAITING.value,
    )
    check_rule: Mapped[FollowupCheckRule] = mapped_column(
        str_enum(FollowupCheckRule, "followup_check_rule")
    )
    every_n_days: Mapped[int | None]
    check_on: Mapped[dt.date | None]
    next_check_at: Mapped[dt.datetime | None]
    last_checked_at: Mapped[dt.datetime | None]
    related_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)


class Memory(TimestampMixin, Base):
    """Long-lived fact the agents should know ("Cuma günleri Medipol'deyim")."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), index=True)
