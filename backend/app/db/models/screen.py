"""Screen time sent by the desktop app: one row per device and local day, replaced by
every sync (the desktop always sends the whole day so far, so a resend is harmless)."""

import datetime as dt
from typing import Any

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ScreenTimeDay(TimestampMixin, Base):
    __tablename__ = "screen_time_days"
    __table_args__ = (UniqueConstraint("device", "date", name="uq_screen_time_days_device_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device: Mapped[str] = mapped_column(String(100))  # computer name
    date: Mapped[dt.date]  # local calendar day on that device
    total_seconds: Mapped[int]
    # [{"exe": "Code.exe", "name": "Visual Studio Code", "seconds": 1200}], biggest first
    apps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # [{"name": "VALORANT", "used_seconds": 3600, "limit_seconds": 5400}]
    limits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
