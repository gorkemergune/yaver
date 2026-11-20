"""Week names and labels, the week view of any week (absences, moves) and the term list."""

from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.core.change_log import undo_change_set
from app.services.weeks import WeekFacts, week_facts
from tests.db.test_agent_tools import IST, NOW, context
from tests.db.test_api_web import client, llm  # noqa: F401 - fixtures

# 2026-09-28 is a Monday: week 1. Week 8 = 16 Nov, week 9 = 23 Nov.
SETUP: list[tuple[str, dict[str, Any]]] = [
    ("add_term", {"name": "2026-27 Güz", "start_date": "2026-09-28", "end_date": "2027-01-15"}),
    ("add_term", {"name": "2026-27 Bahar", "start_date": "2027-02-15", "end_date": "2027-06-04"}),
    (
        "add_holiday",
        {"name": "Cumhuriyet Bayramı", "start_date": "2026-10-28", "end_date": "2026-10-30"},
    ),
    ("add_holiday", {"name": "Yılbaşı", "start_date": "2027-01-01"}),
    (
        "add_recurring_block",
        {
            "kind": "class",
            "title": "Linear Algebra",
            "course": "MATH221",
            "weekdays": ["monday", "wednesday"],
            "start_time": "09:00",
            "end_time": "11:00",
        },
    ),
    (
        "add_event",
        {"kind": "exam", "title": "MATH221 Vize", "date": "2026-11-24", "start_time": "10:00"},
    ),
    (
        "add_event",
        {"kind": "exam", "title": "EE211 Vize", "date": "2026-11-26", "start_time": "13:00"},
    ),
    (
        "add_event",
        {"kind": "quiz", "title": "CSE221 Quiz", "date": "2026-12-01", "start_time": "10:00"},
    ),
    (
        "add_event",
        {
            "kind": "deadline",
            "title": "CSE221 proje teslimi",
            "date": "2026-12-11",
            "start_time": "23:59",
        },
    ),
    (
        "add_event",
        {"kind": "exam", "title": "MATH221 Final", "date": "2027-01-05", "start_time": "10:00"},
    ),
    (
        "add_event",
        {"kind": "exam", "title": "EE211 Final", "date": "2027-01-07", "start_time": "10:00"},
    ),
    ("log_attendance", {"course": "MATH221", "dates": ["2026-11-16"]}),
    (
        "move_block_on",
        {
            "date": "2026-11-18",
            "block": "Linear Algebra",
            "new_date": "2026-11-20",
            "new_start_time": "14:00",
            "new_end_time": "16:00",
        },
    ),
]


async def setup(session: AsyncSession) -> None:
    ctx = context(session, "academic")
    for name, args in SETUP:
        result = await run_tool(name, args, ctx)
        assert "error" not in result, (name, result)
    await session.commit()


async def facts(session: AsyncSession, day: str) -> WeekFacts:
    import datetime as dt

    return await week_facts(session, dt.date.fromisoformat(day), IST)


async def test_week_names_and_automatic_labels(session: AsyncSession) -> None:
    await setup(session)
    week8 = await facts(session, "2026-11-18")
    assert week8.title == "2026-27 Güz · 8. Hafta"
    assert week8.label is None
    assert week8.absence_hours == 2
    assert (await facts(session, "2026-09-28")).title == "2026-27 Güz · 1. Hafta"

    holiday = await facts(session, "2026-10-26")
    assert (holiday.week_no, holiday.label) == (5, "Tatil Haftası")
    assert holiday.holidays == ("Cumhuriyet Bayramı",)
    one_day_off = await facts(session, "2026-12-28")  # Yılbaşı alone: a normal week
    assert one_day_off.label is None

    midterms = await facts(session, "2026-11-23")
    assert (midterms.week_no, midterms.exams, midterms.label) == (9, 2, "Vize Haftası")
    quiz = await facts(session, "2026-11-30")
    assert (quiz.quizzes, quiz.label) == (1, None)  # a quiz is not an exam week
    assert (await facts(session, "2026-12-07")).label == "Proje Haftası"
    finals = await facts(session, "2027-01-04")
    assert (finals.week_no, finals.label) == (15, "Final Haftası")

    between = await facts(session, "2027-01-25")
    assert (between.title, between.label) == (None, "Ara tatil")
    assert (await facts(session, "2027-02-15")).title == "2026-27 Bahar · 1. Hafta"
    before_everything = await facts(session, "2026-08-03")
    assert (before_everything.title, before_everything.label) == (None, None)


async def test_user_names_a_week(session: AsyncSession) -> None:
    await setup(session)
    ctx = context(session, "agenda")
    result = await run_tool(
        "set_week_label", {"date": "2026-11-25", "label": "Hackathon Haftası"}, ctx
    )
    assert result["week"] == {
        "week_start": "2026-11-23",
        "title": "2026-27 Güz · 9. Hafta",
        "label": "Hackathon Haftası",
        "automatic": False,
    }
    renamed = await run_tool("set_week_label", {"date": "2026-11-23", "label": "Kod Haftası"}, ctx)
    assert renamed["week"]["label"] == "Kod Haftası"
    cleared = await run_tool("set_week_label", {"date": "2026-11-23", "label": None}, ctx)
    assert cleared["week"] == {
        "week_start": "2026-11-23",
        "title": "2026-27 Güz · 9. Hafta",
        "label": "Vize Haftası",  # back to the automatic one
        "automatic": True,
    }
    await undo_change_set(session, ctx.change_set_id, NOW)  # one message: all three undone
    assert (await facts(session, "2026-11-23")).user_label is None


async def test_any_week_over_http(client: httpx2.AsyncClient, session: AsyncSession) -> None:  # noqa: F811
    await setup(session)
    week = (await client.get("/api/plan/week", params={"date": "2026-11-18"})).json()
    assert week["week_start"] == "2026-11-16"
    assert week["week"]["title"] == "2026-27 Güz · 8. Hafta"
    monday, _, wednesday, _, friday = week["days"][:5]
    assert monday["attendance"] == [
        {"course": "MATH221", "hours": 2, "status": "absent", "block_id": 1}
    ]
    assert wednesday["moved_away"] == [
        {
            "block_id": 2,  # the Wednesday block
            "title": "Linear Algebra",
            "start": "09:00",
            "moved_to": "2026-11-20 14:00",
            "moved_to_end": "16:00",
            "reason": None,
        }
    ]
    assert wednesday["items"] == []
    assert friday["items"][0]["moved_from"] == "2026-11-18 09:00"

    term = (await client.get("/api/terms/weeks")).json()
    assert term["term"]["name"] == "2026-27 Güz"
    assert len(term["weeks"]) == 16
    by_no = {w["week_no"]: w for w in term["weeks"]}
    assert by_no[8]["absence_hours"] == 2
    assert by_no[9]["label"] == "Vize Haftası"
    assert by_no[9]["exams"] == 2
    assert by_no[16]["week_start"] == "2027-01-11"
    other = (await client.get("/api/terms/weeks", params={"term_id": 2})).json()
    assert other["term"]["name"] == "2026-27 Bahar"
