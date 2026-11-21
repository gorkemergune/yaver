"""Effective plan for one day: recurring blocks + overrides + events + tasks.

Rules (all calendar math happens in APP_TIMEZONE; the DB only holds UTC instants):

- Day window = [D 00:00, D+1 00:00) local. Anything overlapping the window belongs to D,
  so an event 23:00-02:00 shows on both days, flagged as continuing.
- Recurring blocks are weekday + wall-clock times. `end_time <= start_time` means the block
  ends the next day, so occurrences from the previous day are considered as well.
- An occurrence exists on local date d when d is inside valid_from/valid_to and, for academic
  kinds (class/lab):
    * d is inside the course's term (if the course has one), otherwise inside any term.
      If no terms are defined at all, the academic calendar is not enforced yet.
    * d is not a holiday that applies (holiday.term_id NULL, or one of the block's terms).
  Non-academic blocks (sport/work/other) ignore terms and holidays.
- Overrides: `cancel` removes the occurrence (listed in `cancelled`), `move` replaces it with
  the new interval, which may land on another day. A move is an explicit user decision
  (e.g. a make-up class), so it is honoured even if the original date was a holiday.
- Events overlap the window; point events (no end) count when they start inside it.
- Conflicts: pairs of timed (non all-day) items whose intervals overlap. Touching
  intervals (09-11 and 11-12) do not conflict.
- Tasks: the day's tasks and the tasks of the day's week (weeks start on Monday);
  cancelled tasks are left out.
"""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    BlockOverride,
    Course,
    Event,
    Holiday,
    RecurringBlock,
    Task,
    Term,
)
from app.db.models.enums import OverrideAction, TaskScope, TaskStatus

ONE_DAY = dt.timedelta(days=1)


# --------------------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanItem:
    source: Literal["block", "event"]
    source_id: int
    kind: str
    title: str
    start: dt.datetime  # aware, in the plan's timezone
    end: dt.datetime | None  # None = point in time (e.g. a deadline)
    all_day: bool = False
    location: str | None = None
    course_id: int | None = None
    course_code: str | None = None
    moved_from: dt.datetime | None = None  # original start of a moved block occurrence
    note: str | None = None  # override reason
    continues_from_previous_day: bool = False
    continues_to_next_day: bool = False

    @property
    def is_timed(self) -> bool:
        return not self.all_day and self.end is not None and self.end > self.start


@dataclass(frozen=True, slots=True)
class CancelledOccurrence:
    block_id: int
    kind: str
    title: str
    start: dt.datetime
    end: dt.datetime
    reason: str | None


@dataclass(frozen=True, slots=True)
class MovedAway:
    """An occurrence of this day that was moved elsewhere (shown as "eski -> yeni")."""

    block_id: int
    kind: str
    title: str
    start: dt.datetime  # where it would have been
    new_start: dt.datetime
    new_end: dt.datetime
    reason: str | None


@dataclass(frozen=True, slots=True)
class Conflict:
    first: PlanItem
    second: PlanItem


@dataclass(frozen=True, slots=True)
class PlanTask:
    id: int
    title: str
    scope: TaskScope
    status: TaskStatus


@dataclass(frozen=True, slots=True)
class DayPlan:
    day: dt.date
    timezone: str
    items: list[PlanItem]
    cancelled: list[CancelledOccurrence]
    conflicts: list[Conflict]
    holidays: list[str]
    terms: list[str]
    tasks: list[PlanTask]
    week_tasks: list[PlanTask]
    moved_away: list[MovedAway] = field(default_factory=list)


@dataclass(slots=True)
class PlanSources:
    """Rows needed to compute a day plan. ORM objects are only read, never lazy-loaded."""

    terms: Sequence[Term] = ()
    holidays: Sequence[Holiday] = ()
    courses: Sequence[Course] = ()
    blocks: Sequence[RecurringBlock] = ()
    overrides: Sequence[BlockOverride] = ()
    events: Sequence[Event] = ()
    tasks: Sequence[Task] = ()


# --------------------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------------------


def day_window(day: dt.date, tz: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
    """[local midnight of `day`, local midnight of the next day)."""
    return (
        dt.datetime.combine(day, dt.time.min, tzinfo=tz),
        dt.datetime.combine(day + ONE_DAY, dt.time.min, tzinfo=tz),
    )


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def occurrence_interval(
    block: RecurringBlock, on: dt.date, tz: ZoneInfo
) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(on, block.start_time, tzinfo=tz)
    end_day = on if block.end_time > block.start_time else on + ONE_DAY
    return start, dt.datetime.combine(end_day, block.end_time, tzinfo=tz)


def _overlaps(
    start: dt.datetime, end: dt.datetime | None, window: tuple[dt.datetime, dt.datetime]
) -> bool:
    window_start, window_end = window
    if end is None or end <= start:  # point in time
        return window_start <= start < window_end
    return start < window_end and end > window_start


# --------------------------------------------------------------------------------------
# Pure computation
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Calendar:
    terms: Sequence[Term]
    holidays: Sequence[Holiday]
    terms_by_id: dict[int, Term] = field(init=False)

    def __post_init__(self) -> None:
        self.terms_by_id = {term.id: term for term in self.terms}

    def block_terms(self, term_id: int | None, on: dt.date) -> set[int] | None:
        """Term ids the occurrence belongs to; None = outside the academic calendar."""
        if not self.terms:
            return set()  # no calendar yet: don't gate
        if term_id is not None:
            term = self.terms_by_id.get(term_id)
            return {term.id} if term is not None and term.contains(on) else None
        containing = {term.id for term in self.terms if term.contains(on)}
        return containing or None

    def holiday_applies(self, on: dt.date, block_term_ids: set[int]) -> bool:
        return any(
            holiday.contains(on)
            and (holiday.term_id is None or not block_term_ids or holiday.term_id in block_term_ids)
            for holiday in self.holidays
        )


def _block_occurs_on(
    block: RecurringBlock, on: dt.date, calendar: _Calendar, course_terms: dict[int, int | None]
) -> bool:
    if block.weekday != on.weekday():
        return False
    if block.valid_from is not None and on < block.valid_from:
        return False
    if block.valid_to is not None and on > block.valid_to:
        return False
    if not block.is_academic:
        return True
    term_id = course_terms.get(block.course_id) if block.course_id is not None else None
    block_term_ids = calendar.block_terms(term_id, on)
    if block_term_ids is None:
        return False
    return not calendar.holiday_applies(on, block_term_ids)


def _block_item(
    block: RecurringBlock,
    start: dt.datetime,
    end: dt.datetime,
    window: tuple[dt.datetime, dt.datetime],
    *,
    moved_from: dt.datetime | None = None,
    note: str | None = None,
) -> PlanItem:
    return PlanItem(
        source="block",
        source_id=block.id,
        kind=block.kind.value,
        title=block.title,
        start=start,
        end=end,
        location=block.location,
        course_id=block.course_id,
        moved_from=moved_from,
        note=note,
        continues_from_previous_day=start < window[0],
        continues_to_next_day=end > window[1],
    )


def _event_item(event: Event, tz: ZoneInfo, window: tuple[dt.datetime, dt.datetime]) -> PlanItem:
    start = event.start_at.astimezone(tz)
    end = event.end_at.astimezone(tz) if event.end_at is not None else None
    return PlanItem(
        source="event",
        source_id=event.id,
        kind=event.kind.value,
        title=event.title,
        start=start,
        end=end,
        all_day=event.all_day,
        location=event.location,
        course_id=event.course_id,
        note=event.notes,
        continues_from_previous_day=start < window[0],
        continues_to_next_day=end is not None and end > window[1],
    )


def _find_conflicts(items: Iterable[PlanItem]) -> list[Conflict]:
    timed = [item for item in items if item.is_timed]
    return [
        Conflict(a, b)
        for a, b in combinations(timed, 2)
        if a.end is not None and b.end is not None and a.start < b.end and b.start < a.end
    ]


def _sort_key(item: PlanItem) -> tuple[bool, dt.datetime, dt.datetime, str]:
    return (not item.all_day, item.start, item.end or item.start, item.title)


def compute_day_plan(day: dt.date, tz: ZoneInfo, sources: PlanSources) -> DayPlan:
    window = day_window(day, tz)
    calendar = _Calendar(sources.terms, sources.holidays)
    course_terms = {course.id: course.term_id for course in sources.courses}
    blocks_by_id = {block.id: block for block in sources.blocks}
    overrides = {(o.block_id, o.date): o for o in sources.overrides}

    items: list[PlanItem] = []
    cancelled: list[CancelledOccurrence] = []
    moved_away: list[MovedAway] = []

    # Regular occurrences: yesterday's (may run past midnight) and today's.
    for on in (day - ONE_DAY, day):
        for block in sources.blocks:
            if not _block_occurs_on(block, on, calendar, course_terms):
                continue
            start, end = occurrence_interval(block, on, tz)
            if not _overlaps(start, end, window):
                continue
            override = overrides.get((block.id, on))
            if override is None:
                items.append(_block_item(block, start, end, window))
            elif override.action is OverrideAction.CANCEL:
                cancelled.append(
                    CancelledOccurrence(
                        block.id, block.kind.value, block.title, start, end, override.reason
                    )
                )
            elif (
                on == day and override.new_start_at is not None and override.new_end_at is not None
            ):
                # shown wherever it landed (below); here only as "moved away"
                moved_away.append(
                    MovedAway(
                        block.id,
                        block.kind.value,
                        block.title,
                        start,
                        override.new_start_at.astimezone(tz),
                        override.new_end_at.astimezone(tz),
                        override.reason,
                    )
                )

    # Moved occurrences landing in this window, from any original date.
    for override in sources.overrides:
        if override.action is not OverrideAction.MOVE:
            continue
        moved_block = blocks_by_id.get(override.block_id)
        if moved_block is None or override.new_start_at is None or override.new_end_at is None:
            continue
        start = override.new_start_at.astimezone(tz)
        end = override.new_end_at.astimezone(tz)
        if _overlaps(start, end, window):
            original_start, _ = occurrence_interval(moved_block, override.date, tz)
            items.append(
                _block_item(
                    moved_block, start, end, window, moved_from=original_start, note=override.reason
                )
            )

    for event in sources.events:
        item = _event_item(event, tz, window)
        if _overlaps(item.start, item.end, window):
            items.append(item)

    codes = {course.id: course.code for course in sources.courses}
    items = [
        replace(item, course_code=codes[item.course_id]) if item.course_id in codes else item
        for item in items
    ]
    items.sort(key=_sort_key)
    cancelled.sort(key=lambda c: c.start)

    monday = week_start(day)
    active_tasks = [task for task in sources.tasks if task.status is not TaskStatus.CANCELLED]

    return DayPlan(
        day=day,
        timezone=tz.key,
        items=items,
        cancelled=cancelled,
        conflicts=_find_conflicts(items),
        holidays=[h.name for h in sources.holidays if h.contains(day)],
        terms=[t.name for t in sources.terms if t.contains(day)],
        tasks=[_plan_task(t) for t in active_tasks if t.scope is TaskScope.DAY and t.date == day],
        week_tasks=[
            _plan_task(t)
            for t in active_tasks
            if t.scope is TaskScope.WEEK and t.week_start == monday
        ],
        moved_away=moved_away,
    )


def _plan_task(task: Task) -> PlanTask:
    return PlanTask(id=task.id, title=task.title, scope=task.scope, status=task.status)


# --------------------------------------------------------------------------------------
# Database access
# --------------------------------------------------------------------------------------


async def load_plan_sources(session: AsyncSession, day: dt.date, tz: ZoneInfo) -> PlanSources:
    window_start, window_end = day_window(day, tz)
    previous_day = day - ONE_DAY

    terms = (await session.scalars(select(Term))).all()
    courses = (await session.scalars(select(Course))).all()
    holidays = (
        await session.scalars(
            select(Holiday).where(Holiday.start_date <= day, Holiday.end_date >= previous_day)
        )
    ).all()
    overrides = (
        await session.scalars(
            select(BlockOverride).where(
                or_(
                    BlockOverride.date.between(previous_day, day),
                    and_(
                        BlockOverride.action == OverrideAction.MOVE,
                        BlockOverride.new_start_at < window_end,
                        BlockOverride.new_end_at > window_start,
                    ),
                )
            )
        )
    ).all()
    moved_block_ids = {o.block_id for o in overrides}
    blocks = (
        await session.scalars(
            select(RecurringBlock).where(
                or_(
                    RecurringBlock.weekday.in_({previous_day.weekday(), day.weekday()}),
                    RecurringBlock.id.in_(moved_block_ids),
                )
            )
        )
    ).all()
    events = (
        await session.scalars(
            select(Event).where(
                Event.start_at < window_end,
                or_(
                    Event.end_at > window_start,
                    and_(Event.end_at.is_(None), Event.start_at >= window_start),
                ),
            )
        )
    ).all()
    tasks = (
        await session.scalars(
            select(Task).where(
                Task.status != TaskStatus.CANCELLED,
                or_(
                    and_(Task.scope == TaskScope.DAY, Task.date == day),
                    and_(Task.scope == TaskScope.WEEK, Task.week_start == week_start(day)),
                ),
            )
        )
    ).all()

    return PlanSources(
        terms=terms,
        holidays=holidays,
        courses=courses,
        blocks=blocks,
        overrides=overrides,
        events=events,
        tasks=tasks,
    )


async def get_day_plan(session: AsyncSession, day: dt.date, tz: ZoneInfo | None = None) -> DayPlan:
    tz = tz or get_settings().tz
    return compute_day_plan(day, tz, await load_plan_sources(session, day, tz))
