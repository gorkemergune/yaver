"""Web Push subscriptions from the web app (status page → "Bildirimleri aç")."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import PushSubscription
from app.db.session import get_session
from app.services.push import Notification, push_enabled, send_push

router = APIRouter(prefix="/push", tags=["push"])


class Keys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscriptionIn(BaseModel):
    """`PushSubscription.toJSON()` from the browser."""

    endpoint: str = Field(pattern=r"^https://", max_length=2000)
    keys: Keys


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=2000)


@router.get("/key")
async def public_key(
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    count = len((await session.scalars(select(PushSubscription.id))).all())
    return {
        "enabled": push_enabled(settings),
        "public_key": settings.vapid_public_key if push_enabled(settings) else None,
        "subscriptions": count,
    }


@router.post("/subscribe")
async def subscribe(
    body: SubscriptionIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not push_enabled(settings):
        raise HTTPException(503, detail={"code": "push_not_configured"})
    row = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if row is None:
        row = PushSubscription(endpoint=body.endpoint, p256dh="", auth="")
        session.add(row)
    row.p256dh = body.keys.p256dh
    row.auth = body.keys.auth
    row.user_agent = (request.headers.get("user-agent") or "")[:300] or None
    row.failures = 0
    await session.commit()
    return {"subscribed": True}


@router.post("/unsubscribe")
async def unsubscribe(
    body: EndpointIn, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await session.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    await session.commit()
    return {"subscribed": False}


@router.post("/test")
async def send_test_push(
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)
) -> dict[str, int]:
    """A notification to every subscribed device ("Deneme bildirimi gönder")."""
    if not push_enabled(settings):
        raise HTTPException(503, detail={"code": "push_not_configured"})
    notification = Notification(
        title="Yaver",
        body="Bildirimler çalışıyor. Brifing, check-in ve takipler buraya da gelecek.",
        tag="test",
    )
    return await send_push(session, settings, notification, dt.datetime.now(dt.UTC))
