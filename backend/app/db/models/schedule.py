"""Schedule: weekly recurring blocks, per-date overrides, one-off events, attendance.

Time model:
- Instants (event start/end, a moved block's new start/end) are UTC `timestamptz`.
- Weekly recurrence is wall-clock: `weekday` + `start_time`/`end_time` in APP_TIMEZONE,
  so "Monday 09:00" stays 09:00 local even across DST changes. Dates are local dates.
"""

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
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
    start_time: Mapped[dt.time]
    end_time: Mapped[dt.time]
    location: Mapped[str | None] = mapped_column(String(200))
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), index=True
    )
    valid_from: Mapped[dt.date | None]
    valid_to: Mapped[dt.date | None]
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
    date: Mapped[dt.date]
    action: Mapped[OverrideAction] = mapped_column(str_enum(OverrideAction, "override_action"))
    new_start_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    new_end_at: Mapped[dt.datetime | None]
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
    start_at: Mapped[dt.datetime] = mapped_column(index=True)
    end_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    location: Mapped[str | None] = mapped_column(String(200))
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    # The employee who prepares for it (a startup meeting -> Venture: an hour before, the
    # week's presentation draft; app.startup.meeting). NULL = nobody.
    owner_id: Mapped[str | None] = mapped_column(String(50))
    # when that preparation message went out (once)
    prep_sent_at: Mapped[dt.datetime | None]


class Attendance(TimestampMixin, Base):
    """One class session (a block on a date) attended or missed. Absences are counted in
    class hours: a 09:00-11:00 block missed is 2 hours. The same session can be recorded
    only once (course, date, block)."""

    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "date", "recurring_block_id", name="uq_attendance_course_date_block"
        ),
        CheckConstraint("hours > 0", name="hours_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    date: Mapped[dt.date]  # local date the session took place (a moved one: its new day)
    # NULL only for records whose block was deleted later (or that had no block to match).
    recurring_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_blocks.id", ondelete="SET NULL"), index=True
    )
    hours: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[AttendanceStatus] = mapped_column(
        str_enum(AttendanceStatus, "attendance_status")
    )
    note: Mapped[str | None] = mapped_column(Text)


class AttendanceBaseline(TimestampMixin, Base):
    """Absence hours from before Yaver kept track (one line per course in summaries)."""

    __tablename__ = "attendance_baselines"
    __table_args__ = (CheckConstraint("hours >= 0", name="hours_not_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), unique=True
    )
    hours: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
