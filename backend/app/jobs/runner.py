"""Runs one scheduled job for today: builds its message and writes it into the chat.

A job runs at most once per local day (job_runs is unique per job and day): the regular
trigger, a misfire run after the computer slept and the startup catch-up can all fire,
the message is written once.
"""

import datetime as dt
import logging
import re
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.pending import proposal_pending
from app.agent.team import Team, get_team, load_team_config
from app.config import Settings, get_settings
from app.db.models import Conversation, JobRun, Message
from app.db.models.enums import ConversationMode, MessageRole
from app.db.session import get_sessionmaker
from app.jobs.content import Voice, build_briefing, build_checkin, build_followups
from app.jobs.exam_prep import draft_exam_prep
from app.jobs.weekly_plan import draft_week
from app.llm.router import get_router
from app.office.rituals import day_report, meeting, standup_reports, standup_section
from app.office.shifts import OverBudgetError, run_shift
from app.office.state import Office
from app.services.push import Notification, preview, send_push

logger = logging.getLogger(__name__)
PROPOSAL_NOTE = re.compile(r"öneri #(\d+)")

JobId = Literal["briefing", "checkin", "followups", "weekly_plan", "exam_prep", "day_report"]
JOB_IDS: tuple[JobId, ...] = (
    "briefing",
    "checkin",
    "followups",
    "weekly_plan",
    "exam_prep",
    "day_report",
)
# Notification titles; the body is the start of the chat message.
PUSH_TITLES: dict[str, str] = {
    "briefing": "Günaydın ☀️",
    "checkin": "Akşam check-in 🌙",
    "followups": "Takip: haber var mı?",
    "weekly_plan": "Haftalık plan taslağı",
    "exam_prep": "Sınav hazırlığı 📚",
    "day_report": "Gün sonu raporu 🌆",
}
# Whose shift each job is in the office (unknown ids: the coordinator's) and what it shows.
JOB_EMPLOYEES: dict[str, str] = {
    "checkin": "discipline",
    "followups": "agenda",
    "exam_prep": "academic",
}
SHIFT_TASKS: dict[str, str] = {
    "briefing": "Sabah standup'ı ve brifing",
    "checkin": "Akşam check-in'ini hazırlıyor",
    "followups": "Bekleyen takipleri soruyor",
    "weekly_plan": "Haftalık plan taslağını yazıyor",
    "exam_prep": "Sınav tekrar planını çıkarıyor",
    "day_report": "Gün sonu raporunu yazıyor",
}


def parse_hhmm(value: str) -> dt.time:
    return dt.time.fromisoformat(value)


async def run_job(
    job_id: JobId,
    *,
    now: dt.datetime | None = None,
    settings: Settings | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    team: Team | None = None,
    llm: Any = None,
    force: bool = False,
    office: Office | None = None,
) -> int | None:
    """The id of the message written, or None (already ran today / nothing to say /
    the employee's daily budget is used up: not recorded, so it can run after all).
    `force` runs it again today (the manual "run now" endpoint), whatever the budget."""
    settings = settings or get_settings()
    now = now or dt.datetime.now(dt.UTC)
    today = now.astimezone(settings.tz).date()
    sessionmaker = sessionmaker or get_sessionmaker()
    team = team or get_team()
    async with sessionmaker() as session:
        done = await session.scalar(
            select(JobRun.id).where(JobRun.job_id == job_id, JobRun.run_on == today)
        )
        if done is not None and not force:
            return None
        employee = JOB_EMPLOYEES.get(job_id, team.coordinator.id)
        if team.get(employee) is None:
            employee = team.coordinator.id
        try:
            text, context = await run_shift(
                office,
                employee,
                SHIFT_TASKS[job_id],
                lambda: _build(job_id, session, now, today, settings, team, llm, office),
                check_budget=not force,
            )
        except OverBudgetError:
            return None
        message_id = await _post(session, text, job_id, team, now, context) if text else None
        if done is None:
            session.add(
                JobRun(
                    job_id=job_id,
                    run_on=today,
                    status="sent" if text else "skipped",
                    message_id=message_id,
                )
            )
        try:
            await session.commit()
        except IntegrityError:  # another process wrote today's run first
            await session.rollback()
            return None
        if text and message_id:
            await _notify(session, settings, job_id, text, now)
    logger.info("Job %s for %s: %s", job_id, today, "sent" if message_id else "nothing to say")
    return message_id


async def _notify(
    session: AsyncSession, settings: Settings, job_id: JobId, text: str, now: dt.datetime
) -> None:
    """The message is in the chat already; a failed push must not fail the job."""
    notification = Notification(
        title=PUSH_TITLES[job_id], body=preview(text), url="/#/chat", tag=job_id
    )
    try:
        await send_push(session, settings, notification, now)
    except Exception:
        logger.exception("Web Push for %s failed", job_id)
        await session.rollback()


async def _build(
    job_id: JobId,
    session: AsyncSession,
    now: dt.datetime,
    today: dt.date,
    settings: Settings,
    team: Team,
    llm: Any = None,
    office: Office | None = None,
) -> tuple[str | None, str | None]:
    """(message, hidden context replayed to the model) for the job. With the office, the
    briefing starts with the standup and the weekly plan is drafted in a meeting."""
    config = load_team_config()
    voice = Voice(team, config.briefing_style != "single_voice")
    host = team.coordinator.id
    if job_id == "weekly_plan":
        async with meeting(office, host, config.weekly_plan.order, "Haftalık toplantı"):
            drafted = await draft_week(session, llm or get_router(), today, settings.tz)
        return drafted if drafted else (None, None)
    if job_id == "day_report":
        return await day_report(session, team, llm or get_router(), now, settings.tz), None
    if job_id == "exam_prep":
        prepared = await draft_exam_prep(session, today, settings.tz, voice)
        return prepared if prepared else (None, None)
    if job_id == "briefing":
        text: str | None = await build_briefing(
            session,
            today,
            settings.tz,
            voice,
            settings.app_user_name,
            unanswered_checkin=await _checkin_unanswered(session, today - dt.timedelta(days=1)),
        )
        if office is not None:  # the office's morning: everyone meets, then the briefing
            guests = [a.id for a in team.agents]
            async with meeting(office, host, guests, "Sabah standup'ı"):
                lines = await standup_reports(
                    session, team, llm or get_router(), now, settings.tz, config, office
                )
            if text and lines:
                text = f"{text}\n\n{standup_section(lines)}"
    elif job_id == "checkin":
        text = await build_checkin(session, today, settings.tz, voice)
    else:
        text = await build_followups(
            session, now, today, parse_hhmm(settings.followup_time), settings.tz, voice
        )
    return text, None


async def _checkin_unanswered(session: AsyncSession, day: dt.date) -> bool:
    """Yesterday's check-in got no message from the user afterwards (reminded once only:
    the briefing looks at yesterday alone)."""
    run = await session.scalar(
        select(JobRun).where(JobRun.job_id == "checkin", JobRun.run_on == day)
    )
    if run is None or run.message_id is None:
        return False
    checkin = await session.get(Message, run.message_id)
    if checkin is None:
        return False
    answer = await session.scalar(
        select(Message.id).where(
            Message.conversation_id == checkin.conversation_id,
            Message.role == MessageRole.USER,
            Message.id > checkin.id,
        )
    )
    return answer is None


async def _post(
    session: AsyncSession,
    text: str,
    kind: str,
    team: Team,
    now: dt.datetime,
    context: str | None = None,
) -> int:
    """Into the most recent chat (a new one if there is none), from the coordinator."""
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.mode == ConversationMode.CHAT, Conversation.employee_id.is_(None))
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(1)
    )
    if conversation is None:
        conversation = Conversation(title=team.coordinator.name)
        session.add(conversation)
        await session.flush()
    message = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        agent_id=team.coordinator.id,
        content=text,
        kind=kind,
        context=context,
    )
    session.add(message)
    conversation.updated_at = now
    # A newer message from Yaver: an older open question is not what the user answers next.
    conversation.pending_action = None
    proposals = PROPOSAL_NOTE.findall(context or "")
    if len(proposals) == 1:  # a draft table: the user's "evet" saves it (app.agent.pending)
        pending = proposal_pending(team.coordinator.id, text, int(proposals[0]))
        pending.question, pending.created_at = text, now.isoformat()
        conversation.pending_action = pending.dump()
    await session.flush()
    return message.id
