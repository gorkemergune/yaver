"""Login / logout and the dependency that guards every other API route."""

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.auth import (
    COOKIE,
    KEY_PREFIX,
    auth_enabled,
    check_device_key,
    check_session,
    create_session,
    end_session,
    limiter,
    password_ok,
)

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE_MAX_AGE = 400 * 86_400  # browsers cap cookies at 400 days


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def request_token(request: Request) -> str | None:
    """`Authorization: Bearer ...` (a device key or a desktop login), else the cookie."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(COOKIE) or None


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


async def require_auth(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    """Router dependency: 401 without a valid session or device key (when a password is
    set). Device keys (`yvk_...`, desktop app / Siri shortcut) don't expire."""
    if not auth_enabled(settings):
        return
    token = request_token(request)
    if token is not None and token.startswith(KEY_PREFIX):
        if await check_device_key(session, token, _now()):
            return
        raise HTTPException(401, detail={"code": "device_key_invalid"})
    if token is None or not await check_session(session, settings, token, _now()):
        raise HTTPException(401, detail={"code": "login_required"})


class LoginIn(BaseModel):
    password: str = Field(max_length=500)
    client: Literal["web", "desktop"] = "web"
    device: str | None = Field(None, max_length=200)  # desktop: computer name


@router.get("/status")
async def status(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not auth_enabled(settings):
        return {"enabled": False, "authenticated": True}
    token = request_token(request)
    ok = token is not None and await check_session(session, settings, token, _now())
    return {"enabled": True, "authenticated": ok}


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not auth_enabled(settings):
        return {"enabled": False, "authenticated": True}
    key = _client_key(request)
    wait = limiter.retry_after(key)
    if wait:
        raise HTTPException(
            429,
            detail={"code": "too_many_attempts", "retry_after": wait},
            headers={"Retry-After": str(wait)},
        )
    if not password_ok(settings, body.password):
        limiter.failed(key)
        raise HTTPException(401, detail={"code": "wrong_password"})
    limiter.succeeded(key)
    device = body.device or request.headers.get("user-agent")
    token = await create_session(session, settings, body.client, device, _now())
    if body.client == "desktop":
        return {"enabled": True, "authenticated": True, "token": token}
    response.set_cookie(
        COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,  # the server-side session expires after SESSION_DAYS idle
        httponly=True,
        samesite="lax",
        secure=_https(request),
        path="/",
    )
    return {"enabled": True, "authenticated": True}


@router.post("/logout")
async def logout(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    token = request_token(request)
    if token:
        await end_session(session, token)
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}
