"""Single-user password login: server-side sessions, an httpOnly cookie for the browser and
a bearer token for the desktop app. `APP_PASSWORD` empty (or the example placeholder) =
auth off, everything open as before."""

import datetime as dt
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AuthSession, DeviceKey

COOKIE = "yaver_session"
# .env.example used to ship this value; a stack still carrying it has no real password.
PLACEHOLDER_PASSWORDS = frozenset({"change-me"})
TOUCH_EVERY = dt.timedelta(hours=1)  # last_seen / expiry are written at most this often


def configured_password(settings: Settings) -> str | None:
    if settings.app_password is None:
        return None
    password = settings.app_password.get_secret_value()
    if not password.strip() or password in PLACEHOLDER_PASSWORDS:
        return None
    return password


def auth_enabled(settings: Settings) -> bool:
    return configured_password(settings) is not None


def password_ok(settings: Settings, given: str) -> bool:
    expected = configured_password(settings)
    if expected is None:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(
    session: AsyncSession, settings: Settings, client: str, device: str | None, now: dt.datetime
) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=hash_token(token),
            client=client,
            device=(device or "")[:200] or None,
            last_seen_at=now,
            expires_at=now + dt.timedelta(days=settings.session_days),
        )
    )
    # Expired sessions are cleaned up whenever someone logs in.
    await session.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    await session.commit()
    return token


async def check_session(
    session: AsyncSession, settings: Settings, token: str, now: dt.datetime
) -> bool:
    row = await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    )
    if row is None or row.expires_at <= now:
        return False
    if now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
        row.expires_at = now + dt.timedelta(days=settings.session_days)
        await session.commit()
    return True


async def end_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    await session.commit()


# Device keys (desktop app, Siri shortcut): long-lived, revocable, told apart from session
# tokens by their prefix.
KEY_PREFIX = "yvk_"


async def create_device_key(
    session: AsyncSession, name: str, now: dt.datetime
) -> tuple[DeviceKey, str]:
    """(row, key); the key itself is returned once and never stored."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    row = DeviceKey(
        name=name.strip()[:100] or "Cihaz",
        key_hash=hash_token(key),
        prefix=key[: len(KEY_PREFIX) + 4],
        created_at=now,
    )
    session.add(row)
    await session.commit()
    return row, key


async def check_device_key(session: AsyncSession, key: str, now: dt.datetime) -> bool:
    row = await session.scalar(select(DeviceKey).where(DeviceKey.key_hash == hash_token(key)))
    if row is None or row.revoked_at is not None:
        return False
    if row.last_used_at is None or now - row.last_used_at >= TOUCH_EVERY:
        row.last_used_at = now
        await session.commit()
    return True


class LoginLimiter:
    """At most `attempts` wrong passwords per client in `window` seconds (in memory). At most
    `max_clients` addresses are remembered: the oldest go first."""

    def __init__(self, attempts: int = 5, window: float = 600, max_clients: int = 1000) -> None:
        self.attempts = attempts
        self.window = window
        self.max_clients = max_clients
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str, now: float) -> deque[float]:
        failures = self.failures[key]
        while failures and now - failures[0] > self.window:
            failures.popleft()
        return failures

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Seconds to wait before the next try; 0 = allowed."""
        now = time.monotonic() if now is None else now
        failures = self._recent(key, now)
        if len(failures) < self.attempts:
            return 0
        return max(1, int(self.window - (now - failures[0])) + 1)

    def failed(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._recent(key, now).append(now)
        while len(self.failures) > self.max_clients:
            del self.failures[next(iter(self.failures))]  # dicts keep insertion order

    def succeeded(self, key: str) -> None:
        self.failures.pop(key, None)


limiter = LoginLimiter()
