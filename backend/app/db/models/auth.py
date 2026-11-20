"""Login sessions (single user). The cookie / bearer token is random; only its SHA-256 is
stored, so a database dump does not hand out valid sessions."""

import datetime as dt

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class AuthSession(CreatedAtMixin, Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client: Mapped[str] = mapped_column(String(20))  # "web" | "desktop"
    device: Mapped[str | None] = mapped_column(String(200))  # user agent / computer name
    last_seen_at: Mapped[dt.datetime]
    expires_at: Mapped[dt.datetime]  # slides forward while the session is used
