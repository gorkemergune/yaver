"""Web Push: subscriptions over HTTP, sending (fake push service), jobs notify."""

import datetime as dt
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import get_session_factory
from app.config import Settings, get_settings
from app.db.models import PushSubscription
from app.db.session import get_session
from app.main import create_app
from app.services import push as push_service
from app.services.push import Notification, preview, push_enabled, send_push
from tests.db.test_jobs import at, job, week  # noqa: F401 - fixtures

NOW = dt.datetime(2026, 11, 23, 5, 0, tzinfo=dt.UTC)


def vapid(database_url: str = "", **extra: Any) -> Settings:
    values: dict[str, Any] = {
        "app_password": None,
        "app_user_name": "Görkem",
        "vapid_public_key": "BPublicKeyForTests",
        "vapid_private_key": SecretStr("private-key-for-tests"),
        "vapid_subject": "mailto:test@example.com",
        **extra,
    }
    if database_url:
        values["database_url"] = database_url
    return Settings(_env_file=None, **values)


class FakePushService:
    """Answers per endpoint (default 201) and records what was sent."""

    def __init__(self, answers: dict[str, int] | None = None) -> None:
        self.answers = answers or {}
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, info: dict[str, Any], data: str, settings: Settings) -> int:
        self.sent.append((info["endpoint"], json.loads(data)))
        return self.answers.get(info["endpoint"], 201)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakePushService:
    fake = FakePushService()
    monkeypatch.setattr(push_service, "send_one", fake)
    return fake


@pytest.fixture
async def http(session: AsyncSession, tmp_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: vapid(upload_dir=tmp_path)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: None
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def sub(n: int) -> dict[str, Any]:
    return {
        "endpoint": f"https://push.example.com/send/{n}",
        "keys": {"p256dh": f"key-{n}", "auth": f"auth-{n}"},
    }


def test_preview_and_switch() -> None:
    text = (
        "Günaydın, Görkem! Bugün 23 Kasım Pazartesi.\n"
        "- **Friday** · Dersler: 09:00-11:00 Linear Algebra (B204)\n"
        "- **Görevler**: Rapor yaz"
    )
    assert preview(text) == (
        "Günaydın, Görkem! Bugün 23 Kasım Pazartesi. · Friday · Dersler: 09:00-11:00 "
        "Linear Algebra (B204) · Görevler: Rapor yaz"
    )
    assert preview("a" * 300).endswith("…")
    assert len(preview("a" * 300)) == 180
    assert push_enabled(vapid())
    assert not push_enabled(Settings(_env_file=None, vapid_public_key=None))


async def test_subscribe_test_and_unsubscribe(
    http: httpx2.AsyncClient, session: AsyncSession, service: FakePushService
) -> None:
    key = (await http.get("/api/push/key")).json()
    assert key == {"enabled": True, "public_key": "BPublicKeyForTests", "subscriptions": 0}
    for _ in range(2):  # the same browser again: one row, keys refreshed
        assert (await http.post("/api/push/subscribe", json=sub(1))).json() == {"subscribed": True}
    assert (await http.post("/api/push/subscribe", json=sub(2))).status_code == 200
    assert (await http.get("/api/push/key")).json()["subscriptions"] == 2

    result = (await http.post("/api/push/test")).json()
    assert result == {"sent": 2, "removed": 0, "failed": 0}
    assert service.sent[0][1]["title"] == "Yaver"

    await http.post("/api/push/unsubscribe", json={"endpoint": sub(1)["endpoint"]})
    rows = (await session.scalars(select(PushSubscription.endpoint))).all()
    assert rows == [sub(2)["endpoint"]]
    bad = {"endpoint": "http://insecure.example.com", "keys": {"p256dh": "a", "auth": "b"}}
    assert (await http.post("/api/push/subscribe", json=bad)).status_code == 422


async def test_gone_and_failing_subscriptions(
    session: AsyncSession, service: FakePushService
) -> None:
    for n in (1, 2, 3):
        session.add(PushSubscription(endpoint=sub(n)["endpoint"], p256dh="k", auth="a"))
    await session.commit()
    service.answers = {sub(2)["endpoint"]: 410, sub(3)["endpoint"]: 500}
    note = Notification("Yaver", "deneme")
    assert await send_push(session, vapid(), note, NOW) == {"sent": 1, "removed": 1, "failed": 1}
    for _ in range(4):  # still failing: dropped after 5 in a row
        await send_push(session, vapid(), note, NOW)
    left = (await session.scalars(select(PushSubscription.endpoint))).all()
    assert left == [sub(1)["endpoint"]]
    first = await session.scalar(select(PushSubscription))
    assert first is not None
    assert first.last_sent_at == NOW


async def test_no_keys_no_push(session: AsyncSession, service: FakePushService) -> None:
    session.add(PushSubscription(endpoint=sub(1)["endpoint"], p256dh="k", auth="a"))
    await session.commit()
    no_keys = Settings(_env_file=None, vapid_public_key=None, vapid_private_key=None)
    assert await send_push(session, no_keys, Notification("a", "b"), NOW) == {
        "sent": 0,
        "removed": 0,
        "failed": 0,
    }
    assert service.sent == []


async def test_jobs_send_a_notification(
    week: AsyncSession,  # noqa: F811
    database_url: str,
    service: FakePushService,
) -> None:
    week.add(PushSubscription(endpoint=sub(1)["endpoint"], p256dh="k", auth="a"))
    await week.commit()
    settings = vapid(database_url)
    briefing = await job(week, settings, "briefing", at(23, 8))
    checkin = await job(week, settings, "checkin", at(23, 21))
    assert briefing is not None
    assert checkin is not None
    titles = [payload["title"] for _, payload in service.sent]
    assert titles == ["Günaydın ☀️", "Akşam check-in 🌙"]
    first = service.sent[0][1]
    assert first["body"].startswith("Günaydın, Görkem! Bugün 23 Kasım Pazartesi.")
    assert "**" not in first["body"]
    assert first["url"] == "/#/chat"
    assert first["tag"] == "briefing"


async def test_a_broken_push_does_not_break_the_job(
    week: AsyncSession,  # noqa: F811
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_: Any) -> int:
        raise RuntimeError("push service down")

    monkeypatch.setattr(push_service, "send_one", boom)
    week.add(PushSubscription(endpoint=sub(1)["endpoint"], p256dh="k", auth="a"))
    await week.commit()
    assert await job(week, vapid(database_url), "checkin", at(23, 21)) is not None
