import datetime as dt
from typing import Literal

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
from app.services.plan_view import hhmm as _hhmm
from app.services.plan_view import plan_to_dict
from app.services.schedule import get_day_plan

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
BlockKindName = Literal["class", "lab", "sport", "work", "other"]
ISO_DATE = "YYYY-MM-DD"  # the prompts explain resolve_date once; keep schemas small


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
    title: str
    weekdays: list[Weekday] = Field(min_length=1)
    start_time: dt.time
    end_time: dt.time
    location: str | None = None
    course: str | None = Field(None, description="class/lab: code or name, e.g. EE211")


@tool(
    "add_recurring_block",
    "Add a weekly block (class, lab, sport, work...) on one or more weekdays.",
    AddBlockArgs,
    mutates=True,
)
async def add_recurring_block(args: AddBlockArgs, ctx: ToolContext) -> ToolResult:
    return await create_weekly_blocks(ctx, args)


async def create_weekly_blocks(ctx: ToolContext, args: AddBlockArgs) -> ToolResult:
    """Shared by add_recurring_block and apply_proposal (confirmed schedule proposals)."""
    if args.start_time == args.end_time:
        raise ToolError(f"{args.title}: start_time and end_time are the same")
    course_id = None
    course_created = False
    kind = BlockKind(args.kind)
    if kind in ACADEMIC_BLOCK_KINDS:
        course, course_created = await find_or_create_course(ctx, args.course, args.title)
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
