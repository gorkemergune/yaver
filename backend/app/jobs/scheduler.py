"""APScheduler with its jobs in PostgreSQL: briefing, evening check-in, follow-ups.

- Cron triggers in APP_TIMEZONE at BRIEFING_TIME / CHECKIN_TIME / FOLLOWUP_TIME.
- misfire_grace_time: a run missed while the computer slept still happens on wake-up,
  within the job's window; coalesce: several missed runs become one.
- Startup catch-up: when the API starts after today's time but inside the window (the
  computer was off at 08:00), the job runs now. job_runs keeps it to once a day.
"""

import datetime as dt
import logging
from dataclasses import dataclass

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import make_url

from app.config import Settings, get_settings
from app.jobs.runner import JobId, parse_hhmm, run_job
from app.office.state import get_office

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Plan:
    job_id: JobId
    at: dt.time
    window: dt.timedelta  # how late it may still run (misfire / catch-up)
    weekday: int | None = None  # only on this day (0 = Monday); None = every day


def plans(settings: Settings) -> list[Plan]:
    checkin = parse_hhmm(settings.checkin_time)
    until_midnight = dt.timedelta(hours=23 - checkin.hour, minutes=59 - checkin.minute)
    weekly = parse_hhmm(settings.weekly_plan_time)
    weekly_window = min(
        dt.timedelta(hours=3), dt.timedelta(hours=23 - weekly.hour, minutes=59 - weekly.minute)
    )
    return [
        Plan("weekly_plan", weekly, weekly_window, weekday=6),
        Plan("briefing", parse_hhmm(settings.briefing_time), dt.timedelta(hours=8)),
        Plan("checkin", checkin, min(dt.timedelta(hours=3), until_midnight)),
        Plan("followups", parse_hhmm(settings.followup_time), dt.timedelta(hours=8)),
        Plan("exam_prep", parse_hhmm(settings.exam_prep_time), dt.timedelta(hours=4)),
    ]


async def run_scheduled(job_id: JobId) -> None:
    """Entry point stored in the job store (importable, arguments are plain strings)."""
    try:
        await run_job(job_id, office=get_office())
    except Exception:  # a failing job must not stop the scheduler
        logger.exception("Scheduled job %s failed", job_id)


def jobstore_url(settings: Settings) -> str:
    """The job store is synchronous: same database, psycopg driver."""
    url = make_url(settings.database_url).set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def start_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    settings = settings or get_settings()
    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=jobstore_url(settings))},
        timezone=settings.tz,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    for plan in plans(settings):
        scheduler.add_job(
            run_scheduled,
            CronTrigger(
                day_of_week="*" if plan.weekday is None else str(plan.weekday),
                hour=plan.at.hour,
                minute=plan.at.minute,
                timezone=settings.tz,
            ),
            args=[plan.job_id],
            id=plan.job_id,
            name=plan.job_id,
            replace_existing=True,  # times changed in .env take effect on restart
            misfire_grace_time=int(plan.window.total_seconds()),
        )
    scheduler.start()
    logger.info(
        "Scheduler started: %s", ", ".join(f"{p.job_id} {p.at:%H:%M}" for p in plans(settings))
    )
    return scheduler


def due_now(settings: Settings, now: dt.datetime) -> list[JobId]:
    """Jobs whose time today has passed but whose window is still open."""
    local = now.astimezone(settings.tz)
    due = []
    for plan in plans(settings):
        if plan.weekday is not None and local.weekday() != plan.weekday:
            continue
        start = dt.datetime.combine(local.date(), plan.at, tzinfo=settings.tz)
        if start <= local <= start + plan.window:
            due.append(plan.job_id)
    return due


async def catch_up(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for job_id in due_now(settings, dt.datetime.now(dt.UTC)):
        await run_scheduled(job_id)
