"""Single-user login: off without a password, cookie for the browser, bearer token for the
desktop app, sessions in the database, wrong passwords rate-limited."""

import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import get_session_factory
from app.config import Settings, get_settings
from app.db.models import AuthSession
from app.db.session import get_session
from app.main import create_app
from app.services import auth as auth_service
from app.services.auth import COOKIE, LoginLimiter, auth_enabled, hash_token


def settings_with(password: str | None, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        upload_dir=tmp_path,
        app_password=SecretStr(password) if password is not None else None,
    )


async def make_client(
    session: AsyncSession, settings: Settings
) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: None
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_service, "limiter", LoginLimiter())
    from app.api import auth as auth_api

    monkeypatch.setattr(auth_api, "limiter", auth_service.limiter)


@pytest.fixture
async def locked(session: AsyncSession, tmp_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    async for http in make_client(session, settings_with("doğru-parola", tmp_path)):
        yield http


def test_password_rules(tmp_path: Path) -> None:
    assert not auth_enabled(settings_with(None, tmp_path))
    assert not auth_enabled(settings_with("", tmp_path))
    assert not auth_enabled(settings_with("   ", tmp_path))
    assert not auth_enabled(settings_with("change-me", tmp_path))  # the old example value
    assert auth_enabled(settings_with("x7!", tmp_path))


async def test_no_password_no_login(session: AsyncSession, tmp_path: Path) -> None:
    async for http in make_client(session, settings_with(None, tmp_path)):
        assert (await http.get("/api/auth/status")).json() == {
            "enabled": False,
            "authenticated": True,
        }
        assert (await http.get("/api/attendance")).status_code == 200


async def test_browser_login_with_a_cookie(
    locked: httpx2.AsyncClient, session: AsyncSession
) -> None:
    assert (await locked.get("/api/attendance")).status_code == 401
    assert (await locked.get("/api/plan/week")).json()["detail"] == {"code": "login_required"}
    assert (await locked.get("/api/health")).status_code == 200  # public
    assert (await locked.get("/api/auth/status")).json() == {
        "enabled": True,
        "authenticated": False,
    }

    wrong = await locked.post("/api/auth/login", json={"password": "yanlış"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == {"code": "wrong_password"}

    ok = await locked.post("/api/auth/login", json={"password": "doğru-parola"})
    assert ok.status_code == 200
    assert "token" not in ok.json()  # the browser only gets the httpOnly cookie
    cookie = ok.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie  # plain http (localhost); https sets it
    assert (await locked.get("/api/attendance")).status_code == 200
    assert (await locked.get("/api/auth/status")).json()["authenticated"] is True

    stored = (await session.scalars(select(AuthSession))).one()
    token = locked.cookies[COOKIE]
    assert stored.token_hash == hash_token(token) != token  # only the hash is stored
    assert stored.client == "web"

    assert (await locked.post("/api/auth/logout")).status_code == 200
    assert await session.scalar(select(func.count()).select_from(AuthSession)) == 0
    locked.cookies.set(COOKIE, token)  # an old cookie is dead after logout
    assert (await locked.get("/api/attendance")).status_code == 401


async def test_desktop_login_with_a_bearer_token(locked: httpx2.AsyncClient) -> None:
    login = await locked.post(
        "/api/auth/login",
        json={"password": "doğru-parola", "client": "desktop", "device": "GORKEM-PC"},
    )
    token = login.json()["token"]
    assert "set-cookie" not in login.headers
    headers = {"Authorization": f"Bearer {token}"}
    assert (await locked.get("/api/attendance", headers=headers)).status_code == 200
    screen = {"device": "GORKEM-PC", "days": [{"date": "2026-11-20", "apps": []}]}
    assert (await locked.post("/api/screen-time", json=screen, headers=headers)).status_code == 200
    bad = {"Authorization": "Bearer nope"}
    assert (await locked.get("/api/attendance", headers=bad)).status_code == 401


async def test_sessions_expire_after_idle_days(
    locked: httpx2.AsyncClient, session: AsyncSession
) -> None:
    await locked.post("/api/auth/login", json={"password": "doğru-parola"})
    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    await session.execute(update(AuthSession).values(expires_at=past))
    await session.commit()
    assert (await locked.get("/api/attendance")).status_code == 401


async def test_wrong_passwords_are_rate_limited(locked: httpx2.AsyncClient) -> None:
    for _ in range(5):
        assert (await locked.post("/api/auth/login", json={"password": "x"})).status_code == 401
    blocked = await locked.post("/api/auth/login", json={"password": "doğru-parola"})
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "too_many_attempts"
    assert int(blocked.headers["retry-after"]) > 0


def test_limiter_window() -> None:
    limiter = LoginLimiter(attempts=2, window=60)
    limiter.failed("ip", now=0)
    limiter.failed("ip", now=10)
    assert limiter.retry_after("ip", now=20) == 41
    assert limiter.retry_after("ip", now=61) == 0  # the first one aged out
    limiter.succeeded("ip")
    assert limiter.retry_after("ip", now=11) == 0


async def test_device_keys_last_until_revoked(
    locked: httpx2.AsyncClient, session: AsyncSession
) -> None:
    """Desktop app / Siri shortcut: a key made from a logged-in page, sent as a bearer."""
    from sqlalchemy import select

    from app.db.models import DeviceKey

    login = await locked.post("/api/auth/login", json={"password": "doğru-parola"})
    assert login.status_code == 200  # the browser cookie stays on the client
    made = (await locked.post("/api/devices", json={"name": "Masaüstü"})).json()
    key = made["key"]
    assert key.startswith("yvk_")
    assert made["prefix"] == key[:8]
    locked.cookies.clear()  # the device has no browser login

    device = {"Authorization": f"Bearer {key}"}
    assert (await locked.get("/api/team", headers=device)).status_code == 200
    assert (await locked.post("/api/chat", json={}, headers=device)).status_code == 422  # past auth
    # only the hash is stored, and the list never shows the key
    row = await session.scalar(select(DeviceKey))
    assert row is not None
    assert row.key_hash == hash_token(key)
    assert row.last_used_at is not None
    listed = (await locked.get("/api/devices", headers=device)).json()["devices"]
    assert listed[0]["name"] == "Masaüstü"
    assert "key" not in listed[0]
    # a key never expires like a session does, but it can be revoked
    assert (await locked.delete(f"/api/devices/{made['id']}", headers=device)).status_code == 200
    gone = await locked.get("/api/team", headers=device)
    assert gone.status_code == 401
    assert gone.json()["detail"]["code"] == "device_key_invalid"
    wrong = {"Authorization": "Bearer yvk_not-a-key"}
    assert (await locked.get("/api/team", headers=wrong)).status_code == 401


async def test_device_keys_need_a_login_to_be_made(locked: httpx2.AsyncClient) -> None:
    assert (await locked.post("/api/devices", json={"name": "x"})).status_code == 401
