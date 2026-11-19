"""load_plan_sources() + compute_day_plan() against real PostgreSQL rows."""

import datetime as dt
from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from app.services.schedule import get_day_plan
from tests.factories import IST, local

MON = dt.date(2026, 11, 16)
FRI = dt.date(2026, 11, 20)
SAT = dt.date(2026, 11, 21)


async def _seed_week(session: AsyncSession) -> dict[str, int]:
    fall = Term(name="2026-2027 Güz", start_date=dt.date(2026, 9, 28), end_date=dt.date(2027, 1, 8))
    session.add(fall)
    await session.flush()
    linear_course = Course(code="MATH221", name="Linear Algebra", term_id=fall.id)
    session.add(linear_course)
    await session.flush()

    linear = RecurringBlock(
        kind=BlockKind.CLASS,
        title="Linear Algebra",
        weekday=0,
        start_time=dt.time(9),
        end_time=dt.time(11),
        course_id=linear_course.id,
    )
    friday_class = RecurringBlock(
        kind=BlockKind.CLASS, title="EE211", weekday=4, start_time=dt.time(13), end_time=dt.time(15)
    )
    shift = RecurringBlock(
        kind=BlockKind.WORK,
        title="Gece vardiyası",
        weekday=4,
        start_time=dt.time(22),
        end_time=dt.time(2),
    )
    session.add_all([linear, friday_class, shift])
    await session.flush()

    session.add_all(
        [
            BlockOverride(
                block_id=linear.id,
                date=MON,
                action=OverrideAction.MOVE,
                new_start_at=local(SAT, "10:00"),
                new_end_at=local(SAT, "12:00"),
                reason="Telafi",
            ),
            BlockOverride(
                block_id=friday_class.id, date=FRI, action=OverrideAction.CANCEL, reason="İptal"
            ),
            Holiday(
                name="Bayram", start_date=dt.date(2026, 11, 23), end_date=dt.date(2026, 11, 23)
            ),
            Event(
                kind=EventKind.MEETING,
                title="Iceberg toplantısı",
                start_at=local(FRI, "23:00"),
                end_at=local(SAT, "01:00"),
            ),
            Event(
                kind=EventKind.QUIZ,
                title="Online quiz",
                start_at=dt.datetime(2026, 11, 20, 22, 30, tzinfo=dt.UTC),  # 21 Nov 01:30 local
                end_at=dt.datetime(2026, 11, 20, 23, 30, tzinfo=dt.UTC),
            ),
            Event(kind=EventKind.DEADLINE, title="Ödev", start_at=local(SAT, "23:59")),
            Task(title="Haftalık okuma", scope=TaskScope.WEEK, week_start=MON),
            Task(title="Market", scope=TaskScope.DAY, date=SAT),
        ]
    )
    await session.commit()
    return {"linear": linear.id, "friday_class": friday_class.id}


async def test_day_plan_from_database(session: AsyncSession) -> None:
    ids = await _seed_week(session)

    monday = await get_day_plan(session, MON, IST)
    friday = await get_day_plan(session, FRI, IST)
    saturday = await get_day_plan(session, SAT, IST)
    holiday_monday = await get_day_plan(session, dt.date(2026, 11, 23), IST)

    assert monday.items == []  # linear moved to Saturday
    assert monday.terms == ["2026-2027 Güz"]

    assert [item.title for item in friday.items] == ["Gece vardiyası", "Iceberg toplantısı"]
    assert [c.block_id for c in friday.cancelled] == [ids["friday_class"]]
    assert len(friday.conflicts) == 1

    assert [item.title for item in saturday.items] == [
        "Gece vardiyası",
        "Iceberg toplantısı",
        "Online quiz",
        "Linear Algebra",
        "Ödev",
    ]
    moved = saturday.items[3]
    assert moved.moved_from == local(MON, "09:00")
    assert moved.start == local(SAT, "10:00")
    assert moved.start.tzinfo == IST
    assert [t.title for t in saturday.tasks] == ["Market"]
    assert [t.title for t in saturday.week_tasks] == ["Haftalık okuma"]

    assert holiday_monday.items == []
    assert holiday_monday.holidays == ["Bayram"]


async def test_instants_are_stored_and_returned_in_utc(session: AsyncSession) -> None:
    session.add(Event(kind=EventKind.EXAM, title="Vize", start_at=local(MON, "10:00")))
    await session.commit()

    # Read the raw column, bypassing UTCDateTime, to see what PostgreSQL actually holds.
    stored = await session.scalar(text("SELECT start_at AT TIME ZONE 'UTC' FROM events"))

    # 10:00 Istanbul == 07:00 UTC
    assert stored.replace(tzinfo=dt.UTC) == dt.datetime(2026, 11, 16, 7, 0, tzinfo=dt.UTC)


async def test_naive_datetime_is_rejected(session: AsyncSession) -> None:
    session.add(
        Event(kind=EventKind.EXAM, title="Vize", start_at=dt.datetime(2026, 11, 16, 10))  # noqa: DTZ001
    )

    with pytest.raises(StatementError, match="Naive datetime"):
        await session.flush()


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(
            lambda block_id: BlockOverride(block_id=block_id, date=MON, action=OverrideAction.MOVE),
            id="move-without-new-times",
        ),
        pytest.param(
            lambda block_id: BlockOverride(
                block_id=block_id,
                date=MON,
                action=OverrideAction.CANCEL,
                new_start_at=local(MON, "10:00"),
                new_end_at=local(MON, "11:00"),
            ),
            id="cancel-with-new-times",
        ),
        pytest.param(
            lambda _: Task(title="x", scope=TaskScope.WEEK, week_start=dt.date(2026, 11, 18)),
            id="week-task-not-starting-monday",
        ),
        pytest.param(
            lambda _: Task(title="x", scope=TaskScope.DAY),
            id="day-task-without-date",
        ),
        pytest.param(
            lambda _: RecurringBlock(
                kind=BlockKind.CLASS,
                title="x",
                weekday=7,
                start_time=dt.time(9),
                end_time=dt.time(10),
            ),
            id="weekday-out-of-range",
        ),
    ],
)
async def test_check_constraints_reject_inconsistent_rows(
    session: AsyncSession, row: Callable[[int], object]
) -> None:
    block = RecurringBlock(
        kind=BlockKind.CLASS, title="Linear", weekday=0, start_time=dt.time(9), end_time=dt.time(11)
    )
    session.add(block)
    await session.flush()

    session.add(row(block.id))

    with pytest.raises(IntegrityError):
        await session.flush()
