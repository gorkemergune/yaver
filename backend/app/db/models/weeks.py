"""A name the user gave a week ("Hackathon Haftası"); overrides the automatic label."""

import datetime as dt

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WeekLabel(TimestampMixin, Base):
    __tablename__ = "week_labels"
    __table_args__ = (
        CheckConstraint("EXTRACT(ISODOW FROM week_start) = 1", name="week_start_monday"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[dt.date] = mapped_column(unique=True)  # Monday
    label: Mapped[str] = mapped_column(String(100))
