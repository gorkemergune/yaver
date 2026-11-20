"""Weeks of a term: "2025-26 Güz · 8. Hafta", an automatic label from the week's events
("Vize Haftası", "Tatil Haftası"...) unless the user named the week (`week_labels`)."""

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_resolver import week_start
from app.db.models import Attendance, Event, Holiday, Term, WeekLabel
from app.db.models.enums import AttendanceStatus, EventKind

WEEK = dt.timedelta(days=7)
SCHOOL_DAYS = 5  # Mon-Fri
HOLIDAY_WEEK_DAYS = 3  # a holiday on 3+ school days makes a "Tatil Haftası"
FINAL_WEEKS = 3  # exams in the last 3 weeks of a term are finals
EXAM_WEEK_MIN = 2
PROJECT = re.compile(r"proje|project", re.IGNORECASE)

LABEL_HOLIDAY = "Tatil Haftası"
LABEL_BREAK = "Ara tatil"
LABEL_MIDTERM = "Vize Haftası"
LABEL_FINAL = "Final Haftası"
LABEL_PROJECT = "Proje Haftası"


@dataclass(slots=True)
class WeekFacts:
    monday: dt.date
    term: Term | None = None
    week_no: int | None = None
    between_terms: bool = False
    holiday_days: int = 0
    holidays: tuple[str, ...] = ()
    exams: int = 0  # exam kind only (quizzes don't make an exam week)
    quizzes: int = 0
    projects: int = 0  # deadlines / events with "proje" in the title
    absence_hours: int = 0
    user_label: str | None = None

    @property
    def auto_label(self) -> str | None:
        if self.term is None:
            return LABEL_BREAK if self.between_terms else None
        if self.holiday_days >= HOLIDAY_WEEK_DAYS:
            return LABEL_HOLIDAY
        if self.exams >= EXAM_WEEK_MIN:
            final_from = week_start(self.term.end_date) - (FINAL_WEEKS - 1) * WEEK
            return LABEL_FINAL if self.monday >= final_from else LABEL_MIDTERM
        if self.projects:
            return LABEL_PROJECT
        return None

    @property
    def label(self) -> str | None:
        return self.user_label or self.auto_label

    @property
    def title(self) -> str | None:
        if self.term is None or self.week_no is None:
            return None
        return f"{self.term.name} · {self.week_no}. Hafta"

    def as_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.monday.isoformat(),
            "title": self.title,
            "term": self.term.name if self.term else None,
            "week_no": self.week_no,
            "label": self.label,
            "label_source": "user" if self.user_label else "auto" if self.auto_label else None,
            "auto_label": self.auto_label,
            "holidays": list(self.holidays),
            "exams": self.exams,
            "quizzes": self.quizzes,
            "absence_hours": self.absence_hours,
        }


def term_of_week(terms: Sequence[Term], monday: dt.date) -> tuple[Term | None, int | None]:
    """The term that has a school day in this week, and the week's number in it (1-based,
    counted from the Monday of the term's first week)."""
    friday = monday + dt.timedelta(days=SCHOOL_DAYS - 1)
    for term in sorted(terms, key=lambda t: t.start_date):
        if term.start_date <= friday and term.end_date >= monday:
            return term, (monday - week_start(term.start_date)).days // 7 + 1
    return None, None


async def weeks_facts(
    session: AsyncSession, mondays: Sequence[dt.date], tz: ZoneInfo
) -> list[WeekFacts]:
    """Facts for several weeks with one query per table (the term overview lists ~16)."""
    if not mondays:
        return []
    first, last = min(mondays), max(mondays) + WEEK
    terms = (await session.scalars(select(Term))).all()
    holidays = (
        await session.scalars(
            select(Holiday).where(Holiday.start_date < last, Holiday.end_date >= first)
        )
    ).all()
    start = dt.datetime.combine(first, dt.time(), tzinfo=tz)
    end = dt.datetime.combine(last, dt.time(), tzinfo=tz)
    events = (
        await session.scalars(select(Event).where(Event.start_at >= start, Event.start_at < end))
    ).all()
    absences = (
        await session.scalars(
            select(Attendance).where(
                Attendance.date >= first,
                Attendance.date < last,
                Attendance.status == AttendanceStatus.ABSENT,
            )
        )
    ).all()
    labels = {
        row.week_start: row.label
        for row in (
            await session.scalars(
                select(WeekLabel).where(WeekLabel.week_start >= first, WeekLabel.week_start < last)
            )
        ).all()
    }
    out = []
    for monday in mondays:
        term, week_no = term_of_week(terms, monday)
        facts = WeekFacts(monday=monday, term=term, week_no=week_no)
        if term is None:
            facts.between_terms = any(t.end_date < monday for t in terms) and any(
                t.start_date > monday for t in terms
            )
        school_days = [monday + dt.timedelta(days=i) for i in range(SCHOOL_DAYS)]
        applying = [h for h in holidays if h.term_id is None or (term and h.term_id == term.id)]
        facts.holiday_days = sum(any(h.contains(d) for h in applying) for d in school_days)
        facts.holidays = tuple(
            dict.fromkeys(h.name for h in applying if any(h.contains(d) for d in school_days))
        )
        for event in events:
            if week_start(event.start_at.astimezone(tz).date()) != monday:
                continue
            if event.kind is EventKind.EXAM:
                facts.exams += 1
            elif event.kind is EventKind.QUIZ:
                facts.quizzes += 1
            elif PROJECT.search(event.title):
                facts.projects += 1
        facts.absence_hours = sum(a.hours for a in absences if week_start(a.date) == monday)
        facts.user_label = labels.get(monday)
        out.append(facts)
    return out


async def week_facts(session: AsyncSession, day: dt.date, tz: ZoneInfo) -> WeekFacts:
    return (await weeks_facts(session, [week_start(day)], tz))[0]


async def current_term(session: AsyncSession, today: dt.date) -> Term | None:
    """The term today is in; else the next one; else the last one."""
    terms = (await session.scalars(select(Term).order_by(Term.start_date))).all()
    for term in terms:
        if term.contains(today):
            return term
    upcoming = [t for t in terms if t.start_date > today]
    if upcoming:
        return upcoming[0]
    return terms[-1] if terms else None


def term_mondays(term: Term) -> list[dt.date]:
    mondays = []
    monday = week_start(term.start_date)
    while monday <= term.end_date:
        mondays.append(monday)
        monday += WEEK
    return mondays
