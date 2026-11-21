"""The task board (görev panosu): the employees' inboxes as kanban columns.

waiting   Bekliyor       today's scheduled work not run yet (shift jobs, rituals)
running   Çalışıyor      employee_tasks still running
approval  Onay bekliyor  the latest task of an employee whose question waits for the user
done      Bitti          finished tasks of the last days (failed ones marked)
"""

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.team import TeamConfig
from app.config import Settings
from app.core.localtime import local_datetime
from app.db.models import EmployeeTask, JobRun
from app.db.models.enums import EmployeeTaskStatus, TaskOrigin
from app.office.budget import day_start
from app.office.shift_jobs import shift_plans
from app.office.state import QUESTION, Office

DONE_DAYS = 3
DONE_LIMIT = 30
# Rituals and Yaver's own scheduled messages: (job id, title, settings field).
RITUALS = [
    ("briefing", "Sabah standup'ı ve brifing", "briefing_time"),
    ("exam_prep", "Sınav tekrar planı", "exam_prep_time"),
    ("checkin", "Akşam check-in", "checkin_time"),
    ("day_report", "Gün sonu raporu", "day_report_time"),
    ("weekly_plan", "Haftalık toplantı ve plan", "weekly_plan_time"),
]
RITUAL_EMPLOYEES = {"exam_prep": "academic", "checkin": "discipline"}


def _task_card(task: EmployeeTask, column: str) -> dict[str, Any]:
    return {
        "id": f"task:{task.id}",
        "column": column,
        "employee_id": task.employee_id,
        "title": task.instruction,
        "source": task.source.value,
        "requested_by": task.requested_by,
        "status": task.status.value,
        "result": task.result,
        "at": (task.finished_at or task.started_at or task.created_at).isoformat(),
    }


async def board(
    session: AsyncSession,
    config: TeamConfig,
    settings: Settings,
    office: Office | None,
    now: dt.datetime,
) -> dict[str, Any]:
    tz = settings.tz
    local = now.astimezone(tz)
    today = local.date()
    ran = set((await session.scalars(select(JobRun.job_id).where(JobRun.run_on == today))).all())
    ids = {config.coordinator.id, *(a.id for a in config.agents)}
    cards: list[dict[str, Any]] = []

    def scheduled(key: str, employee: str, title: str, at: str, weekday: int | None) -> None:
        if key in ran or (weekday is not None and weekday != local.weekday()):
            return
        if employee not in ids or at < f"{local:%H:%M}":
            return  # past its time today without running: not "waiting" any more
        cards.append(
            {
                "id": f"job:{key}",
                "column": "waiting",
                "employee_id": employee,
                "title": title,
                "source": "shift",
                "status": "scheduled",
                "at": local_datetime(today, dt.time.fromisoformat(at), tz).isoformat(),
            }
        )

    for job_id, title, field in RITUALS:
        employee = RITUAL_EMPLOYEES.get(job_id, config.coordinator.id)
        if employee not in ids:
            employee = config.coordinator.id
        scheduled(
            job_id,
            employee,
            title,
            getattr(settings, field),
            6 if job_id == "weekly_plan" else None,
        )
    for plan in shift_plans(config):
        scheduled(plan.key, plan.employee_id, plan.title, plan.job.at, plan.job.weekday)

    since = day_start(now, tz) - dt.timedelta(days=DONE_DAYS - 1)
    tasks = (
        await session.scalars(
            select(EmployeeTask)
            .where(EmployeeTask.created_at >= since)
            .order_by(EmployeeTask.id.desc())
            .limit(200)
        )
    ).all()
    asking = set()
    if office is not None and office.ready:
        asking = {
            e
            for e in office.employees
            if (state := office.state(e)) is not None
            and state.needs_user
            and state.needs_user_reason == QUESTION
        }
    latest_seen: set[str] = set()
    done = 0
    for task in tasks:
        if task.employee_id not in ids:
            continue
        # the question waits on the latest chat task (shift jobs never ask the user)
        asked_here = task.source is not TaskOrigin.SHIFT and task.employee_id not in latest_seen
        if task.source is not TaskOrigin.SHIFT:
            latest_seen.add(task.employee_id)
        if task.status is EmployeeTaskStatus.RUNNING:
            cards.append(_task_card(task, "running"))
        elif asked_here and task.employee_id in asking:
            cards.append(_task_card(task, "approval"))
        elif done < DONE_LIMIT:
            cards.append(_task_card(task, "done"))
            done += 1
    cards.sort(key=lambda c: c["at"], reverse=False)
    return {
        "columns": ["waiting", "running", "approval", "done"],
        "cards": cards,
        "ts": now.isoformat(),
    }
