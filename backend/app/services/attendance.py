"""Absence counts per course, shared by agent tools and the HTTP API."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attendance, Course
from app.db.models.enums import AttendanceStatus


async def course_summary(session: AsyncSession, course: Course) -> dict[str, Any]:
    absences = await session.scalar(
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


async def all_course_summaries(session: AsyncSession) -> list[dict[str, Any]]:
    courses = (await session.scalars(select(Course).order_by(Course.code))).all()
    return [await course_summary(session, course) for course in courses]
