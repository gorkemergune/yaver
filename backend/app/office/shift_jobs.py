"""Shift jobs (mesai, docs/OFFICE.md): scheduled work of one employee, given in agents.yaml
(`shift_jobs`). Each run shows the employee working (office.shifts.run_shift: daily budget,
working -> break) and ends with a line in its notebook. No LLM: the notes are built by code
from the database or a web search, so they are free and never made up.

Job keys are "shift:<employee id>:<kind>" (job_runs keeps each to once a day).
"""

import datetime as dt
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.team import SHIFT_JOB_KINDS, ShiftJobConfig, TeamConfig, load_team_config
from app.config import Settings, get_settings
from app.core.time_resolver import MONTH_NAMES_TR, WEEKDAY_NAMES_TR
from app.db.models import Event, Followup, JobRun
from app.db.models.enums import EventKind, FollowupStatus
from app.db.session import get_sessionmaker
from app.integrations import web_search as search
from app.integrations.meta_ads import NO_CREDENTIALS, NOT_BUILT, ads_status
from app.office.notebook import note_event, write_note
from app.office.shifts import OverBudgetError, run_shift
from app.office.state import Office

logger = logging.getLogger(__name__)
PREFIX = "shift:"
HORIZON_DAYS = 7
SOCIAL_WORDS = ("doğum gün", "dogum gun", "parti", "buluş", "bulus", "kutlama", "düğün", "nişan")
DEFAULT_TITLES = {
    "web_scan": "Web taraması yapıyor",
    "ads_report": "Reklam metriklerine bakıyor",
    "social_reminders": "Hatırlatmaları topluyor",
    "followup_watch": "Bekleyen dönüşlere bakıyor",
    "deadline_watch": "Yaklaşan teslimlere bakıyor",
}
# Status notes (no data source yet) are written once a day, not on every run.
STATUS_NOTES = frozenset({search.PENDING_NOTE, NO_CREDENTIALS, NOT_BUILT})


@dataclass(frozen=True, slots=True)
class ShiftPlan:
    key: str
    employee_id: str
    job: ShiftJobConfig

    @property
    def title(self) -> str:
        return self.job.title or DEFAULT_TITLES[self.job.job]


def shift_plans(config: TeamConfig) -> list[ShiftPlan]:
    plans: list[ShiftPlan] = []
    for member in (config.coordinator, *config.agents):
        seen: dict[str, int] = {}
        for job in member.shift_jobs:
            n = seen[job.job] = seen.get(job.job, 0) + 1
            key = f"{PREFIX}{member.id}:{job.job}" + (f":{n}" if n > 1 else "")
            plans.append(ShiftPlan(key[:50], member.id, job))
    return plans


@dataclass(frozen=True, slots=True)
class ShiftContext:
    session: AsyncSession
    now: dt.datetime
    tz: dt.tzinfo
    job: ShiftJobConfig
    settings: Settings
    search: search.WebSearch | None

    @property
    def today(self) -> dt.date:
        return self.now.astimezone(self.tz).date()


def _day(local: dt.datetime) -> str:
    return f"{local.day} {MONTH_NAMES_TR[local.month - 1]} {WEEKDAY_NAMES_TR[local.weekday()]}"


async def _upcoming(ctx: ShiftContext) -> list[Event]:
    start = dt.datetime.combine(ctx.today, dt.time(), tzinfo=ctx.tz)
    end = start + dt.timedelta(days=HORIZON_DAYS + 1)
    rows = await ctx.session.scalars(
        select(Event).where(Event.start_at >= start, Event.start_at < end).order_by(Event.start_at)
    )
    return list(rows.all())


async def web_scan(ctx: ShiftContext) -> str | None:
    if ctx.search is None:
        return search.PENDING_NOTE
    lines = []
    for topic in ctx.job.topics:
        try:
            results = await ctx.search.search(topic, 3)
        except search.SearchError as exc:
            logger.warning("web_scan %r failed: %s", topic, exc)
            lines.append(f"{topic}: arama başarısız")
            continue
        found = "; ".join(f"{r.title} ({r.site})" for r in results) or "yeni bir şey yok"
        lines.append(f"{topic}: {found}")
    return "Tarama · " + " | ".join(lines) if lines else None


async def ads_report(ctx: ShiftContext) -> str | None:
    return ads_status(ctx.settings).note


async def social_reminders(ctx: ShiftContext) -> str | None:
    social = [
        e
        for e in await _upcoming(ctx)
        if any(w in f"{e.title} {e.notes or ''}".lower() for w in SOCIAL_WORDS)
    ]
    if not social:
        return None
    items = [f"{e.title} ({_day(e.start_at.astimezone(ctx.tz))})" for e in social]
    return f"Önümüzdeki {HORIZON_DAYS} gün: " + "; ".join(items)


async def followup_watch(ctx: ShiftContext) -> str | None:
    waiting = (
        await ctx.session.scalars(
            select(Followup).where(Followup.status == FollowupStatus.WAITING).order_by(Followup.id)
        )
    ).all()
    if not waiting:
        return None
    items = []
    for f in waiting:
        days = (ctx.now - f.created_at).days
        items.append(f"{f.title} ({days} gündür)" if days >= 1 else f.title)
    return "Dönüş bekleniyor: " + ", ".join(items)


async def deadline_watch(ctx: ShiftContext) -> str | None:
    due = [
        e
        for e in await _upcoming(ctx)
        if e.kind in (EventKind.DEADLINE, EventKind.HACKATHON) or "teslim" in e.title.lower()
    ]
    if not due:
        return None
    items = [f"{e.title} ({_day(e.start_at.astimezone(ctx.tz))})" for e in due]
    return "Yaklaşan teslimler: " + "; ".join(items)


JOBS: dict[str, Callable[[ShiftContext], Awaitable[str | None]]] = {
    "web_scan": web_scan,
    "ads_report": ads_report,
    "social_reminders": social_reminders,
    "followup_watch": followup_watch,
    "deadline_watch": deadline_watch,
}
assert set(JOBS) == set(SHIFT_JOB_KINDS), "every kind agents.yaml accepts has a job"


async def run_shift_job(
    key: str,
    *,
    now: dt.datetime | None = None,
    settings: Settings | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    config: TeamConfig | None = None,
    office: Office | None = None,
    web: search.WebSearch | bool | None = True,
    force: bool = False,
) -> str | None:
    """The note written, or None (unknown key, already ran today, nothing to say, over
    budget - not recorded then, so it can run once the budget allows). `force`: run again
    today, whatever the budget (the "run now" endpoint). `web`: True = from settings."""
    settings = settings or get_settings()
    config = config or load_team_config()
    plan = next((p for p in shift_plans(config) if p.key == key), None)
    if plan is None:
        logger.warning("Unknown shift job %s (removed from agents.yaml?)", key)
        return None
    now = now or dt.datetime.now(dt.UTC)
    today = now.astimezone(settings.tz).date()
    sessionmaker = sessionmaker or get_sessionmaker()
    provider = search.get_web_search() if web is True else (web or None)

    async with sessionmaker() as session:
        done = await session.scalar(
            select(JobRun.id).where(JobRun.job_id == plan.key, JobRun.run_on == today)
        )
        if done is not None and not force:
            return None
        ctx = ShiftContext(session, now, settings.tz, plan.job, settings, provider)

        async def work() -> str | None:
            return await JOBS[plan.job.job](ctx)

        try:
            text = await run_shift(
                office, plan.employee_id, plan.title, work, check_budget=not force
            )
        except OverBudgetError:
            return None
        note = None
        if text:
            note = await write_note(
                session,
                plan.employee_id,
                text,
                now,
                settings.tz,
                source="shift",
                once_a_day=text in STATUS_NOTES,
            )
        if done is None:
            session.add(JobRun(job_id=plan.key, run_on=today, status="sent" if text else "skipped"))
        try:
            await session.commit()
        except IntegrityError:  # another process ran it first
            await session.rollback()
            return None
    if note is not None and office is not None:
        office.publish_notes([note_event(note)])
    logger.info("Shift job %s: %s", plan.key, text or "nothing to note")
    return text


def is_shift(job_id: str) -> bool:
    return job_id.startswith(PREFIX)
