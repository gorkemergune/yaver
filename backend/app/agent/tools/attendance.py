import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agent.context import ToolContext
from app.agent.tools import ToolResult, tool
from app.agent.tools.matching import require_course
from app.agent.tools.schedule import ISO_DATE
from app.db.models import Attendance, Course, RecurringBlock
from app.db.models.enums import AttendanceStatus
from app.services.schedule import get_day_plan


async def _summary(ctx: ToolContext, course: Course) -> dict[str, Any]:
    absences = await ctx.session.scalar(
        select(func.count()).where(
            Attendance.course_id == course.id, Attendance.status == AttendanceStatus.ABSENT
        )
    )
    data: dict[str, Any] = {"course": course.code, "name": course.name, "absences": absences or 0}
    if course.absence_limit is not None:
        data["limit"] = course.absence_limit
        data["remaining"] = course.absence_limit - (absences or 0)
    else:
        data["limit"] = None  # unknown: ask the user once and store it
    return data


class LogAttendanceArgs(BaseModel):
    course: str = Field(description="course code or name, e.g. 'EE211', 'linear'")
    date: dt.date = Field(description="resolve with direction='past', " + ISO_DATE)
    status: Literal["absent", "present", "excused"] = "absent"


@tool(
    "log_attendance",
    "Record that the user missed / attended a class on a date. Returns the absence count "
    "and remaining allowance (limit null = not known yet: ask the user for it).",
    LogAttendanceArgs,
    mutates=True,
)
async def log_attendance(args: LogAttendanceArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    existing = await ctx.session.scalar(
        select(Attendance).where(Attendance.course_id == course.id, Attendance.date == args.date)
    )
    status = AttendanceStatus(args.status)
    if existing is not None:
        before = ctx.recorder.before_update(existing)
        existing.status = status
        await ctx.recorder.updated(existing, before)
    else:
        record = Attendance(course_id=course.id, date=args.date, status=status)
        ctx.session.add(record)
        await ctx.recorder.created(record)

    result: ToolResult = {
        "logged": {"course": course.code, "date": args.date.isoformat(), "status": args.status},
        "summary": await _summary(ctx, course),
    }
    plan = await get_day_plan(ctx.session, args.date, ctx.tz)
    block_ids = {item.source_id for item in plan.items if item.source == "block"}
    has_session = await ctx.session.scalar(
        select(func.count()).where(
            RecurringBlock.course_id == course.id, RecurringBlock.id.in_(block_ids)
        )
    )
    if not has_session:
        result["warning"] = f"{course.code} has no session in the schedule on that day"
    return result


class SetLimitArgs(BaseModel):
    course: str
    absence_limit: int = Field(ge=0)


@tool(
    "set_absence_limit",
    "Store how many absences a course allows.",
    SetLimitArgs,
    mutates=True,
)
async def set_absence_limit(args: SetLimitArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    before = ctx.recorder.before_update(course)
    course.absence_limit = args.absence_limit
    await ctx.recorder.updated(course, before)
    return {"summary": await _summary(ctx, course)}


class SummaryArgs(BaseModel):
    course: str | None = Field(None, description="omit for all courses")


@tool("get_attendance_summary", "Absences and remaining allowance per course.", SummaryArgs)
async def get_attendance_summary(args: SummaryArgs, ctx: ToolContext) -> ToolResult:
    if args.course:
        return {"courses": [await _summary(ctx, await require_course(ctx, args.course))]}
    courses = (await ctx.session.scalars(select(Course).order_by(Course.code))).all()
    return {"courses": [await _summary(ctx, course) for course in courses]}
