"""B from real use: "Pazartesi DSA sınavında linked list, stack, queue çıkacakmış" -> the exam
is saved (DSA asked once, then remembered as an alias), its topics go into the event, the
answer comes at once and the review plan is drafted in the background as its own message."""

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.tools import run_tool
from app.api.chat import adds_an_exam
from app.config import Settings
from app.db.models import Course, Event, JobRun, Message
from app.db.models.enums import EventKind
from app.jobs.content import Voice
from app.jobs.exam_prep import draft_exam_prep, plan_exam
from app.jobs.runner import run_job
from tests.agent_fakes import NOW, ScriptedLLM, call, example_team, route_as, say
from tests.db.test_agent_tools import context

TEXT = "Pazartesi DSA sınavında linked list, stack, queue çıkcakmış"
TOPICS = ["linked list", "stack", "queue"]
EXAM = {
    "kind": "exam",
    "title": "DSA sınavı",
    "date": "2026-11-30",
    "course": "DSA",
    "topics": TOPICS,
}
TZ = Settings(_env_file=None).tz


async def courses(session: AsyncSession) -> None:
    session.add_all(
        [Course(code="CSE 211", name="CSE 211"), Course(code="CSE 221", name="CSE 221")]
    )
    await session.commit()


async def test_topics_go_into_the_exam_and_the_answer_mentions_the_plan(
    session: AsyncSession,
) -> None:
    await courses(session)
    ctx = context(session, "academic")
    await run_tool("add_course_alias", {"course": "CSE 211", "alias": "DSA"}, ctx)

    result = await run_tool("add_event", {**EXAM, "date": "2026-11-26"}, ctx)

    [event] = (await session.scalars(select(Event))).all()
    assert event.notes == "Konular: linked list, stack, queue"
    assert result["review_plan"].startswith("drafted now")
    later = await run_tool("add_event", {**EXAM, "date": "2026-12-14", "title": "final"}, ctx)
    assert later["review_plan"] == "proposed in the chat a week before the exam"


async def test_the_review_plan_uses_the_topics_without_a_syllabus(session: AsyncSession) -> None:
    await courses(session)
    ctx = context(session, "academic")
    await run_tool("add_course_alias", {"course": "CSE 211", "alias": "DSA"}, ctx)
    await run_tool("add_event", EXAM, ctx)  # Monday 30 Nov, a week away
    exam = await session.scalar(select(Event))
    assert exam is not None

    entries, topics, _ = await plan_exam(session, exam, dt.date(2026, 11, 23), TZ)
    drafted = await draft_exam_prep(session, dt.date(2026, 11, 25), TZ, Voice(example_team(), True))

    titles = [str(e["title"]) for e in entries]
    assert topics == TOPICS
    assert [t.split(":")[-1].strip() for t in titles[:-1]] == TOPICS  # a day per topic
    assert titles[-1].endswith("linked list, stack, queue + soru çözümü")
    assert drafted is not None
    assert "Konular (senin söylediğin): linked list, stack, queue" in drafted[0]


async def test_dsa_is_asked_once_then_the_exam_is_saved_and_the_plan_follows(
    session: AsyncSession,
) -> None:
    await courses(session)
    after: list[ChatReply] = []
    llm = ScriptedLLM()
    coordinator = Coordinator(
        llm, example_team(), Settings(_env_file=None), after_message=after.append
    )
    # 1) the exam goes to Scholar; DSA matches no course: one question
    llm.add("intent", route_as(("exam", TEXT)))
    llm.add(
        "academic",
        call("resolve_date", expression="pazartesi", direction="future"),
        call("add_event", **EXAM),
        say("DSA hangi ders: CSE 211 mi, CSE 221 mi?"),
    )
    llm.add("yaver", say("Scholar: DSA hangi ders, CSE 211 mi, CSE 221 mi?"))
    first = await coordinator.handle(session, TEXT, now=NOW)
    assert first.change_set_id is None
    assert not adds_an_exam(first)

    # 2) "cse 211" answers it: alias, then the exam with its topics
    def classify(request: Any) -> Any:
        assert "DSA hangi ders" in request.messages[0].content
        return route_as(("answer", "cse 211"))

    llm.add("intent", classify)
    llm.add(
        "academic",
        call("add_course_alias", course="CSE 211", alias="DSA"),
        call("add_event", **EXAM),
        say("CSE 211 sınavını 30 Kasım Pazartesi'ye ekledim; tekrar planı birazdan geliyor."),
    )
    second = await coordinator.handle(
        session, "cse 211", conversation_id=first.conversation_id, now=NOW
    )

    [exam] = (await session.scalars(select(Event))).all()
    course = await session.scalar(select(Course).where(Course.code == "CSE 211"))
    assert course is not None
    assert (exam.kind, exam.course_id, exam.notes) == (
        EventKind.EXAM,
        course.id,
        "Konular: linked list, stack, queue",
    )
    assert course.aliases == ["DSA"]
    assert adds_an_exam(second)
    assert after == [first, second]  # the API starts the review plan from the second
    llm.assert_done()


async def test_the_extra_run_writes_the_plan_message_but_not_the_days_run(
    session: AsyncSession,
) -> None:
    """The background run after the chat: a message of its own; the daily 18:00 run still
    happens (no JobRun for today)."""
    await courses(session)
    ctx = context(session, "academic")
    await run_tool("add_course_alias", {"course": "CSE 211", "alias": "DSA"}, ctx)
    await run_tool("add_event", {**EXAM, "date": "2026-11-26"}, ctx)
    await session.commit()

    message_id = await run_job(
        "exam_prep",
        now=NOW,
        settings=Settings(_env_file=None),
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        team=example_team(),
        force=True,
        record=False,
    )

    message = await session.get(Message, message_id)
    assert message is not None
    assert "Konular (senin söylediğin): linked list, stack, queue" in message.content
    assert (await session.scalars(select(JobRun))).all() == []
