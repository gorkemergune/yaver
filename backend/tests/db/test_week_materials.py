"""What a course week holds (app.materials.weekly) and Scholar's answers built on it:
"bu hafta CSE 221'de ne var?" -> get_syllabus(relative=this_week) with sections, pages, the
shared notes' tab and the lab sheet; "sınav için ne çalışmalıyım?" -> get_exam_scope with the
user's topics matched to the syllabus weeks; the Sunday plan lists each course's week."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Course,
    CourseMaterial,
    CourseSource,
    Event,
    MaterialSection,
    SourceItem,
    SyllabusWeek,
    Term,
)
from app.db.models.enums import EventKind
from app.jobs.weekly_plan import draft_week
from app.materials.weekly import WeekRef, match_topics, week_material_ids
from tests.agent_fakes import NOW, ScriptedLLM, call
from tests.db.test_agent_tools import IST, context, tool

# NOW is Monday 23 November 2026: week 9 of a term that starts on 28 September


async def cse221(session: AsyncSession) -> Course:
    session.add(
        Term(name="2026-27 Güz", start_date=dt.date(2026, 9, 28), end_date=dt.date(2027, 1, 22))
    )
    course = Course(code="CSE 221", name="Logic Design", aliases=["Lojik"])
    session.add(course)
    await session.flush()
    plan = {
        3: ("Boolean Functions, Canonical Forms", "2.5-2.6", None),
        4: ("Karnaugh Maps, Don't Cares", "3.1-3.4", None),
        8: ("Review and Midterm Exam", None, None),
        9: ("Decoders, MUX/DEMUX", "4.9-4.11", "Lab 3: decoder"),
    }
    for week, (topics, readings, lab) in plan.items():
        session.add(
            SyllabusWeek(
                course_id=course.id, week_no=week, topics=topics, readings=readings, lab=lab
            )
        )
    book = CourseMaterial(course_id=course.id, kind="book", title="Digital Design.pdf", pages=500)
    sheet = CourseMaterial(course_id=course.id, kind="lab", title="Lab3 decoder.pdf", pages=3)
    tab = CourseMaterial(course_id=course.id, kind="notes", title="CSE 221 notları: Map", pages=4)
    session.add_all([book, sheet, tab])
    await session.flush()
    session.add_all(
        [
            MaterialSection(
                material_id=book.id,
                course_id=course.id,
                number="4.9",
                title="Decoders",
                page_start=180,
                page_end=186,
                week_nos=[9],
            ),
            MaterialSection(
                material_id=book.id,
                course_id=course.id,
                number="3.2",
                title="Four-Variable Map",
                page_start=92,
                page_end=97,
                week_nos=[4],
            ),
            MaterialSection(
                material_id=sheet.id,
                course_id=course.id,
                number=None,
                title="Lab3 decoder",
                page_start=1,
                page_end=3,
                week_nos=[9],
            ),
        ]
    )
    source = CourseSource(
        course_id=course.id, url="https://docs.google.com/spreadsheets/d/x", title="CSE 221 notları"
    )
    session.add(source)
    await session.flush()
    session.add(
        SourceItem(
            source_id=source.id,
            key="Map",
            topic="Karnaugh haritası",
            week_nos=[4],
            digest="d",
            material_id=tab.id,
        )
    )
    await session.commit()
    return course


async def test_this_weeks_topics_with_sections_pages_notes_and_sheets(
    session: AsyncSession,
) -> None:
    await cse221(session)
    result = await tool(context(session), "get_syllabus", course="Lojik", relative="this_week")
    assert result["current_term_week"] == 9
    assert result["weeks"] == [
        {
            "week": 9,
            "topics": "Decoders, MUX/DEMUX",
            "readings": "4.9-4.11",
            "lab": "Lab 3: decoder",
            "sections": ["Digital Design.pdf: 4.9 Decoders (s. 180-186)"],
            "sheets": ["Lab3 decoder.pdf"],
        }
    ]
    previous = await tool(context(session), "get_syllabus", course="CSE 221", week=4)
    assert previous["weeks"][0]["notes"] == ["CSE 221 notları: Map (Karnaugh haritası)"]
    every = await tool(context(session), "get_syllabus", course="CSE 221")
    assert len(every["weeks"]) == 4
    assert "sections" not in every["weeks"][1]  # all weeks: compact


async def test_exam_scope_matches_the_users_topics_to_the_syllabus(session: AsyncSession) -> None:
    course = await cse221(session)
    nothing = await tool(context(session), "get_exam_scope", course="CSE 221")
    assert nothing["exam"] is None
    session.add(
        Event(
            kind=EventKind.EXAM,
            title="CSE 221 Ara Sınav",
            course_id=course.id,
            start_at=NOW + dt.timedelta(days=3),
            notes="Konular: Karnaugh, kanonik formlar",
        )
    )
    await session.commit()
    scope = await tool(context(session), "get_exam_scope", course="CSE 221")
    assert scope["exam"]["days_left"] == 3
    assert scope["basis"] == "your topics matched to the syllabus"
    assert [w["week"] for w in scope["weeks"]] == [3, 4]
    assert scope["weeks"][1]["sections"] == ["Digital Design.pdf: 3.2 Four-Variable Map (s. 92-97)"]


def test_topic_words_match_loosely() -> None:
    weeks = [
        WeekRef("X", 1, "Number Systems"),
        WeekRef("X", 2, "Karnaugh Maps"),
        WeekRef("X", 3, "Canonical Forms", readings="2.5"),
    ]
    found = match_topics(["karnaugh haritası", "kanonik formlar"], weeks)
    assert (found.weeks, found.missing, found.complete) == ([2, 3], [], True)
    assert match_topics(["sayı sistemleri"], weeks).weeks == [1]
    partly = match_topics(["Karnaugh", "Quine-McCluskey"], weeks)
    assert (partly.weeks, partly.missing, partly.complete) == ([2], ["Quine-McCluskey"], False)
    assert match_topics(["giriş"], weeks).weeks == []


async def test_the_sunday_plan_lists_each_courses_week(session: AsyncSession) -> None:
    await cse221(session)
    llm = ScriptedLLM(
        {
            "weekly_planner": [
                call(
                    "week_draft",
                    summary="Sakin bir hafta.",
                    tasks=[{"title": "CSE 221: 4.9 oku", "date": "2026-11-24", "why": "9. hafta"}],
                )
            ]
        }
    )
    drafted = await draft_week(session, llm, dt.date(2026, 11, 22), IST)
    assert drafted is not None
    message, _ = drafted
    assert (
        "📚 Derslerde bu hafta:\n- CSE 221 (9. hafta): Decoders, MUX/DEMUX · okuma: 4.9-4.11 · "
        "bölümler: Digital Design.pdf: 4.9 Decoders (s. 180-186) · lab: Lab 3: decoder · "
        "föy: Lab3 decoder.pdf"
    ) in message
    facts = llm.requests[0][1].messages[0].content
    assert "Course week: CSE 221 (9. hafta): Decoders, MUX/DEMUX" in facts


async def test_a_weeks_materials_include_tabs_of_several_weeks(session: AsyncSession) -> None:
    course = await cse221(session)
    titles = {
        m.title
        for m in (
            await session.scalars(
                select(CourseMaterial).where(
                    CourseMaterial.id.in_(await week_material_ids(session, course.id, 4))
                )
            )
        ).all()
    }
    assert titles == {"Digital Design.pdf", "CSE 221 notları: Map"}
