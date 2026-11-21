"""Sunday evening weekly planning: the smart tier looks at the coming week (classes,
exams, absences near the limit, follow-ups, open tasks) and drafts tasks for it. The draft
is a proposal: shown as a table, written into tasks only after the user's "evet"."""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import json_schema
from app.core.localtime import local_datetime
from app.db.models import Course, Event, Followup, Proposal, Task
from app.db.models.enums import EventKind, FollowupStatus, ProposalKind, TaskStatus
from app.jobs.content import day_name
from app.llm.types import ChatMessage, LLMRequest, ToolSpec
from app.services.attendance import course_summary
from app.services.schedule import get_day_plan

PURPOSE = "weekly_plan"  # routing.purposes -> smart
MAX_TASKS = 12


class DraftTask(BaseModel):
    title: str = Field(description="short, Turkish, concrete ('EE211 ara sınav: devre çöz')")
    date: dt.date | None = Field(None, description="a day of the planned week; omit = week task")
    why: str | None = Field(None, description="a few words: 'sınav 27 Kasım'")


class WeekDraft(BaseModel):
    summary: str = Field(description="2-3 Turkish sentences: what the week looks like")
    tasks: list[DraftTask] = Field(max_length=MAX_TASKS)


TOOL = ToolSpec("week_draft", "Return the week's plan draft.", json_schema(WeekDraft))
PROMPT = (
    "You plan the coming week of a Turkish university student, from the facts given only "
    "(never invent classes, exams or dates). Call week_draft once.\n"
    "- Suggest at most 10 concrete tasks: study blocks before exams (spread over the days "
    "before them), catching up on missed classes, chasing follow-ups, the open tasks.\n"
    "- Put a task on a light day; a date must be one of the week's days listed; no date = "
    "something for the whole week.\n"
    "- Turkish, short titles; address the student as 'sen'."
)


def next_monday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)


async def week_facts(session: AsyncSession, monday: dt.date, tz: ZoneInfo) -> str:
    lines = [f"Planned week: {day_name(monday)} - {day_name(monday + dt.timedelta(days=6))}"]
    for offset in range(7):
        day = monday + dt.timedelta(days=offset)
        plan = await get_day_plan(session, day, tz)
        items = [
            f"{'tüm gün' if i.all_day else f'{i.start:%H:%M}'} {i.title} ({i.kind})"
            for i in plan.items
        ]
        holiday = f" [tatil: {', '.join(plan.holidays)}]" if plan.holidays else ""
        lines.append(f"- {day.isoformat()} {day_name(day)}{holiday}: {'; '.join(items) or 'boş'}")
    start = local_datetime(monday, dt.time(), tz)
    exams = (
        await session.scalars(
            select(Event)
            .where(
                Event.kind.in_((EventKind.EXAM, EventKind.QUIZ, EventKind.DEADLINE)),
                Event.start_at >= start,
                Event.start_at < start + dt.timedelta(days=14),
            )
            .order_by(Event.start_at)
        )
    ).all()
    for exam in exams:
        lines.append(
            f"Exam/deadline: {exam.title} on {day_name(exam.start_at.astimezone(tz).date())}"
        )
    for course in (await session.scalars(select(Course).order_by(Course.code))).all():
        summary = await course_summary(session, course)
        if summary["absent_hours"]:
            limit = summary.get("limit_hours")
            lines.append(
                f"Absences {course.code}: {summary['absent_hours']} h"
                + (f" of {limit} h allowed" if limit is not None else "")
            )
    followups = (
        await session.scalars(select(Followup).where(Followup.status == FollowupStatus.WAITING))
    ).all()
    lines += [f"Waiting for: {f.title}" for f in followups]
    open_tasks = (
        await session.scalars(
            select(Task).where(
                Task.status == TaskStatus.TODO,
                (Task.week_start == monday) | (Task.date >= monday),
            )
        )
    ).all()
    lines += [f"Already planned task: {t.title}" for t in open_tasks]
    return "\n".join(lines)


def tasks_table(entries: list[dict[str, Any]]) -> str:
    lines = ["| Gün | Görev | Neden |", "|---|---|---|"]
    for entry in entries:
        when = (
            day_name(dt.date.fromisoformat(entry["date"])) if entry.get("date") else "Hafta boyunca"
        )
        lines.append(f"| {when} | {entry['title']} | {entry.get('why') or ''} |")
    return "\n".join(lines)


async def draft_week(
    session: AsyncSession, llm: Any, today: dt.date, tz: ZoneInfo
) -> tuple[str, str] | None:
    """(message, context) for the chat, or None when the model gave nothing usable."""
    monday = next_monday(today)
    response = await llm.complete(
        LLMRequest(
            system=PROMPT,
            messages=[ChatMessage("user", await week_facts(session, monday, tz))],
            tools=[TOOL],
            tool_choice="required",
            max_tokens=4096,
        ),
        purpose=PURPOSE,
        agent_id="weekly_planner",
    )
    call = next((c for c in response.tool_calls if c.name == TOOL.name), None)
    try:
        draft = WeekDraft.model_validate(call.arguments if call and call.arguments else {})
    except ValidationError:
        return None
    sunday = monday + dt.timedelta(days=6)
    entries = [
        {
            "title": t.title,
            "date": t.date.isoformat() if t.date else None,
            "why": t.why,
            "week_start": monday.isoformat(),
        }
        for t in draft.tasks
        if t.date is None or monday <= t.date <= sunday  # a date outside the week is dropped
    ]
    if not entries:
        return None
    proposal = Proposal(
        kind=ProposalKind.TASKS,
        source_text=f"[haftalık plan {monday.isoformat()}]",
        entries=entries,
        parsed_by=f"{response.provider}/{response.model}",
    )
    session.add(proposal)
    await session.flush()
    message = (
        f"Haftalık plan taslağı 🗓 ({day_name(monday)} haftası)\n\n{draft.summary}\n\n"
        f'{tasks_table(entries)}\n\nUygun mu? "Evet" dersen görevlere yazarım; '
        "değiştirmek istediğini söylemen yeter."
    )
    context = f"[Haftalık plan taslağı -> öneri #{proposal.id}, henüz kaydedilmedi]"
    return message, context
