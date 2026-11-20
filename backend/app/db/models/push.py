"""Web Push subscriptions: one row per browser / device that turned notifications on."""

import datetime as dt

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class PushSubscription(CreatedAtMixin, Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)  # the push service URL
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    last_sent_at: Mapped[dt.datetime | None]
    failures: Mapped[int] = mapped_column(default=0, server_default="0")  # in a row
