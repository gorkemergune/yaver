"""Web Push (VAPID): the morning briefing, the evening check-in and follow-ups also arrive
as notifications. Keys come from .env (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY /
VAPID_SUBJECT); without them nothing is sent and the web app hides the switch."""

import asyncio
import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import PushSubscription

logger = logging.getLogger(__name__)

TTL_SECONDS = 12 * 3600  # a briefing nobody saw for 12 hours is stale
MAX_FAILURES = 5  # in a row (push service down / odd errors): the subscription is dropped
GONE = frozenset({404, 410})  # the browser unsubscribed: drop it right away
BODY_CHARS = 180


@dataclass(frozen=True, slots=True)
class Notification:
    title: str
    body: str
    url: str = "/#/chat"
    tag: str | None = None  # same tag replaces the previous notification

    def payload(self) -> str:
        return json.dumps(
            {"title": self.title, "body": self.body, "url": self.url, "tag": self.tag},
            ensure_ascii=False,
        )


def push_enabled(settings: Settings) -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key and settings.vapid_subject)


def preview(text: str, limit: int = BODY_CHARS) -> str:
    """Chat markdown -> one short plain-text body ("**Friday** · ..." -> "Friday · ...")."""
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    lines = [line.strip().lstrip("-• ").strip() for line in plain.splitlines() if line.strip()]
    joined = " · ".join(lines)
    return joined if len(joined) <= limit else joined[: limit - 1].rstrip() + "…"


def _webpush(subscription: dict[str, Any], data: str, settings: Settings) -> int:
    """Blocking send (pywebpush uses requests); returns the push service's HTTP status."""
    from pywebpush import WebPushException, webpush

    assert settings.vapid_private_key is not None
    try:
        response = webpush(
            subscription_info=subscription,
            data=data,
            vapid_private_key=settings.vapid_private_key.get_secret_value(),
            vapid_claims={"sub": str(settings.vapid_subject)},
            ttl=TTL_SECONDS,
            timeout=10,
        )
    except WebPushException as exc:
        return exc.response.status_code if exc.response is not None else 0
    return int(getattr(response, "status_code", 201))


# Replaced in tests (no network).
send_one = _webpush


async def send_push(
    session: AsyncSession, settings: Settings, notification: Notification, now: dt.datetime
) -> dict[str, int]:
    """To every subscription; gone ones are deleted. Never raises for a failed send."""
    result = {"sent": 0, "removed": 0, "failed": 0}
    if not push_enabled(settings):
        return result
    rows = (await session.scalars(select(PushSubscription))).all()
    data = notification.payload()
    for row in rows:
        info = {"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}}
        try:
            status = await asyncio.to_thread(send_one, info, data, settings)
        except Exception:  # network trouble, bad key: logged, the job goes on
            logger.exception("Web Push to %s failed", row.endpoint[:60])
            status = 0
        if 200 <= status < 300:
            row.last_sent_at = now
            row.failures = 0
            result["sent"] += 1
        elif status in GONE or row.failures + 1 >= MAX_FAILURES:
            await session.delete(row)
            result["removed"] += 1
        else:
            row.failures += 1
            result["failed"] += 1
    await session.commit()
    if rows:
        logger.info("Web Push %r: %s", notification.title, result)
    return result
