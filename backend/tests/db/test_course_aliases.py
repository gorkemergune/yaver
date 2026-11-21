"""Course aliases: the user's own words for a course ("DSA" -> CSE 211). Unknown: the tool
says to ask once; the answer is saved as an alias and works from then on (undoable)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.core.change_log import undo_change_set
from app.db.models import Course, Event
from tests.agent_fakes import NOW
from tests.db.test_agent_tools import context

EXAM = {"kind": "exam", "title": "DSA sınavı", "date": "2026-11-30", "course": "DSA"}


async def courses(session: AsyncSession) -> None:
    session.add_all(
        [Course(code="CSE 211", name="CSE 211"), Course(code="CSE 221", name="CSE 221")]
    )
    await session.commit()


async def test_an_unknown_abbreviation_asks_with_the_known_courses(session: AsyncSession) -> None:
    await courses(session)
    ctx = context(session, "academic")

    result = await run_tool("add_event", EXAM, ctx)

    assert result["error"].startswith("no course matches 'DSA': ask the user once")
    assert result["known_courses"] == ["CSE 211", "CSE 221"]
    assert (await session.scalars(select(Event))).all() == []


async def test_the_answer_becomes_an_alias_that_matches_from_then_on(
    session: AsyncSession,
) -> None:
    await courses(session)
    ctx = context(session, "academic")

    saved = await run_tool("add_course_alias", {"course": "cse 211", "alias": "DSA"}, ctx)
    again = await run_tool("add_course_alias", {"course": "CSE 211", "alias": "dsa"}, ctx)
    exam = await run_tool("add_event", EXAM, ctx)
    spaced = await run_tool("get_attendance_summary", {"course": "d s a"}, ctx)

    assert saved == {"course": "CSE 211", "aliases": ["DSA"]}
    assert again["unchanged"] is True
    [event] = (await session.scalars(select(Event))).all()
    assert event.course_id == (
        await session.scalar(select(Course.id).where(Course.code == "CSE 211"))
    )
    assert "created" in exam
    assert "error" not in spaced


async def test_an_alias_of_another_course_is_refused(session: AsyncSession) -> None:
    await courses(session)
    ctx = context(session, "academic")
    await run_tool("add_course_alias", {"course": "CSE 211", "alias": "DSA"}, ctx)

    clash = await run_tool("add_course_alias", {"course": "CSE 221", "alias": "DSA"}, ctx)

    assert clash["error"] == "'DSA' already means CSE 211"


async def test_an_alias_is_undone_with_its_message(session: AsyncSession) -> None:
    await courses(session)
    ctx = context(session, "academic")
    await run_tool("add_course_alias", {"course": "CSE 211", "alias": "Veri Yapıları"}, ctx)
    await session.commit()

    await undo_change_set(session, ctx.change_set_id, NOW)

    course = await session.scalar(select(Course).where(Course.code == "CSE 211"))
    assert course is not None
    assert course.aliases == []
