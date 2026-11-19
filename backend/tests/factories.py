"""Builders for transient ORM objects (no database) used by service tests."""

import datetime as dt
from itertools import count
from zoneinfo import ZoneInfo

from app.db.models import (
    BlockOverride,
    Course,
    Event,
    Holiday,
    RecurringBlock,
    Task,
    Term,
)
from app.db.models.enums import (
    BlockKind,
    EventKind,
    OverrideAction,
    TaskScope,
    TaskSource,
    TaskStatus,
)

IST = ZoneInfo("Europe/Istanbul")
UTC = dt.UTC

_ids = count(1)


def local(day: dt.date, hhmm: str, tz: ZoneInfo = IST) -> dt.datetime:
    """Aware local datetime, e.g. local(MON, "09:30")."""
    return dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=tz)


def utc(value: dt.datetime) -> dt.datetime:
    """What the database hands back: the same instant in UTC."""
    return value.astimezone(UTC)


def term(start: dt.date, end: dt.date, name: str = "2026-2027 Güz") -> Term:
    return Term(id=next(_ids), name=name, start_date=start, end_date=end)


def holiday(
    start: dt.date, end: dt.date | None = None, *, name: str = "Tatil", term_id: int | None = None
) -> Holiday:
    return Holiday(
        id=next(_ids), name=name, start_date=start, end_date=end or start, term_id=term_id
    )


def course(code: str = "MATH221", *, term_id: int | None = None) -> Course:
    return Course(id=next(_ids), code=code, name=code, term_id=term_id)


def block(
    weekday: int,
    start: str,
    end: str,
    *,
    title: str = "Linear Algebra",
    kind: BlockKind = BlockKind.CLASS,
    course_id: int | None = None,
    valid_from: dt.date | None = None,
    valid_to: dt.date | None = None,
    location: str | None = None,
) -> RecurringBlock:
    return RecurringBlock(
        id=next(_ids),
        kind=kind,
        title=title,
        weekday=weekday,
        start_time=dt.time.fromisoformat(start),
        end_time=dt.time.fromisoformat(end),
        course_id=course_id,
        valid_from=valid_from,
        valid_to=valid_to,
        location=location,
    )


def cancel(target: RecurringBlock, on: dt.date, reason: str | None = None) -> BlockOverride:
    return BlockOverride(
        id=next(_ids), block_id=target.id, date=on, action=OverrideAction.CANCEL, reason=reason
    )


def move(
    target: RecurringBlock,
    on: dt.date,
    new_start: dt.datetime,
    new_end: dt.datetime,
    reason: str | None = None,
) -> BlockOverride:
    return BlockOverride(
        id=next(_ids),
        block_id=target.id,
        date=on,
        action=OverrideAction.MOVE,
        new_start_at=utc(new_start),
        new_end_at=utc(new_end),
        reason=reason,
    )


def event(
    start: dt.datetime,
    end: dt.datetime | None = None,
    *,
    title: str = "Toplantı",
    kind: EventKind = EventKind.MEETING,
    all_day: bool = False,
) -> Event:
    return Event(
        id=next(_ids),
        kind=kind,
        title=title,
        start_at=utc(start),
        end_at=utc(end) if end is not None else None,
        all_day=all_day,
    )


def all_day_event(
    first_day: dt.date,
    last_day: dt.date,
    *,
    title: str = "Hackathon",
    kind: EventKind = EventKind.HACKATHON,
    tz: ZoneInfo = IST,
) -> Event:
    return event(
        local(first_day, "00:00", tz),
        local(last_day + dt.timedelta(days=1), "00:00", tz),
        title=title,
        kind=kind,
        all_day=True,
    )


def task(
    title: str,
    *,
    on: dt.date | None = None,
    week_of: dt.date | None = None,
    status: TaskStatus = TaskStatus.TODO,
) -> Task:
    return Task(
        id=next(_ids),
        title=title,
        scope=TaskScope.DAY if on is not None else TaskScope.WEEK,
        date=on,
        week_start=week_of,
        status=status,
        source=TaskSource.USER,
    )
