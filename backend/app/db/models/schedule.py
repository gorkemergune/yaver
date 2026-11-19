"""Schedule: weekly recurring blocks, per-date overrides, one-off events, attendance.

Time model:
- Instants (event start/end, a moved block's new start/end) are UTC `timestamptz`.
- Weekly recurrence is wall-clock: `weekday` + `start_time`/`end_time` in APP_TIMEZONE,
  so "Monday 09:00" stays 09:00 local even across DST changes. Dates are local dates.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.enums import (
    ACADEMIC_BLOCK_KINDS,
    AttendanceStatus,
    BlockKind,
    EventKind,
    OverrideAction,
)
from app.db.types import str_enum


class RecurringBlock(TimestampMixin, Base):
    """Weekly repeating block. `end_time <= start_time` means it ends the next day."""

    __tablename__ = "recurring_blocks"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
        CheckConstraint("start_time <> end_time", name="non_empty"),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from",
            name="valid_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[BlockKind] = mapped_column(str_enum(BlockKind, "block_kind"))
    title: Mapped[str] = mapped_column(String(200))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday ... 6 = Sunday
    start_time: Mapped[time]
    end_time: Mapped[time]
    location: Mapped[str | None] = mapped_column(String(200))
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), index=True
    )
    valid_from: Mapped[date | None]
    valid_to: Mapped[date | None]
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def is_academic(self) -> bool:
        return self.kind in ACADEMIC_BLOCK_KINDS


class BlockOverride(TimestampMixin, Base):
    """Change to a single occurrence of a recurring block.

    `date` is the local date of the original occurrence. A move may land on another day.
    """

    __tablename__ = "block_overrides"
    __table_args__ = (
        UniqueConstraint("block_id", "date", name="uq_block_overrides_block_date"),
        CheckConstraint(
            "(action = 'cancel' AND new_start_at IS NULL AND new_end_at IS NULL)"
            " OR (action = 'move' AND new_start_at IS NOT NULL AND new_end_at IS NOT NULL"
            " AND new_end_at > new_start_at)",
            name="action_fields",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_blocks.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date]
    action: Mapped[OverrideAction] = mapped_column(str_enum(OverrideAction, "override_action"))
    new_start_at: Mapped[datetime | None] = mapped_column(index=True)
    new_end_at: Mapped[datetime | None]
    reason: Mapped[str | None] = mapped_column(Text)


class Event(TimestampMixin, Base):
    """One-off event. `end_at` NULL = point in time (e.g. a deadline).

    All-day events span local midnights: start_at = first day 00:00, end_at = day after
    the last day 00:00 (both in APP_TIMEZONE, stored as UTC).
    """

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("end_at IS NULL OR end_at >= start_at", name="time_range"),
        CheckConstraint("NOT all_day OR end_at IS NOT NULL", name="all_day_has_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[EventKind] = mapped_column(str_enum(EventKind, "event_kind"))
    title: Mapped[str] = mapped_column(String(200))
    start_at: Mapped[datetime] = mapped_column(index=True)
    end_at: Mapped[datetime | None] = mapped_column(index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    location: Mapped[str | None] = mapped_column(String(200))
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)


class Attendance(TimestampMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("course_id", "date", name="uq_attendance_course_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    date: Mapped[date]
    status: Mapped[AttendanceStatus] = mapped_column(
        str_enum(AttendanceStatus, "attendance_status")
    )
    note: Mapped[str | None] = mapped_column(Text)
