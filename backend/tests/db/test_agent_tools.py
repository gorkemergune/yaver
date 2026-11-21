"""Agent tools against PostgreSQL: behaviour, change log and undo."""

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import ToolContext
from app.agent.tools import run_tool
from app.core.change_log import ChangeRecorder, latest_change_set, undo_change_set
from app.db.models import (
    BlockOverride,
    ChangeLog,
    Course,
    Event,
    Followup,
    RecurringBlock,
    Term,
)
from app.db.models.enums import ChangeOp, OverrideAction

IST = ZoneInfo("Europe/Istanbul")
NOW = dt.datetime(2026, 11, 23, 7, 0, tzinfo=dt.UTC)  # Monday 10:00 Istanbul


def context(session: AsyncSession, agent_id: str = "academic") -> ToolContext:
    change_set = uuid.uuid4()
    ctx = ToolContext(
        session=session,
        now=NOW,
        tz=IST,
        change_set_id=change_set,
        recorder=ChangeRecorder(session, change_set),
        agent_id=agent_id,
    )
    ctx.recorder.agent_id = agent_id
    return ctx


async def tool(ctx: ToolContext, name: str, **arguments: Any) -> dict[str, Any]:
    return await run_tool(name, arguments, ctx)


async def add_linear(session: AsyncSession) -> ToolContext:
    ctx = context(session)
    result = await tool(
        ctx,
        "add_recurring_block",
        kind="class",
        title="Linear Algebra",
        weekdays=["monday"],
        start_time="09:00",
        end_time="11:00",
        course="Linear Algebra",
    )
    assert "created" in result, result
    await session.commit()
    return ctx


async def test_add_block_creates_course_once_and_skips_duplicates(session: AsyncSession) -> None:
    await add_linear(session)
    ctx = context(session)

    again = await tool(
        ctx,
        "add_recurring_block",
        kind="lab",
        title="Linear Lab",
        weekdays=["monday", "friday"],
        start_time="13:00",
        end_time="15:00",
        course="linear",
    )
    duplicate = await tool(
        ctx,
        "add_recurring_block",
        kind="class",
        title="Linear Algebra",
        weekdays=["monday"],
        start_time="09:00",
        end_time="11:00",
    )

    assert len(again["created"]) == 2
    assert "course_created" not in again  # matched the existing "Linear Algebra"
    assert duplicate["created"] == []
    assert len(duplicate["already_existed"]) == 1
    assert len((await session.scalars(select(Course))).all()) == 1


async def test_course_gets_the_current_term(session: AsyncSession) -> None:
    session.add(Term(name="Güz", start_date=dt.date(2026, 9, 28), end_date=dt.date(2027, 1, 8)))
    await session.flush()

    await add_linear(session)

    course = await session.scalar(select(Course))
    assert course is not None
    assert course.term_id is not None


async def test_cancel_errors_list_what_is_there(session: AsyncSession) -> None:
    await add_linear(session)
    ctx = context(session)

    wrong_day = await tool(ctx, "cancel_block_on", date="2026-11-24", block="linear")
    unknown = await tool(ctx, "cancel_block_on", date="2026-11-23", block="kimya")

    assert "no 'linear' block on 2026-11-24" in wrong_day["error"]
    assert unknown["blocks_that_day"] == ["Linear Algebra"]


async def test_ambiguous_block_returns_candidates(session: AsyncSession) -> None:
    await add_linear(session)
    ctx = context(session)
    await tool(
        ctx,
        "add_recurring_block",
        kind="lab",
        title="Linear Lab",
        weekdays=["monday"],
        start_time="13:00",
        end_time="14:00",
        course="Linear Algebra",
    )

    result = await tool(ctx, "cancel_block_on", date="2026-11-23", block="linear")

    assert "several blocks" in result["error"]
    assert {c["title"] for c in result["candidates"]} == {"Linear Algebra", "Linear Lab"}


async def test_cancel_then_move_updates_the_same_override(session: AsyncSession) -> None:
    await add_linear(session)
    ctx = context(session)

    await tool(ctx, "cancel_block_on", date="2026-11-23", block="linear", reason="hasta")
    again = await tool(ctx, "cancel_block_on", date="2026-11-23", block="linear")
    moved = await tool(
        ctx,
        "move_block_on",
        date="2026-11-23",
        block="linear",
        new_date="2026-11-28",
        new_start_time="10:00",
        new_end_time="12:00",
    )

    assert "already_cancelled" in again
    assert moved["to"] == "2026-11-28 10:00-12:00"  # "not cancelled after all: moved"
    overrides = (await session.scalars(select(BlockOverride))).all()
    assert [o.action for o in overrides] == [OverrideAction.MOVE]
    cancelled_again = await tool(ctx, "cancel_block_on", date="2026-11-23", block="linear")
    assert "cancelled" in cancelled_again  # the moved occurrence can still be cancelled
    assert [o.action for o in (await session.scalars(select(BlockOverride))).all()] == [
        OverrideAction.CANCEL
    ]


async def test_move_to_another_day(session: AsyncSession) -> None:
    await add_linear(session)
    ctx = context(session)

    result = await tool(
        ctx,
        "move_block_on",
        date="2026-11-23",
        block="linear",
        new_date="2026-11-28",
        new_start_time="10:00",
        new_end_time="12:00",
        reason="telafi",
    )

    assert result["to"] == "2026-11-28 10:00-12:00"
    override = await session.scalar(select(BlockOverride))
    assert override is not None
    assert override.new_start_at == dt.datetime(2026, 11, 28, 7, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("arguments", "start_utc", "end_utc", "all_day"),
    [
        (
            {"date": "2026-11-24", "start_time": "14:00", "end_time": "15:30"},
            dt.datetime(2026, 11, 24, 11, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 11, 24, 12, 30, tzinfo=dt.UTC),
            False,
        ),
        (
            {"date": "2026-11-27", "start_time": "23:00", "end_time": "02:00"},  # overnight
            dt.datetime(2026, 11, 27, 20, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 11, 27, 23, 0, tzinfo=dt.UTC),
            False,
        ),
        (
            {"date": "2026-11-28", "end_date": "2026-11-29"},  # all-day, two days
            dt.datetime(2026, 11, 27, 21, 0, tzinfo=dt.UTC),
            dt.datetime(2026, 11, 29, 21, 0, tzinfo=dt.UTC),
            True,
        ),
        (
            {"date": "2026-11-30", "start_time": "23:59"},  # deadline: a point in time
            dt.datetime(2026, 11, 30, 20, 59, tzinfo=dt.UTC),
            None,
            False,
        ),
    ],
)
async def test_event_times_are_stored_in_utc(
    session: AsyncSession,
    arguments: dict[str, str],
    start_utc: dt.datetime,
    end_utc: dt.datetime | None,
    all_day: bool,
) -> None:
    result = await tool(context(session), "add_event", kind="other", title="X", **arguments)

    assert "created" in result, result
    event = await session.scalar(select(Event))
    assert event is not None
    assert event.start_at == start_utc
    assert event.end_at == end_utc
    assert event.all_day is all_day


async def test_attendance_with_limit(session: AsyncSession) -> None:
    await add_linear(session)  # Mondays 09:00-11:00
    ctx = context(session)

    first = await tool(ctx, "log_attendance", course="linear", dates=["2026-11-16"])
    limit = await tool(ctx, "set_absence_limit", course="Linear Algebra", hours=8)
    second = await tool(ctx, "log_attendance", course="linear", dates=["2026-11-23"])
    unknown = await tool(ctx, "log_attendance", course="kimya", dates=["2026-11-23"])

    assert first["summary"]["limit_hours"] is None  # agent should ask for it
    assert first["hours_logged"] == 2
    assert limit["summary"]["remaining_hours"] == 8 - 2
    assert second["summary"] == {
        "course": "Linear Algebra",
        "name": "Linear Algebra",
        "absent_hours": 4,
        "recorded_hours": 4,
        "limit_hours": 8,
        "remaining_hours": 4,
    }
    assert unknown["known_courses"] == ["Linear Algebra"]


async def test_resolve_date_tool_uses_term_and_weekday(session: AsyncSession) -> None:
    session.add(Term(name="Güz", start_date=dt.date(2026, 9, 28), end_date=dt.date(2027, 1, 8)))
    await session.flush()
    ctx = context(session)

    term_end = await tool(ctx, "resolve_date", expression="dönem sonu", direction="future")
    past = await tool(ctx, "resolve_date", expression="geçen salı", direction="past")
    meeting = await tool(ctx, "resolve_date", expression="yarın 3'te", direction="future")

    assert (term_end["start"], term_end["weekday"]) == ("2027-01-08", "Cuma")
    assert past["start"] == "2026-11-17"
    assert (meeting["start"], meeting["time"]) == ("2026-11-24", "15:00")


async def test_undo_reverts_create_update_and_delete(session: AsyncSession) -> None:
    # Setup in one change set
    await add_linear(session)
    setup = context(session)
    created = await tool(
        setup, "add_event", kind="exam", title="Vize", date="2026-11-25", start_time="10:00"
    )
    await session.commit()
    event_id = created["created"]["event_id"]

    # One message: update the block, delete the event, cancel an occurrence
    ctx = context(session)
    await tool(ctx, "update_recurring_block", block="linear", start_time="10:00", end_time="12:00")
    await tool(ctx, "delete_event", event_id=event_id)
    await tool(ctx, "cancel_block_on", date="2026-11-23", block="linear")
    await session.commit()
    ops = (
        await session.scalars(
            select(ChangeLog.op).where(ChangeLog.change_set_id == ctx.change_set_id)
        )
    ).all()
    assert list(ops) == [ChangeOp.UPDATE, ChangeOp.DELETE, ChangeOp.CREATE]
    assert await latest_change_set(session) == ctx.change_set_id

    await undo_change_set(session, ctx.change_set_id, NOW)
    await session.commit()

    block = await session.scalar(select(RecurringBlock))
    assert block is not None
    assert block.start_time == dt.time(9, 0)  # update reverted
    restored = await session.get(Event, event_id)
    assert restored is not None  # delete reverted, same id
    assert restored.title == "Vize"
    assert restored.start_at == dt.datetime(2026, 11, 25, 7, 0, tzinfo=dt.UTC)
    assert (await session.scalars(select(BlockOverride))).all() == []  # create reverted
    assert await latest_change_set(session) == setup.change_set_id


async def test_undo_tool_skips_its_own_change_set_and_reports_nothing_left(
    session: AsyncSession,
) -> None:
    ctx = context(session)

    nothing = await tool(ctx, "undo")
    bad_id = await tool(ctx, "undo", change_set_id="not-a-uuid")

    assert nothing["error"] == "there is nothing to undo"
    assert "not a valid id" in bad_id["error"]


async def test_tasks_followups_and_memories(session: AsyncSession) -> None:
    ctx = context(session, "agenda")

    task = await tool(ctx, "add_task", title="CV güncelle", week_of="2026-11-25")
    done = await tool(ctx, "complete_task", title="cv")
    followup = await tool(ctx, "add_followup", title="Hackathon kabulü", check_rule="daily")
    news = await tool(ctx, "update_followup", title="hackathon", status="positive")
    memory = await tool(ctx, "remember", content="Cuma günleri Medipol'deyim", category="work")
    forgotten = await tool(ctx, "forget", about="medipol")
    both_scopes = await tool(ctx, "add_task", title="x", date="2026-11-24", week_of="2026-11-24")

    assert task["created"]["week_start"] == "2026-11-23"
    assert done["completed"]["status"] == "done"
    assert followup["created"]["check_rule"] == "daily"
    assert news["updated"]["status"] == "positive"
    assert memory["remembered"]["content"] == "Cuma günleri Medipol'deyim"
    assert forgotten["forgotten"]["memory_id"] == memory["remembered"]["memory_id"]
    assert "exactly one of date / week_of" in both_scopes["error"]
    assert {a["agent_id"] for a in ctx.actions} == {"agenda"}


async def test_a_followup_belongs_to_the_employee_that_added_it(session: AsyncSession) -> None:
    mentor = context(session, "career")
    chrono = context(session, "agenda")

    staj = await tool(mentor, "add_followup", title="Iceberg staj dönüşü", check_rule="daily")
    hackathon = await tool(chrono, "add_followup", title="Hackathon kabulü", check_rule="daily")

    rows = {f.title: f.owner_id for f in (await session.scalars(select(Followup))).all()}
    assert "error" not in staj
    assert "error" not in hackathon
    assert rows == {"Iceberg staj dönüşü": "career", "Hackathon kabulü": "agenda"}
