"""Calendar subscription: GET /api/calendar.ics?token=... (no login: the phone's calendar
cannot log in; the long random token is the key) and, behind the login, the URL itself."""

import datetime as dt
import hmac
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models.secrets import AppSecret
from app.db.session import get_session
from app.services.calendar_feed import feed_items, render

TOKEN_NAME = "calendar_token"

feed_router = APIRouter(tags=["calendar"])  # public, token-checked
router = APIRouter(prefix="/calendar", tags=["calendar"])  # behind the login


async def calendar_token(session: AsyncSession, *, rotate: bool = False) -> str:
    row = await session.get(AppSecret, TOKEN_NAME)
    if row is None or rotate:
        value = secrets.token_urlsafe(24)
        if row is None:
            session.add(AppSecret(name=TOKEN_NAME, value=value))
        else:
            row.value = value
        await session.commit()
        return value
    return row.value


@feed_router.get("/calendar.ics")
async def calendar_feed(
    token: str = Query(min_length=1, max_length=200),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    row = await session.get(AppSecret, TOKEN_NAME)
    if row is None or not hmac.compare_digest(token.encode(), row.value.encode()):
        raise HTTPException(404)  # no hint whether a feed exists
    now = dt.datetime.now(dt.UTC)
    items = await feed_items(session, now.astimezone(settings.tz).date(), settings.tz)
    name = f"{settings.app_name} · {settings.app_user_name}".strip(" ·")
    return Response(
        content=render(items, now, name),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="yaver.ics"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/subscription")
async def subscription(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """The path with the token; the web app puts its own host in front (webcal://...)."""
    return {"path": f"/api/calendar.ics?token={await calendar_token(session)}"}


@router.post("/subscription/rotate")
async def rotate(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """A new secret URL; the old one stops working (shared it by mistake)."""
    return {"path": f"/api/calendar.ics?token={await calendar_token(session, rotate=True)}"}
