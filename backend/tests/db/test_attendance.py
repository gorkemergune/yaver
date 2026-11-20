"""Attendance in class hours, per block (the schedule is a subset of a real student week)."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import ToolContext
from app.agent.tools import run_tool
from app.db.models import Attendance
from tests.db.test_agent_tools import context

# context(): now = Monday 23 Nov 2026 10:00 Istanbul
WEEK = [
    # (kind, title, course, weekday, start, end)
    ("class", "CSE 211", "CSE 211", "monday", "11:00", "13:00"),
    ("class", "CSE 221", "CSE 221", "monday", "13:00", "14:00"),
    ("lab", "CSE 211 Lab", "CSE 211", "monday", "16:00", "18:00"),
    ("class", "MATH 221", "MATH 221", "tuesday", "11:00", "13:00"),
    ("class", "EE 211 (Ders + Quiz)", "EE 211", "tuesday", "14:00", "16:00"),
    ("lab", "EE 211 Lab", "EE 211", "wednesday", "11:00", "13:00"),
    ("lab", "CSE 221 Lab", "CSE 221", "wednesday", "14:00", "16:00"),
    ("class", "TKL 201", "TKL 201", "wednesday", "16:00", "18:00"),
    ("class", "MATH 221", "MATH 221", "thursday", "09:00", "11:00"),
    ("class", "EE 211", "EE 211", "thursday", "13:00", "14:00"),
    ("class", "CSE 221", "CSE 221", "thursday", "16:00", "18:00"),
]


@pytest.fixture
async def ctx(session: AsyncSession) -> ToolContext:
    ctx = context(session, "academic")
    for kind, title, course, weekday, start, end in WEEK:
        result = await run_tool(
            "add_recurring_block",
            {
                "kind": kind,
                "title": title,
                "course": course,
                "weekdays": [weekday],
                "start_time": start,
                "end_time": end,
            },
            ctx,
        )
        assert "created" in result, result
    return ctx


def nov(*days: int) -> list[str]:
    return [f"2026-11-{day:02d}" for day in days]


async def absent(ctx: ToolContext, course: str, days: list[str], **extra: Any) -> dict[str, Any]:
    return await run_tool("log_attendance", {"course": course, "dates": days, **extra}, ctx)


async def test_the_reported_conversation_counts_class_hours(ctx: ToolContext) -> None:
    tkl = await absent(ctx, "tkl", nov(18))
    math = await absent(ctx, "math221", nov(5, 12, 17, 19))
    cse = await absent(ctx, "cse221", nov(2, 9, 12, 16, 19))
    ee = await absent(ctx, "ee211", nov(12, 19))

    assert tkl["summary"]["absent_hours"] == 2
    assert math["summary"]["absent_hours"] == 8
    assert cse["summary"]["absent_hours"] == 7  # Mondays 1 h, Thursdays 2 h
    assert ee["summary"]["absent_hours"] == 2  # Thursdays 13-14 only, not the Wednesday lab
    assert [(e["date"], e["time"], e["hours"]) for e in math["logged"]] == [
        ("2026-11-05 Perşembe", "09:00-11:00", 2),
        ("2026-11-12 Perşembe", "09:00-11:00", 2),
        ("2026-11-17 Salı", "11:00-13:00", 2),
        ("2026-11-19 Perşembe", "09:00-11:00", 2),
    ]


async def test_sending_it_again_changes_nothing(ctx: ToolContext) -> None:
    await absent(ctx, "math221", nov(5, 12, 17, 19))

    again = await absent(ctx, "MATH 221", nov(5, 12, 17, 19))

    assert again["hours_logged"] == 0
    assert len(again["already_recorded"]) == 4
    assert again["summary"]["absent_hours"] == 8
    count = await ctx.session.scalar(select(func.count()).select_from(Attendance))
    assert count == 4


async def test_every_class_of_the_day_unless_one_is_named(ctx: ToolContext) -> None:
    lab_only = await absent(ctx, "cse211", nov(9), time="16:00")
    whole_day = await absent(ctx, "cse211", nov(16))

    assert [(e["time"], e["hours"]) for e in lab_only["logged"]] == [("16:00-18:00", 2)]
    assert [(e["time"], e["hours"]) for e in whole_day["logged"]] == [
        ("11:00-13:00", 2),
        ("16:00-18:00", 2),
    ]
    assert whole_day["summary"]["absent_hours"] == 6


async def test_days_without_class_or_in_the_future_suggest_the_nearest_past_class(
    ctx: ToolContext,
) -> None:
    sunday = await absent(ctx, "math221", nov(22))
    future = await absent(ctx, "math221", nov(24))
    mixed = await absent(ctx, "math221", nov(19, 22))

    assert sunday["logged"] == []
    assert sunday["not_logged"] == [
        {
            "date": "2026-11-22 Pazar",
            "problem": "no MATH 221 class that day",
            "suggest": ["2026-11-19 Perşembe"],
        }
    ]
    assert future["not_logged"][0]["problem"] == "in the future"
    assert future["not_logged"][0]["suggest"] == ["2026-11-19 Perşembe"]
    assert mixed["hours_logged"] == 2  # the valid day is recorded, the other one asked
    assert [p["date"] for p in mixed["not_logged"]] == ["2026-11-22 Pazar"]


async def test_cancelled_class_is_not_an_absence(ctx: ToolContext) -> None:
    cancel = await run_tool("cancel_block_on", {"date": "2026-11-19", "block": "MATH 221"}, ctx)
    assert "cancelled" in cancel, cancel

    result = await absent(ctx, "math221", nov(19))

    assert result["logged"] == []
    assert result["not_logged"][0]["suggest"] == ["2026-11-17 Salı"]


async def test_baseline_limit_list_and_delete(ctx: ToolContext) -> None:
    await absent(ctx, "math221", nov(5, 12))
    baseline = await run_tool(
        "set_attendance_baseline", {"course": "math221", "hours": 3, "note": "Ekim"}, ctx
    )
    limit = await run_tool("set_absence_limit", {"course": "math221", "hours": 10}, ctx)
    listed = await run_tool("list_attendance", {"course": "math221"}, ctx)
    deleted = await run_tool(
        "delete_attendance", {"attendance_id": listed["records"][0]["id"]}, ctx
    )

    assert baseline["summary"]["baseline"] == {"hours": 3, "note": "Ekim"}
    assert baseline["summary"]["absent_hours"] == 4 + 3
    assert limit["summary"]["remaining_hours"] == 10 - 7
    assert [(r["date"], r["time"], r["hours"]) for r in listed["records"]] == [
        ("2026-11-05 Perşembe", "09:00-11:00", 2),
        ("2026-11-12 Perşembe", "09:00-11:00", 2),
    ]
    assert listed["totals"][0]["recorded_hours"] == 4
    assert deleted["summary"]["absent_hours"] == 2 + 3


@pytest.mark.parametrize(
    ("expression", "direction", "expected"),
    [
        ("5 12 17 19 kasımda", "past", {"dates": nov(5, 12, 17, 19)}),
        ("2, 9, 12, 16 ve 19 kasım", "past", {"dates": nov(2, 9, 12, 16, 19)}),
        ("12 19 kasımda", "past", {"dates": nov(12, 19)}),  # two days, not 12-19
        ("28-29 kasım", "future", {"start": "2026-11-28", "end": "2026-11-29"}),  # a range
    ],
)
async def test_resolve_date_takes_a_list_of_days(
    ctx: ToolContext, expression: str, direction: str, expected: dict[str, Any]
) -> None:
    result = await run_tool("resolve_date", {"expression": expression, "direction": direction}, ctx)

    assert result["status"] == "resolved", result
    assert {k: result[k] for k in expected} == expected
