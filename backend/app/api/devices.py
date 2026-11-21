"""Device keys (Durum → Cihazlar): long-lived keys for the desktop app and the iPhone Siri
shortcut, sent as `Authorization: Bearer yvk_...`. Created and revoked from a logged-in
page; the key is shown once, only its hash is kept."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeviceKey
from app.db.session import get_session
from app.services.auth import create_device_key

router = APIRouter(tags=["devices"])


def _view(row: DeviceKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "revoked": row.revoked_at is not None,
    }


@router.get("/devices")
async def list_devices(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (await session.scalars(select(DeviceKey).order_by(DeviceKey.id.desc()))).all()
    return {"devices": [_view(row) for row in rows]}


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/devices")
async def add_device(
    body: DeviceIn, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """The key comes back only here, once."""
    row, key = await create_device_key(session, body.name, dt.datetime.now(dt.UTC))
    return {**_view(row), "key": key}


@router.delete("/devices/{device_id}")
async def revoke_device(
    device_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    row = await session.get(DeviceKey, device_id)
    if row is None:
        raise HTTPException(404, detail={"code": "unknown_device"})
    if row.revoked_at is None:
        row.revoked_at = dt.datetime.now(dt.UTC)
        await session.commit()
    return _view(row)
