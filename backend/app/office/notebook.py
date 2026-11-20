"""Writing into an employee's notebook (employee_notes), from a tool or a shift job."""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.change_log import ChangeRecorder
from app.db.models import EmployeeNote
from app.office.budget import day_start


async def write_note(
    session: AsyncSession,
    employee_id: str,
    content: str,
    now: dt.datetime,
    tz: ZoneInfo,
    *,
    source: str = "agent",
    recorder: ChangeRecorder | None = None,
    once_a_day: bool = False,
) -> EmployeeNote | None:
    """`once_a_day`: skip when the same note was already written today (status notes such
    as "web arama anahtarı bekleniyor"). With a recorder the note joins the message's
    change set (undo)."""
    if once_a_day:
        exists = await session.scalar(
            select(EmployeeNote.id).where(
                EmployeeNote.employee_id == employee_id,
                EmployeeNote.content == content,
                EmployeeNote.created_at >= day_start(now, tz),
            )
        )
        if exists is not None:
            return None
    note = EmployeeNote(employee_id=employee_id, content=content, source=source, created_at=now)
    session.add(note)
    if recorder is not None:
        await recorder.created(note)
    else:
        await session.flush()
    return note


def note_event(note: EmployeeNote) -> dict[str, Any]:
    """What the office stream announces (Office.publish_notes) once the note is committed."""
    return {
        "id": note.id,
        "employee_id": note.employee_id,
        "content": note.content,
        "created_at": note.created_at,
    }
