"""Attendance in class hours, shared by agent tools and the HTTP API.

A missed day is recorded per class block of that day (09:00-11:00 = 2 hours); limits are
hours too. Absences from before Yaver are one baseline line per course.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_resolver import WEEKDAY_NAMES_TR
from app.db.models import Attendance, AttendanceBaseline, Course, RecurringBlock
from app.db.models.enums import AttendanceStatus
from app.services.schedule import get_day_plan

# How far around a date to look for the nearest class day of a course.
SUGGESTION_WINDOW_DAYS = 21


def class_hours(start: dt.datetime | dt.time, end: dt.datetime | dt.time) -> int:
    """Whole class hours of a session: 09:00-11:00 = 2, 13:00-13:50 = 1."""
    if isinstance(start, dt.datetime) and isinstance(end, dt.datetime):
        minutes = (end - start).total_seconds() / 60
    else:
        minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        if minutes <= 0:
            minutes += 24 * 60
    return max(1, round(minutes / 60))


@dataclass(frozen=True, slots=True)
class Session:
    """One class block of a course on a date (after cancellations / moves)."""

    block_id: int
    title: str
    start: dt.datetime
    end: dt.datetime

    @property
    def hours(self) -> int:
        return class_hours(self.start, self.end)

    @property
    def time_range(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


async def sessions_on(
    session: AsyncSession, course: Course, day: dt.date, tz: ZoneInfo
) -> list[Session]:
    plan = await get_day_plan(session, day, tz)
    return [
        Session(item.source_id, item.title, item.start, item.end)
        for item in plan.items
        if item.source == "block"
        and item.course_id == course.id
        and item.end is not None
        and item.start.date() == day  # a block from the previous evening is that day's
    ]


async def nearest_class_days(
    session: AsyncSession, course: Course, around: dt.date, today: dt.date, tz: ZoneInfo
) -> list[dt.date]:
    """The course's class day(s) closest to `around` that are not in the future (two when
    one is as close before as after). Holidays and cancellations are respected."""
    weekdays = set(
        (
            await session.scalars(
                select(RecurringBlock.weekday).where(RecurringBlock.course_id == course.id)
            )
        ).all()
    )
    if not weekdays:
        return []
    candidates = [
        around + dt.timedelta(days=offset)
        for offset in range(-SUGGESTION_WINDOW_DAYS, SUGGESTION_WINDOW_DAYS + 1)
        if offset != 0
    ]
    candidates = [d for d in candidates if d <= today and d.weekday() in weekdays]
    candidates.sort(key=lambda d: (abs((d - around).days), d))
    found: list[dt.date] = []
    for day in candidates:
        if found and abs((day - around).days) > abs((found[0] - around).days):
            break
        if await sessions_on(session, course, day, tz):
            found.append(day)
    return found


def day_label(day: dt.date) -> str:
    return f"{day.isoformat()} {WEEKDAY_NAMES_TR[day.weekday()]}"


async def course_summary(session: AsyncSession, course: Course) -> dict[str, Any]:
    recorded = await session.scalar(
        select(func.coalesce(func.sum(Attendance.hours), 0)).where(
            Attendance.course_id == course.id, Attendance.status == AttendanceStatus.ABSENT
        )
    )
    baseline = await session.scalar(
        select(AttendanceBaseline).where(AttendanceBaseline.course_id == course.id)
    )
    total = int(recorded or 0) + (baseline.hours if baseline else 0)
    data: dict[str, Any] = {
        "course": course.code,
        "name": course.name,
        "absent_hours": total,
        "recorded_hours": int(recorded or 0),
    }
    if baseline is not None:
        data["baseline"] = {"hours": baseline.hours, "note": baseline.note}
    if course.absence_limit is not None:
        data["limit_hours"] = course.absence_limit
        data["remaining_hours"] = course.absence_limit - total
    else:
        data["limit_hours"] = None  # unknown: ask the user once and store it
    return data


async def all_course_summaries(session: AsyncSession) -> list[dict[str, Any]]:
    courses = (await session.scalars(select(Course).order_by(Course.code))).all()
    return [await course_summary(session, course) for course in courses]
