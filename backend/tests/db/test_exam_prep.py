"""Exam review plan a week before: syllabus weeks since the previous exam, notes of those
weeks, a free slot per day; a proposal (tasks after "evet"), proposed once per exam."""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.config import Settings
from app.db.models import Course, CourseMaterial, Proposal, SyllabusWeek, Task, Term
from app.db.models.enums import ProposalKind
from app.jobs.exam_prep import free_slot
from tests.db.test_agent_tools import IST, context
from tests.db.test_jobs import at, job, settings, week  # noqa: F401 - fixtures

TOPICS = {
    1: "Vektörler",
    2: "Matrisler",
    3: "Determinant",
    4: "Lineer denklem sistemleri",
    5: "Vektör uzayları",
    6: "Taban ve boyut",
    7: "Lineer dönüşümler",
    8: "Ara sınav",
    9: "Özdeğerler",
}


async def with_syllabus(session: AsyncSession) -> None:
    session.add(
        Term(name="2026-27 Güz", start_date=dt.date(2026, 9, 28), end_date=dt.date(2027, 1, 15))
    )
    course = await session.scalar(select(Course).where(Course.code == "MATH221"))
    assert course is not None
    for week_no, topics in TOPICS.items():
        session.add(SyllabusWeek(course_id=course.id, week_no=week_no, topics=topics))
    session.add(
        CourseMaterial(
            course_id=course.id,
            kind="notes",
            title="math221_hafta5.pdf",
            pages=4,
            week_no=5,
            indexed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
        )
    )
    await session.commit()


async def test_free_slot_prefers_the_evening(week: AsyncSession) -> None:  # noqa: F811
    # Monday 23 Nov: Linear 09-11, meeting 14:00, sport 19-20
    slot = await free_slot(week, dt.date(2026, 11, 23), IST)
    assert slot is not None
    assert slot.label() == "17:00-18:30"
    empty = await free_slot(week, dt.date(2026, 11, 22), IST)  # Sunday, nothing planned
    assert empty is not None
    assert empty.label() == "17:00-18:30"


async def test_review_plan_a_week_before_the_exam(
    week: AsyncSession,  # noqa: F811
    settings: Settings,  # noqa: F811
) -> None:
    await with_syllabus(week)
    message = await job(week, settings, "exam_prep", at(20, 18))  # exam: Fri 27 Nov 10:00

    assert message is not None
    assert message.kind == "exam_prep"
    text = message.content
    assert "· Sınav hazırlığı 📚 MATH221 Ara Sınav: 7 gün kaldı (27 Kasım Cuma 10:00)." in text
    # weeks 1-7: the exam is in week 9, "Ara sınav" (week 8) is not a topic
    assert "Konular (syllabus): 1. hafta: Vektörler;" in text
    assert "7. hafta: Lineer dönüşümler" in text
    assert "Ara sınav" not in text.split("Konular (syllabus):")[1].split("\n")[0]
    assert "Notların: math221_hafta5.pdf" in text
    assert (
        "| 23 Kasım Pazartesi | MATH221 tekrar 17:00-18:30: h4 Lineer denklem sistemleri; h5"
        in text
    )
    assert "MATH221 genel tekrar" in text  # the last day before the exam
    assert message.context is not None
    assert "[Sınav hazırlığı taslağı (MATH221 Ara Sınav) -> öneri #1" in message.context

    proposal = await week.get(Proposal, 1)
    assert proposal is not None
    assert proposal.kind is ProposalKind.TASKS
    days = [e["date"] for e in proposal.entries]
    assert days == [
        "2026-11-21",
        "2026-11-22",
        "2026-11-23",
        "2026-11-24",
        "2026-11-25",
        "2026-11-26",
    ]

    # next day: the same exam is not proposed again
    assert await job(week, settings, "exam_prep", at(21, 18)) is None

    # "evet": the classes yaver applies it -> tasks on those days
    before = await week.scalar(select(func.count()).select_from(Task))
    result = await run_tool("apply_proposal", {"proposal_id": 1}, context(week, "academic"))
    assert len(result["tasks_created"]) == 6
    assert await week.scalar(select(func.count()).select_from(Task)) == (before or 0) + 6


async def test_no_exam_no_message(week: AsyncSession, settings: Settings) -> None:  # noqa: F811
    assert await job(week, settings, "exam_prep", at(2, 18)) is None  # nothing 2-7 days after 2 Nov


async def test_two_exams_do_not_share_an_hour(
    week: AsyncSession,  # noqa: F811
    settings: Settings,  # noqa: F811
) -> None:
    ctx = context(week, "academic")
    added = await run_tool(
        "add_event",
        {"kind": "exam", "title": "EE211 Vize", "date": "2026-11-26", "start_time": "13:00"},
        ctx,
    )
    assert "error" not in added
    await week.commit()
    message = await job(week, settings, "exam_prep", at(20, 18))
    assert message is not None
    proposals = (await week.scalars(select(Proposal).order_by(Proposal.id))).all()
    assert len(proposals) == 2  # one per exam
    slots: dict[str, list[str]] = {}
    for proposal in proposals:
        for entry in proposal.entries:
            time = entry["title"].split(" tekrar ")[1].split(":")[0:2]
            slots.setdefault(entry["date"], []).append(":".join(time))
    for day, times in slots.items():
        assert len(times) == len(set(times)), (day, times)  # never the same start
    # no syllabus: a few sessions, not one every day
    assert len(proposals[0].entries) == 3
