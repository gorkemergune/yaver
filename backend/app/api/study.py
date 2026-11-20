"""Study sheets for the web app: list, read, download as Markdown."""

import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Course
from app.db.models.study import StudySheet
from app.db.session import get_session

router = APIRouter(prefix="/study-sheets", tags=["study"])


def _view(sheet: StudySheet, course: str | None, full: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": sheet.id,
        "title": sheet.title,
        "course": course,
        "week": sheet.week_no,
        "created_at": sheet.created_at,
        "sources": len(sheet.sources),
    }
    if full:
        data["content_md"] = sheet.content_md
        data["model"] = sheet.model
        data["sources"] = sheet.sources
    return data


@router.get("")
async def list_sheets(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(StudySheet, Course.code)
            .outerjoin(Course, Course.id == StudySheet.course_id)
            .order_by(StudySheet.id.desc())
        )
    ).all()
    return {"sheets": [_view(sheet, code) for sheet, code in rows]}


async def _get(session: AsyncSession, sheet_id: int) -> tuple[StudySheet, str | None]:
    row = (
        await session.execute(
            select(StudySheet, Course.code)
            .outerjoin(Course, Course.id == StudySheet.course_id)
            .where(StudySheet.id == sheet_id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, detail={"code": "not_found"})
    return row[0], row[1]


@router.get("/{sheet_id}")
async def get_sheet(sheet_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    sheet, code = await _get(session, sheet_id)
    return _view(sheet, code, full=True)


def file_name(title: str) -> str:
    """'EE211 · 7. hafta: Thevenin' -> 'EE211-7-hafta-Thevenin' (ASCII-safe header + UTF-8)."""
    slug = re.sub(r"[^\w]+", "-", title, flags=re.UNICODE).strip("-")
    return slug[:80] or "calisma-kagidi"


@router.get("/{sheet_id}/download.md")
async def download_markdown(
    sheet_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    sheet, _ = await _get(session, sheet_id)
    name = file_name(sheet.title)
    ascii_name = name.encode("ascii", "ignore").decode() or "calisma-kagidi"
    return Response(
        content=f"# {sheet.title}\n\n{sheet.content_md}",
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}.md\"; filename*=UTF-8''{quote(name)}.md"
            )
        },
    )
