import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.agent.tools.matching import (
    WEEKDAYS_EN,
    describe_block,
    find_blocks,
    find_or_create_course,
    single_block,
)
from app.core.time_resolver import WEEKDAY_NAMES_TR, week_start
from app.db.models import BlockOverride, RecurringBlock
from app.db.models.enums import ACADEMIC_BLOCK_KINDS, BlockKind, OverrideAction
from app.services.schedule import DayPlan, PlanItem, get_day_plan

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
BlockKindName = Literal["class", "lab", "sport", "work", "other"]
ISO_DATE = "ISO date YYYY-MM-DD (use resolve_date for words like 'yarın')"


def _hhmm(value: dt.datetime | dt.time) -> str:
    return value.strftime("%H:%M")


def item_to_dict(item: PlanItem, day: dt.date) -> dict[str, Any]:
    data: dict[str, Any] = {
        "type": item.source,
        "id": item.source_id,
        "kind": item.kind,
        "title": item.title,
    }
    if item.all_day:
        data["all_day"] = True
    else:
        data["start"] = _hhmm(item.start)
        if item.end is not None:
            data["end"] = _hhmm(item.end)
    if item.start.date() != day:
        data["starts_on"] = item.start.date().isoformat()
    if item.end is not None and item.end.date() != day and not item.all_day:
        data["ends_on"] = item.end.date().isoformat()
    if item.location:
        data["location"] = item.location
    if item.moved_from:
        data["moved_from"] = item.moved_from.strftime("%Y-%m-%d %H:%M")
    if item.note:
        data["note"] = item.note
    return data


def plan_to_dict(plan: DayPlan) -> dict[str, Any]:
    data: dict[str, Any] = {
        "date": plan.day.isoformat(),
        "weekday": WEEKDAY_NAMES_TR[plan.day.weekday()],
        "items": [item_to_dict(item, plan.day) for item in plan.items],
    }
    if plan.cancelled:
        data["cancelled"] = [
            {"block_id": c.block_id, "title": c.title, "start": _hhmm(c.start), "reason": c.reason}
            for c in plan.cancelled
        ]
    if plan.conflicts:
        data["conflicts"] = [[c.first.title, c.second.title] for c in plan.conflicts]
    if plan.holidays:
        data["holidays"] = plan.holidays
    if plan.tasks:
        data["tasks"] = [
            {"id": t.id, "title": t.title, "status": t.status.value} for t in plan.tasks
        ]
    if plan.week_tasks:
        data["week_tasks"] = [
            {"id": t.id, "title": t.title, "status": t.status.value} for t in plan.week_tasks
        ]
    return data


# --- reading ---------------------------------------------------------------------------


class DayArgs(BaseModel):
    date: dt.date = Field(description=ISO_DATE)


@tool(
    "get_day_plan",
    "Everything on one day: weekly blocks (with cancellations/moves applied), events, "
    "tasks, conflicts, holidays.",
    DayArgs,
)
async def get_day_plan_tool(args: DayArgs, ctx: ToolContext) -> ToolResult:
    return plan_to_dict(await get_day_plan(ctx.session, args.date, ctx.tz))


@tool("get_week_plan", "Monday-Sunday overview of the week containing the date.", DayArgs)
async def get_week_plan(args: DayArgs, ctx: ToolContext) -> ToolResult:
    monday = week_start(args.date)
    days = []
    for offset in range(7):
        plan = await get_day_plan(ctx.session, monday + dt.timedelta(days=offset), ctx.tz)
        day = plan_to_dict(plan)
        day.pop("week_tasks", None)
        days.append(day)
    return {"week_start": monday.isoformat(), "days": days}


# --- weekly blocks ---------------------------------------------------------------------


class AddBlockArgs(BaseModel):
    kind: BlockKindName
    title: str = Field(description="e.g. 'Linear Algebra', 'EE211 Lab', 'Spor', 'Medipol'")
    weekdays: list[Weekday] = Field(min_length=1, description="one block per weekday")
    start_time: dt.time = Field(description="HH:MM, 24h")
    end_time: dt.time = Field(description="HH:MM, 24h")
    location: str | None = None
    course_code: str | None = Field(None, description="for class/lab, e.g. 'EE211'")
    course_name: str | None = Field(None, description="for class/lab, e.g. 'Linear Algebra'")
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


@tool(
    "add_recurring_block",
    "Add a weekly repeating block (class, lab, sport, work...) on one or more weekdays. "
    "For class/lab the course is found or created from course_code / course_name.",
    AddBlockArgs,
    mutates=True,
)
async def add_recurring_block(args: AddBlockArgs, ctx: ToolContext) -> ToolResult:
    if args.start_time == args.end_time:
        raise ToolError("start_time and end_time are the same")
    course_id = None
    course_created = False
    kind = BlockKind(args.kind)
    if kind in ACADEMIC_BLOCK_KINDS:
        course, course_created = await find_or_create_course(
            ctx, args.course_code, args.course_name or args.title
        )
        course_id = course.id
    created, existing = [], []
    for weekday_name in dict.fromkeys(args.weekdays):
        weekday = WEEKDAYS_EN.index(weekday_name)
        duplicate = await ctx.session.scalar(
            select(RecurringBlock).where(
                RecurringBlock.weekday == weekday,
                RecurringBlock.start_time == args.start_time,
                RecurringBlock.title == args.title,
            )
        )
        if duplicate is not None:
            existing.append(describe_block(duplicate))
            continue
        block = RecurringBlock(
            kind=kind,
            title=args.title,
            weekday=weekday,
            start_time=args.start_time,
            end_time=args.end_time,
            location=args.location,
            course_id=course_id,
            valid_from=args.valid_from,
            valid_to=args.valid_to,
        )
        ctx.session.add(block)
        await ctx.recorder.created(block)
        created.append(describe_block(block))
    result: ToolResult = {"created": created}
    if existing:
        result["already_existed"] = existing
    if course_created:
        result["course_created"] = True
    return result


class UpdateBlockArgs(BaseModel):
    block: str = Field(description="which block, e.g. 'linear', 'spor'")
    on_weekday: Weekday | None = Field(None, description="to pick one if the name repeats")
    title: str | None = None
    weekday: Weekday | None = Field(None, description="move the weekly block to this day")
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    location: str | None = None
    valid_to: dt.date | None = Field(None, description="last date it happens (stops it)")


@tool(
    "update_recurring_block",
    "Change a weekly block permanently (time, day, place, or end it with valid_to). "
    "For a single date use cancel_block_on / move_block_on instead.",
    UpdateBlockArgs,
    mutates=True,
)
async def update_recurring_block(args: UpdateBlockArgs, ctx: ToolContext) -> ToolResult:
    weekday = WEEKDAYS_EN.index(args.on_weekday) if args.on_weekday else None
    block = single_block(await find_blocks(ctx, args.block, weekday=weekday), args.block, None)
    before = ctx.recorder.before_update(block)
    if args.title is not None:
        block.title = args.title
    if args.weekday is not None:
        block.weekday = WEEKDAYS_EN.index(args.weekday)
    if args.start_time is not None:
        block.start_time = args.start_time
    if args.end_time is not None:
        block.end_time = args.end_time
    if args.location is not None:
        block.location = args.location
    if args.valid_to is not None:
        block.valid_to = args.valid_to
    await ctx.recorder.updated(block, before)
    return {"updated": describe_block(block)}


# --- single-date overrides -------------------------------------------------------------


async def _block_on(ctx: ToolContext, query: str, day: dt.date) -> RecurringBlock:
    plan = await get_day_plan(ctx.session, day, ctx.tz)
    overridden = (
        await ctx.session.scalars(select(BlockOverride.block_id).where(BlockOverride.date == day))
    ).all()
    # Occurrences of that date: shown as usual, already cancelled, or already moved away.
    occurring = {
        item.source_id for item in plan.items if item.source == "block" and item.moved_from is None
    }
    occurring |= {cancelled.block_id for cancelled in plan.cancelled} | set(overridden)
    found = [b for b in await find_blocks(ctx, query) if b.id in occurring]
    if not found:
        on_day = [item.title for item in plan.items if item.source == "block"]
        raise ToolError(
            f"no '{query}' block on {day.isoformat()} ({WEEKDAY_NAMES_TR[day.weekday()]})",
            blocks_that_day=on_day,
        )
    return single_block(found, query, day)


async def _override(ctx: ToolContext, block: RecurringBlock, day: dt.date) -> BlockOverride | None:
    return await ctx.session.scalar(
        select(BlockOverride).where(BlockOverride.block_id == block.id, BlockOverride.date == day)
    )


class CancelArgs(BaseModel):
    date: dt.date = Field(description=ISO_DATE)
    block: str = Field(description="which block, e.g. 'linear', 'spor'")
    reason: str | None = None


@tool(
    "cancel_block_on",
    "Cancel ONE occurrence of a weekly block on a date (the block stays for other weeks).",
    CancelArgs,
    mutates=True,
)
async def cancel_block_on(args: CancelArgs, ctx: ToolContext) -> ToolResult:
    block = await _block_on(ctx, args.block, args.date)
    existing = await _override(ctx, block, args.date)
    if existing is not None and existing.action is OverrideAction.CANCEL:
        return {"already_cancelled": describe_block(block), "date": args.date.isoformat()}
    if existing is not None:  # was moved; now cancelled instead
        before = ctx.recorder.before_update(existing)
        existing.action = OverrideAction.CANCEL
        existing.new_start_at = existing.new_end_at = None
        existing.reason = args.reason
        await ctx.recorder.updated(existing, before)
    else:
        override = BlockOverride(
            block_id=block.id, date=args.date, action=OverrideAction.CANCEL, reason=args.reason
        )
        ctx.session.add(override)
        await ctx.recorder.created(override)
    return {"cancelled": describe_block(block), "date": args.date.isoformat()}


class MoveArgs(BaseModel):
    date: dt.date = Field(description="original date of the occurrence, " + ISO_DATE)
    block: str
    new_start_time: dt.time = Field(description="HH:MM")
    new_end_time: dt.time = Field(description="HH:MM")
    new_date: dt.date | None = Field(None, description="if it moves to another day")
    reason: str | None = None

    @model_validator(mode="after")
    def _times(self) -> "MoveArgs":
        if self.new_start_time == self.new_end_time:
            raise ValueError("new_start_time and new_end_time are the same")
        return self


@tool(
    "move_block_on",
    "Move ONE occurrence of a weekly block to another time and/or day (make-up class).",
    MoveArgs,
    mutates=True,
)
async def move_block_on(args: MoveArgs, ctx: ToolContext) -> ToolResult:
    block = await _block_on(ctx, args.block, args.date)
    target = args.new_date or args.date
    start = ctx.local(target, args.new_start_time)
    end_day = target if args.new_end_time > args.new_start_time else target + dt.timedelta(days=1)
    end = ctx.local(end_day, args.new_end_time)
    existing = await _override(ctx, block, args.date)
    if existing is not None:
        before = ctx.recorder.before_update(existing)
        existing.action = OverrideAction.MOVE
        existing.new_start_at, existing.new_end_at, existing.reason = start, end, args.reason
        await ctx.recorder.updated(existing, before)
    else:
        override = BlockOverride(
            block_id=block.id,
            date=args.date,
            action=OverrideAction.MOVE,
            new_start_at=start,
            new_end_at=end,
            reason=args.reason,
        )
        ctx.session.add(override)
        await ctx.recorder.created(override)
    return {
        "moved": describe_block(block),
        "from": args.date.isoformat(),
        "to": f"{target.isoformat()} {_hhmm(args.new_start_time)}-{_hhmm(args.new_end_time)}",
    }
