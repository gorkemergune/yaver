import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.agent.tools.matching import matches
from app.agent.tools.schedule import ISO_DATE
from app.core.time_resolver import week_start
from app.db.models import Event, Followup, Task
from app.db.models.enums import (
    FollowupCheckRule,
    FollowupStatus,
    TaskScope,
    TaskSource,
    TaskStatus,
)

# --- tasks -----------------------------------------------------------------------------


def describe_task(task: Task) -> dict[str, Any]:
    data: dict[str, Any] = {"task_id": task.id, "title": task.title, "status": task.status.value}
    if task.date:
        data["date"] = task.date.isoformat()
    if task.week_start:
        data["week_start"] = task.week_start.isoformat()
    return data


class AddTaskArgs(BaseModel):
    title: str
    date: dt.date | None = Field(None, description="for a one-day task, " + ISO_DATE)
    week_of: dt.date | None = Field(None, description="any date in the week, for a weekly task")

    @model_validator(mode="after")
    def _one_scope(self) -> "AddTaskArgs":
        if (self.date is None) == (self.week_of is None):
            raise ValueError("give exactly one of date / week_of")
        return self


@tool(
    "add_task", "Add a to-do for a day (date) or a whole week (week_of).", AddTaskArgs, mutates=True
)
async def add_task(args: AddTaskArgs, ctx: ToolContext) -> ToolResult:
    task = Task(
        title=args.title,
        scope=TaskScope.DAY if args.date else TaskScope.WEEK,
        date=args.date,
        week_start=week_start(args.week_of) if args.week_of else None,
        source=TaskSource.AGENT,
    )
    ctx.session.add(task)
    await ctx.recorder.created(task)
    return {"created": describe_task(task)}


class CompleteTaskArgs(BaseModel):
    task_id: int | None = None
    title: str | None = Field(None, description="if the id is not known")


@tool("complete_task", "Mark a task done.", CompleteTaskArgs, mutates=True)
async def complete_task(args: CompleteTaskArgs, ctx: ToolContext) -> ToolResult:
    if args.task_id is not None:
        task = await ctx.session.get(Task, args.task_id)
        candidates = [task] if task else []
    else:
        open_tasks = (
            await ctx.session.scalars(select(Task).where(Task.status == TaskStatus.TODO))
        ).all()
        candidates = [t for t in open_tasks if args.title and matches(args.title, t.title)]
    if not candidates:
        raise ToolError("no matching open task")
    if len(candidates) > 1:
        raise ToolError(
            "several tasks match; ask which one", candidates=[describe_task(t) for t in candidates]
        )
    task = candidates[0]
    before = ctx.recorder.before_update(task)
    task.status = TaskStatus.DONE
    task.completed_at = ctx.now
    await ctx.recorder.updated(task, before)
    return {"completed": describe_task(task)}


# --- follow-ups ------------------------------------------------------------------------


def describe_followup(followup: Followup) -> dict[str, Any]:
    data: dict[str, Any] = {
        "followup_id": followup.id,
        "title": followup.title,
        "status": followup.status.value,
        "check_rule": followup.check_rule.value,
    }
    if followup.every_n_days:
        data["every_n_days"] = followup.every_n_days
    if followup.check_on:
        data["check_on"] = followup.check_on.isoformat()
    return data


class AddFollowupArgs(BaseModel):
    title: str = Field(description="what to keep asking about, e.g. 'Hackathon kabulü'")
    check_rule: Literal["daily", "every_n_days", "on_date"] = "daily"
    every_n_days: int | None = Field(None, ge=1)
    check_on: dt.date | None = Field(None, description="for on_date, " + ISO_DATE)
    related_event_id: int | None = None


@tool(
    "add_followup",
    "Keep asking the user about something until it resolves (application results, replies).",
    AddFollowupArgs,
    mutates=True,
)
async def add_followup(args: AddFollowupArgs, ctx: ToolContext) -> ToolResult:
    rule = FollowupCheckRule(args.check_rule)
    if rule is FollowupCheckRule.EVERY_N_DAYS and not args.every_n_days:
        raise ToolError("every_n_days is required for check_rule=every_n_days")
    if rule is FollowupCheckRule.ON_DATE and not args.check_on:
        raise ToolError("check_on is required for check_rule=on_date")
    if args.related_event_id and await ctx.session.get(Event, args.related_event_id) is None:
        raise ToolError(f"no event {args.related_event_id}")
    followup = Followup(
        title=args.title,
        check_rule=rule,
        every_n_days=args.every_n_days,
        check_on=args.check_on,
        related_event_id=args.related_event_id,
        owner_id=ctx.agent_id,  # Mentor's application follow-ups stay Mentor's
    )
    ctx.session.add(followup)
    await ctx.recorder.created(followup)
    return {"created": describe_followup(followup)}


class UpdateFollowupArgs(BaseModel):
    followup_id: int | None = None
    title: str | None = Field(None, description="to find it if the id is not known")
    status: Literal["waiting", "positive", "negative", "done"] | None = None
    notes: str | None = None


@tool(
    "update_followup",
    "Record news on a follow-up (e.g. accepted -> positive) or close it (done).",
    UpdateFollowupArgs,
    mutates=True,
)
async def update_followup(args: UpdateFollowupArgs, ctx: ToolContext) -> ToolResult:
    if args.followup_id is not None:
        found = await ctx.session.get(Followup, args.followup_id)
        candidates = [found] if found else []
    else:
        rows = (await ctx.session.scalars(select(Followup))).all()
        candidates = [f for f in rows if args.title and matches(args.title, f.title)]
    if len(candidates) != 1:
        raise ToolError(
            "follow-up not found or ambiguous",
            candidates=[describe_followup(f) for f in candidates],
        )
    followup = candidates[0]
    before = ctx.recorder.before_update(followup)
    if args.status is not None:
        followup.status = FollowupStatus(args.status)
    if args.notes is not None:
        followup.notes = args.notes
    followup.last_checked_at = ctx.now
    await ctx.recorder.updated(followup, before)
    return {"updated": describe_followup(followup)}
