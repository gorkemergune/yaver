"""Scheduled messages: morning briefing, evening check-in, follow-ups; once a day each."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.team import load_team_config
from app.agent.tools import run_tool
from app.config import Settings
from app.db.models import Followup, JobRun, Message
from app.db.models.enums import FollowupCheckRule, MessageRole
from app.jobs.runner import run_job
from app.jobs.scheduler import due_now, jobstore_url, start_scheduler
from app.office.shift_jobs import shift_plans
from tests.agent_fakes import example_team
from tests.db.test_agent_tools import context

IST = dt.timezone(dt.timedelta(hours=3))


def at(day: int, hour: int, minute: int = 0) -> dt.datetime:
    """A moment in November 2026, Istanbul time."""
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=IST)


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(_env_file=None, database_url=database_url, app_user_name="Görkem")


@pytest.fixture
async def week(session: AsyncSession) -> AsyncSession:
    """Monday 23 Nov: Linear 09-11 (limit 4 h, 2 h used), meeting, sport Tue, exam Fri, a task."""
    ctx = context(session, "academic")
    calls: list[tuple[str, dict[str, Any]]] = [
        (
            "add_recurring_block",
            {
                "kind": "class",
                "title": "Linear Algebra",
                "course": "MATH221",
                "weekdays": ["monday"],
                "start_time": "09:00",
                "end_time": "11:00",
                "location": "B204",
            },
        ),
        (
            "add_recurring_block",
            {
                "kind": "sport",
                "title": "Spor",
                "weekdays": ["monday"],
                "start_time": "19:00",
                "end_time": "20:00",
            },
        ),
        (
            "add_event",
            {
                "kind": "meeting",
                "title": "Iceberg toplantısı",
                "date": "2026-11-23",
                "start_time": "14:00",
            },
        ),
        (
            "add_event",
            {
                "kind": "exam",
                "title": "MATH221 Ara Sınav",
                "date": "2026-11-27",
                "start_time": "10:00",
                "course": "MATH221",
            },
        ),
        ("add_task", {"title": "Rapor yaz", "date": "2026-11-23"}),
        ("set_absence_limit", {"course": "MATH221", "hours": 4}),
        ("log_attendance", {"course": "MATH221", "dates": ["2026-11-16"]}),
    ]
    for name, args in calls:
        result = await run_tool(name, args, ctx)
        assert "error" not in result, (name, result)
    await session.commit()
    return session


async def job(
    session: AsyncSession, settings: Settings, job_id: Any, now: dt.datetime
) -> Message | None:
    message_id = await run_job(
        job_id,
        now=now,
        settings=settings,
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        team=example_team(),
    )
    return await session.get(Message, message_id) if message_id else None


async def test_morning_briefing(week: AsyncSession, settings: Settings) -> None:
    message = await job(week, settings, "briefing", at(23, 8))
    again = await job(week, settings, "briefing", at(23, 9))

    assert message is not None
    text = message.content
    assert text.startswith("Günaydın, Görkem! Bugün 23 Kasım Pazartesi.")
    assert "- **Atlas** · Dersler: 09:00-11:00 Linear Algebra (B204)" in text
    assert "MATH221 Ara Sınav 4 gün sonra (27 Kasım Cuma 10:00)" in text
    assert "MATH221 için 2 saat hakkın kaldı" in text
    assert "14:00 Iceberg toplantısı" in text
    assert "19:00-20:00 Spor" in text
    assert "Rapor yaz" in text
    assert (message.kind, message.role, message.agent_id) == (
        "briefing",
        MessageRole.ASSISTANT,
        "yaver",
    )
    assert again is None  # once a day
    runs = await week.scalar(select(func.count()).select_from(JobRun))
    assert runs == 1


async def test_evening_checkin_and_the_reminder_next_morning(
    week: AsyncSession, settings: Settings
) -> None:
    checkin = await job(week, settings, "checkin", at(23, 21))
    assert checkin is not None
    assert checkin.kind == "checkin"
    assert "09:00-11:00 Linear Algebra (B204) - katıldı sayıyorum" in checkin.content
    assert "19:00-20:00 Spor - yaptın mı?" in checkin.content
    assert "Rapor yaz - bitti mi?" in checkin.content
    assert "✓ Hepsi tamam" in checkin.content

    # no answer -> reminded in the next briefing, once
    tuesday = await job(week, settings, "briefing", at(24, 8))
    wednesday = await job(week, settings, "briefing", at(25, 8))
    assert tuesday is not None
    assert "Dünkü akşam check-in'ine cevap vermedin" in tuesday.content
    assert wednesday is not None
    assert "check-in" not in wednesday.content


async def test_answered_checkin_is_not_reminded(week: AsyncSession, settings: Settings) -> None:
    checkin = await job(week, settings, "checkin", at(23, 21))
    assert checkin is not None
    week.add(
        Message(
            conversation_id=checkin.conversation_id, role=MessageRole.USER, content="✓ Hepsi tamam"
        )
    )
    await week.commit()

    briefing = await job(week, settings, "briefing", at(24, 8))

    assert briefing is not None
    assert "check-in" not in briefing.content


async def test_quiet_day_has_no_checkin(session: AsyncSession, settings: Settings) -> None:
    assert await job(session, settings, "checkin", at(28, 21)) is None
    run = await session.scalar(select(JobRun))
    assert run is not None
    assert run.status == "skipped"


async def test_followups_are_asked_when_due(session: AsyncSession, settings: Settings) -> None:
    session.add_all(
        [
            Followup(title="Hackathon kabulü", check_rule=FollowupCheckRule.DAILY),
            Followup(
                title="Staj cevabı", check_rule=FollowupCheckRule.EVERY_N_DAYS, every_n_days=3
            ),
            Followup(
                title="Burs sonucu",
                check_rule=FollowupCheckRule.ON_DATE,
                check_on=dt.date(2026, 11, 30),
            ),
        ]
    )
    await session.commit()

    monday = await job(session, settings, "followups", at(23, 12))
    tuesday = await job(session, settings, "followups", at(24, 12))

    assert monday is not None
    assert "- Hackathon kabulü" in monday.content
    assert "- Staj cevabı" in monday.content
    assert "Burs sonucu" not in monday.content  # its day is the 30th
    assert tuesday is not None
    assert "- Hackathon kabulü" in tuesday.content
    assert "Staj cevabı" not in tuesday.content  # every 3 days: next on Thursday
    staj = await session.scalar(select(Followup).where(Followup.title == "Staj cevabı"))
    assert staj is not None
    await session.refresh(staj)
    assert staj.next_check_at == dt.datetime(2026, 11, 26, 9, 0, tzinfo=dt.UTC)  # 12:00 Istanbul


def test_due_now_windows() -> None:
    # 08:00 briefing, 21:00 check-in, 12:00 follow-ups, 21:15 day report
    settings = Settings(_env_file=None, briefing_time="08:00")

    assert due_now(settings, at(23, 7, 59)) == []
    assert due_now(settings, at(23, 10)) == ["briefing"]  # computer turned on at 10:00
    assert due_now(settings, at(23, 15)) == ["briefing", "followups"]
    assert due_now(settings, at(23, 17)) == ["followups"]  # briefing window (8 h) is over
    assert due_now(settings, at(23, 23, 30)) == ["checkin", "day_report"]


async def test_scheduler_keeps_its_jobs_in_postgres(settings: Settings) -> None:
    scheduler = start_scheduler(settings)
    try:
        jobs = {job.id: job for job in scheduler.get_jobs()}
        core = {"briefing", "checkin", "followups", "weekly_plan", "exam_prep", "day_report"}
        # plus every employee's shift jobs from agents.yaml (app.office.shift_jobs)
        shifts = {p.key for p in shift_plans(load_team_config())}
        assert set(jobs) == core | shifts
        assert all(key.startswith("shift:") for key in shifts)
        assert jobs["weekly_plan"].next_run_time.astimezone(IST).weekday() == 6  # Sunday
        assert jobs["checkin"].next_run_time.astimezone(IST).time() == dt.time(21, 0)
        assert jobs["briefing"].misfire_grace_time == 8 * 3600
    finally:
        scheduler.shutdown(wait=False)
        # the job store's own table: not ours, it would upset the migration tests
        engine = create_engine(jobstore_url(settings))
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS apscheduler_jobs"))
        engine.dispose()


# --- weekly plan (Sunday evening) ---------------------------------------------------------


def draft_llm(*tasks: dict[str, Any]) -> Any:
    from tests.agent_fakes import ScriptedLLM, call

    return ScriptedLLM(
        {
            "weekly_planner": [
                call(
                    "week_draft",
                    summary="Yoğun bir hafta: Cuma sınavın var.",
                    tasks=list(tasks),
                )
            ]
        }
    )


async def test_weekly_plan_is_a_proposal_until_yes(week: AsyncSession, settings: Settings) -> None:
    llm = draft_llm(
        {"title": "MATH221: çalışma 1", "date": "2026-11-24", "why": "sınav 27 Kasım"},
        {"title": "Rapor", "why": "hafta içinde"},
        {"title": "Geçen haftaya ait", "date": "2026-11-20"},  # outside the week: dropped
    )
    sunday = at(22, 20)

    message_id = await run_job(
        "weekly_plan",
        now=sunday,
        settings=settings,
        sessionmaker=async_sessionmaker(week.bind, expire_on_commit=False),
        team=example_team(),
        llm=llm,
    )

    message = await week.get(Message, message_id)
    assert message is not None
    assert message.kind == "weekly_plan"
    assert "| 24 Kasım Salı | MATH221: çalışma 1 | sınav 27 Kasım |" in message.content
    assert "| Hafta boyunca | Rapor | hafta içinde |" in message.content
    assert "Geçen haftaya ait" not in message.content
    assert message.context == "[Haftalık plan taslağı -> öneri #1, henüz kaydedilmedi]"
    facts = llm.requests[0][1].messages[0].content
    assert "2026-11-23 23 Kasım Pazartesi: 09:00 Linear Algebra (class)" in facts
    assert "Exam/deadline: MATH221 Ara Sınav on 27 Kasım Cuma" in facts
    assert "Absences MATH221: 2 h of 4 h allowed" in facts
    assert llm.purposes == ["weekly_plan"]  # -> smart tier

    ctx = context(week, "agenda")  # Monday: "evet"
    applied = await run_tool("apply_proposal", {"proposal_id": 1}, ctx)
    assert [t["date"] for t in applied["tasks_created"]] == ["2026-11-24", "hafta"]


async def test_history_keeps_sundays_plan_behind_mondays_briefing(
    week: AsyncSession, settings: Settings
) -> None:
    from tests.agent_fakes import ScriptedLLM, coordinator

    maker = async_sessionmaker(week.bind, expire_on_commit=False)
    llm = draft_llm({"title": "Rapor"})
    await run_job(
        "weekly_plan",
        now=at(22, 20),
        settings=settings,
        sessionmaker=maker,
        team=example_team(),
        llm=llm,
    )
    briefing = await job(week, settings, "briefing", at(23, 8))
    assert briefing is not None

    history = await coordinator(ScriptedLLM())._history(week, briefing.conversation_id)

    assert history == []  # nothing from the user yet: no turn to answer
    week.add(
        Message(conversation_id=briefing.conversation_id, role=MessageRole.USER, content="evet")
    )
    week.add(
        Message(
            conversation_id=briefing.conversation_id,
            role=MessageRole.ASSISTANT,
            agent_id="yaver",
            content="Tamam.",
        )
    )
    await week.commit()
    week.add(
        Message(
            conversation_id=briefing.conversation_id,
            role=MessageRole.ASSISTANT,
            agent_id="yaver",
            content="Akşam check-in",
            kind="checkin",
        )
    )
    await week.commit()
    history = await coordinator(ScriptedLLM())._history(week, briefing.conversation_id)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == "Tamam.\n\nAkşam check-in"  # the scheduler message is kept


def test_weekly_plan_runs_on_sundays_only() -> None:
    settings = Settings(_env_file=None)

    assert "weekly_plan" in due_now(settings, at(22, 21))  # Sunday 21:00
    assert "weekly_plan" not in due_now(settings, at(23, 21))  # Monday


async def test_run_a_job_now_over_http(week: AsyncSession, settings: Settings) -> None:
    import httpx2

    from app.agent.team import get_team
    from app.api.auth import require_auth
    from app.api.chat import get_session_factory
    from app.main import create_app
    from app.office.state import get_office

    app = create_app()
    app.dependency_overrides[require_auth] = lambda: None  # login: tests/db/test_auth.py
    app.dependency_overrides[get_session_factory] = lambda: async_sessionmaker(
        week.bind, expire_on_commit=False
    )
    app.dependency_overrides[get_team] = example_team
    app.dependency_overrides[get_office] = lambda: None  # never the real database's office
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        first = (await http.post("/api/jobs/followups/run")).json()
        unknown = await http.post("/api/jobs/nope/run")

    assert first == {"job": "followups", "message_id": None}  # nothing due
    assert unknown.status_code == 404


async def test_yes_to_the_weekly_plan_saves_it_in_code(
    week: AsyncSession, settings: Settings
) -> None:
    from app.db.models import Conversation, Task
    from tests.agent_fakes import NOW, ScriptedLLM, coordinator, say

    llm = draft_llm({"title": "Rapor", "why": "hafta içinde"})
    message_id = await run_job(
        "weekly_plan",
        now=at(22, 20),
        settings=settings,
        sessionmaker=async_sessionmaker(week.bind, expire_on_commit=False),
        team=example_team(),
        llm=llm,
    )
    message = await week.get(Message, message_id)
    assert message is not None
    conversation = await week.get(Conversation, message.conversation_id)
    assert conversation is not None
    await week.refresh(conversation)
    assert conversation.pending_action is not None
    assert conversation.pending_action["tool"] == "apply_proposal"

    chat = ScriptedLLM()
    chat.add("yaver", say("Planı görevlere yazdım."))  # one answer, no tool turn
    reply = await coordinator(chat).handle(week, "Evet", conversation_id=conversation.id, now=NOW)
    assert [(t["tool"], t["arguments"]) for t in reply.trace] == [
        ("apply_proposal", {"proposal_id": 1})
    ]
    assert reply.change_set_id is not None
    assert "Rapor" in [t.title for t in (await week.scalars(select(Task))).all()]  # + seeded
    chat.assert_done()
