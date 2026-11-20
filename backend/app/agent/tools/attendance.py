"""Attendance tools (the classes yaver). Everything is in class hours, per block."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import HHMM_PATTERN, ToolError, ToolResult, tool
from app.agent.tools.matching import require_course
from app.agent.tools.schedule import ISO_DATE
from app.db.models import Attendance, AttendanceBaseline, Course, RecurringBlock
from app.db.models.enums import AttendanceStatus
from app.services.attendance import (
    course_summary,
    day_label,
    nearest_class_days,
    sessions_on,
)


class LogAttendanceArgs(BaseModel):
    course: str = Field(description="course code or name, e.g. 'EE211', 'linear'")
    dates: list[dt.date] = Field(
        min_length=1,
        max_length=31,
        description="every date the user named (resolve_date, direction='past'), " + ISO_DATE,
    )
    status: Literal["absent", "present", "excused"] = "absent"
    time: str | None = Field(
        None,
        pattern=HHMM_PATTERN,
        description="start HH:MM, only if the user named one class of that day; else all",
    )


@tool(
    "log_attendance",
    "Record missed (or attended) classes. Each date counts every class block of the course "
    "that day, in class hours (09:00-11:00 = 2). Already recorded sessions are not counted "
    "twice. Dates in the future or without a class come back under not_logged with the "
    "nearest past class day to suggest.",
    LogAttendanceArgs,
    mutates=True,
)
async def log_attendance(args: LogAttendanceArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    status = AttendanceStatus(args.status)
    today = ctx.today
    logged: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for day in sorted(set(args.dates)):
        sessions = [] if day > today else await sessions_on(ctx.session, course, day, ctx.tz)
        if args.time:
            sessions = [s for s in sessions if f"{s.start:%H:%M}" == args.time]
        if not sessions:
            reason = "in the future" if day > today else f"no {course.code} class that day"
            suggestions = await nearest_class_days(ctx.session, course, day, today, ctx.tz)
            problems.append(
                {
                    "date": day_label(day),
                    "problem": reason,
                    "suggest": [day_label(d) for d in suggestions],
                }
            )
            continue
        for item in sessions:
            entry = {"date": day_label(day), "time": item.time_range, "hours": item.hours}
            existing = await ctx.session.scalar(
                select(Attendance).where(
                    Attendance.course_id == course.id,
                    Attendance.date == day,
                    Attendance.recurring_block_id == item.block_id,
                )
            )
            if existing is not None and existing.status is status:
                already.append(entry)
                continue
            if existing is not None:
                before = ctx.recorder.before_update(existing)
                existing.status = status
                existing.hours = item.hours
                await ctx.recorder.updated(existing, before)
            else:
                record = Attendance(
                    course_id=course.id,
                    date=day,
                    recurring_block_id=item.block_id,
                    hours=item.hours,
                    status=status,
                )
                ctx.session.add(record)
                await ctx.recorder.created(record)
            logged.append(entry)

    result: ToolResult = {
        "course": course.code,
        "status": args.status,
        "logged": logged,
        "hours_logged": sum(e["hours"] for e in logged),
        "summary": await course_summary(ctx.session, course),
    }
    if already:
        result["already_recorded"] = already  # not counted again
    if problems:
        result["not_logged"] = problems
    return result


class ListAttendanceArgs(BaseModel):
    course: str | None = Field(None, description="omit for all courses")
    from_date: dt.date | None = Field(None, description=ISO_DATE)
    to_date: dt.date | None = Field(None, description=ISO_DATE)


@tool(
    "list_attendance",
    "Recorded sessions (id, date, class time, hours, status) and the baseline from before "
    "Yaver, with totals per course.",
    ListAttendanceArgs,
)
async def list_attendance(args: ListAttendanceArgs, ctx: ToolContext) -> ToolResult:
    query = (
        select(Attendance, Course, RecurringBlock)
        .join(Course, Course.id == Attendance.course_id)
        .outerjoin(RecurringBlock, RecurringBlock.id == Attendance.recurring_block_id)
        .order_by(Course.code, Attendance.date, RecurringBlock.start_time)
    )
    courses: list[Course]
    if args.course:
        course = await require_course(ctx, args.course)
        query = query.where(Attendance.course_id == course.id)
        courses = [course]
    else:
        courses = list((await ctx.session.scalars(select(Course).order_by(Course.code))).all())
    if args.from_date:
        query = query.where(Attendance.date >= args.from_date)
    if args.to_date:
        query = query.where(Attendance.date <= args.to_date)
    rows = []
    for record, course_row, block in (await ctx.session.execute(query)).all():
        rows.append(
            {
                "id": record.id,
                "course": course_row.code,
                "date": day_label(record.date),
                "time": f"{block.start_time:%H:%M}-{block.end_time:%H:%M}" if block else None,
                "hours": record.hours,
                "status": record.status.value,
            }
        )
    summaries = [await course_summary(ctx.session, c) for c in courses]
    if not args.course:  # all courses: only those with absences
        summaries = [s for s in summaries if s["absent_hours"]]
    return {"records": rows, "totals": summaries}


class DeleteAttendanceArgs(BaseModel):
    attendance_id: int = Field(description="id from list_attendance")


@tool(
    "delete_attendance",
    "Delete one recorded session (wrong date / course). Find the id with list_attendance.",
    DeleteAttendanceArgs,
    mutates=True,
)
async def delete_attendance(args: DeleteAttendanceArgs, ctx: ToolContext) -> ToolResult:
    record = await ctx.session.get(Attendance, args.attendance_id)
    if record is None:
        raise ToolError(f"no attendance record {args.attendance_id}; see list_attendance")
    course = await ctx.session.get(Course, record.course_id)
    assert course is not None
    deleted = {"id": record.id, "date": day_label(record.date), "hours": record.hours}
    await ctx.recorder.deleted(record)  # deletes and logs it for undo
    return {"deleted": deleted, "summary": await course_summary(ctx.session, course)}


class BaselineArgs(BaseModel):
    course: str
    hours: int = Field(ge=0, description="absence hours before Yaver kept track")
    note: str | None = None


@tool(
    "set_attendance_baseline",
    "Store absence hours from before Yaver for a course (replaces an earlier baseline; 0 "
    "clears it). Shown as its own line in summaries.",
    BaselineArgs,
    mutates=True,
)
async def set_attendance_baseline(args: BaselineArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    baseline = await ctx.session.scalar(
        select(AttendanceBaseline).where(AttendanceBaseline.course_id == course.id)
    )
    if baseline is None:
        baseline = AttendanceBaseline(course_id=course.id, hours=args.hours, note=args.note)
        ctx.session.add(baseline)
        await ctx.recorder.created(baseline)
    else:
        before = ctx.recorder.before_update(baseline)
        baseline.hours = args.hours
        baseline.note = args.note
        await ctx.recorder.updated(baseline, before)
    return {"summary": await course_summary(ctx.session, course)}


class SetLimitArgs(BaseModel):
    course: str
    hours: int = Field(ge=0, description="allowed absence, in class hours")


@tool(
    "set_absence_limit",
    "Store how many class hours of absence a course allows.",
    SetLimitArgs,
    mutates=True,
)
async def set_absence_limit(args: SetLimitArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    before = ctx.recorder.before_update(course)
    course.absence_limit = args.hours
    await ctx.recorder.updated(course, before)
    return {"summary": await course_summary(ctx.session, course)}


class SummaryArgs(BaseModel):
    course: str | None = Field(None, description="omit for all courses")


@tool(
    "get_attendance_summary",
    "Absence hours (recorded + before Yaver), limit and remaining hours per course.",
    SummaryArgs,
)
async def get_attendance_summary(args: SummaryArgs, ctx: ToolContext) -> ToolResult:
    if args.course:
        return {
            "courses": [await course_summary(ctx.session, await require_course(ctx, args.course))]
        }
    courses = (await ctx.session.scalars(select(Course).order_by(Course.code))).all()
    return {"courses": [await course_summary(ctx.session, course) for course in courses]}
