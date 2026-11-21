"""Academic calendar: terms, holidays, courses."""

import datetime as dt

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Term(TimestampMixin, Base):
    """A semester. Class/lab blocks only occur inside a term (dates inclusive)."""

    __tablename__ = "terms"
    __table_args__ = (CheckConstraint("end_date >= start_date", name="date_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[dt.date]
    end_date: Mapped[dt.date]

    def contains(self, day: dt.date) -> bool:
        return self.start_date <= day <= self.end_date


class Holiday(TimestampMixin, Base):
    """No classes on these dates (inclusive). `term_id` NULL = applies to every term."""

    __tablename__ = "holidays"
    __table_args__ = (CheckConstraint("end_date >= start_date", name="date_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int | None] = mapped_column(
        ForeignKey("terms.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[dt.date]
    end_date: Mapped[dt.date]

    def contains(self, day: dt.date) -> bool:
        return self.start_date <= day <= self.end_date


class Course(TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("term_id", "code", name="uq_courses_term_code"),
        CheckConstraint("absence_limit IS NULL OR absence_limit >= 0", name="absence_limit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int | None] = mapped_column(
        ForeignKey("terms.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    # other names the user calls it ("DSA", "Veri Yapıları"); saved when the user tells
    # which course an unknown abbreviation is (add_course_alias)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list, server_default="{}")
    instructor: Mapped[str | None] = mapped_column(String(200))
    absence_limit: Mapped[int | None]
    color: Mapped[str | None] = mapped_column(String(7))  # "#4f46e5"
    notes: Mapped[str | None] = mapped_column(Text)
