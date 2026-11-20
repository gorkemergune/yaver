"""Screen time from the desktop app (`desktop/`): it sends whole days, every 10 minutes
and on exit, and again whatever it could not send while the backend was down."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScreenTimeDay
from app.db.session import get_session
from app.services.screen_time import day_summary

router = APIRouter(tags=["screen-time"])

DAY_SECONDS = 86_400 + 3_600  # a DST day can have 25 hours


class AppTime(BaseModel):
    exe: str = Field(min_length=1, max_length=260)
    name: str = Field(min_length=1, max_length=200)
    seconds: int = Field(ge=0, le=DAY_SECONDS)


class LimitTime(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    used_seconds: int = Field(ge=0, le=DAY_SECONDS)
    limit_seconds: int = Field(ge=0, le=DAY_SECONDS)


class DayIn(BaseModel):
    date: dt.date
    total_seconds: int | None = Field(None, ge=0, le=DAY_SECONDS)  # None: sum of apps
    apps: list[AppTime] = Field(default_factory=list, max_length=1000)
    limits: list[LimitTime] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _total(self) -> "DayIn":
        if self.total_seconds is None:
            self.total_seconds = min(sum(a.seconds for a in self.apps), DAY_SECONDS)
        return self


class ScreenTimeIn(BaseModel):
    device: str = Field("pc", min_length=1, max_length=100)
    days: list[DayIn] = Field(min_length=1, max_length=31)


@router.post("/screen-time")
async def save_screen_time(
    body: ScreenTimeIn, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Idempotent: a day is replaced as a whole (device + date)."""
    for day in body.days:
        statement = insert(ScreenTimeDay).values(
            device=body.device,
            date=day.date,
            total_seconds=day.total_seconds,
            apps=[a.model_dump() for a in sorted(day.apps, key=lambda a: -a.seconds)],
            limits=[lim.model_dump() for lim in day.limits],
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_screen_time_days_device_date",
                set_={
                    "total_seconds": statement.excluded.total_seconds,
                    "apps": statement.excluded.apps,
                    "limits": statement.excluded.limits,
                    "updated_at": dt.datetime.now(dt.UTC),
                },
            )
        )
    await session.commit()
    return {"saved": [d.date.isoformat() for d in body.days]}


@router.get("/screen-time/{day}")
async def get_screen_time(day: dt.date, session: AsyncSession = Depends(get_session)) -> Any:
    summary = await day_summary(session, day)
    return summary or {"date": day.isoformat(), "total_seconds": 0, "apps": [], "limits": []}
