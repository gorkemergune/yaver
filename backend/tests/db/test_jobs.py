"""Scheduled messages: morning briefing, evening check-in, follow-ups; once a day each."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.tools import run_tool
from app.config import Settings
from app.db.models import Followup, JobRun, Message
from app.db.models.enums import FollowupCheckRule, MessageRole
from app.jobs.runner import run_job
from app.jobs.scheduler import due_now, jobstore_url, start_scheduler
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
    settings = Settings(_env_file=None)  # 08:00 briefing, 21:00 check-in, 12:00 follow-ups

    assert due_now(settings, at(23, 7, 59)) == []
    assert due_now(settings, at(23, 10)) == ["briefing"]  # computer turned on at 10:00
    assert due_now(settings, at(23, 15)) == ["briefing", "followups"]
    assert due_now(settings, at(23, 17)) == ["followups"]  # briefing window (8 h) is over
    assert due_now(settings, at(23, 23, 30)) == ["checkin"]


async def test_scheduler_keeps_its_jobs_in_postgres(settings: Settings) -> None:
    scheduler = start_scheduler(settings)
    try:
        jobs = {job.id: job for job in scheduler.get_jobs()}
        assert set(jobs) == {"briefing", "checkin", "followups"}
        assert jobs["checkin"].next_run_time.astimezone(IST).time() == dt.time(21, 0)
        assert jobs["briefing"].misfire_grace_time == 8 * 3600
    finally:
        scheduler.shutdown(wait=False)
        # the job store's own table: not ours, it would upset the migration tests
        engine = create_engine(jobstore_url(settings))
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS apscheduler_jobs"))
        engine.dispose()
