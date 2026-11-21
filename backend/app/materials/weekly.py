"""What one week of a course holds: the syllabus row (topics, readings, lab, exam) and what
the materials mapped to it - book / lab-book sections with their pages, the shared notes'
tabs, homework / lab sheets, uploaded notes of that week. All read in code; used by
get_syllabus / get_exam_scope (Scholar), the Sunday weekly plan and the exam review plan.
"""

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_resolver import normalize
from app.db.models import (
    Course,
    CourseMaterial,
    CourseSource,
    Event,
    MaterialSection,
    SourceItem,
    SyllabusWeek,
)
from app.db.models.enums import EventKind
from app.services.weeks import week_facts

SHEET_KINDS = ("homework", "lab")
WORD = re.compile(r"[a-z0-9]{4,}")
# words of a topic that say nothing about it
COMMON = frozenset(
    {"introduction", "giris", "and", "the", "with", "konu", "konulari", "review", "tekrar"}
)
# Turkish course words -> the English a syllabus uses (prefixes, normalized: no accents).
# The user writes "kanonik formlar", the syllabus "Canonical Forms".
GLOSSARY: dict[str, tuple[str, ...]] = {
    "kanonik": ("canonical",),
    "harita": ("map",),
    "sayi": ("number",),
    "sistem": ("system",),
    "kod": ("code",),
    "toplayici": ("adder",),
    "cikarici": ("subtractor",),
    "carpici": ("multiplier",),
    "karsilastirici": ("comparator",),
    "cozucu": ("decoder",),
    "kodlayici": ("encoder",),
    "flip": ("flip",),
    "sayac": ("counter",),
    "kaydedici": ("register",),
    "ardisil": ("sequential",),
    "birlesik": ("combinational",),
    "sadelestir": ("simplification", "simplify"),
    "fonksiyon": ("function",),
    "matris": ("matrix", "matrices"),
    "determinant": ("determinant",),
    "vektor": ("vector",),
    "lineer": ("linear",),
    "dogrusal": ("linear",),
    "donusum": ("transformation",),
    "ozdeger": ("eigenvalue",),
    "ozvektor": ("eigenvector",),
    "uzay": ("space",),
    "taban": ("basis",),
    "devre": ("circuit",),
    "dugum": ("nodal", "node"),
    "cevre": ("mesh",),
    "kaynak": ("source",),
    "direnc": ("resistor", "resistance"),
    "kondansator": ("capacitor",),
    "bobin": ("inductor",),
    "agac": ("tree",),
    "yigin": ("stack", "heap"),
    "kuyruk": ("queue",),
    "liste": ("list",),
    "siralama": ("sorting", "sort"),
    "arama": ("search",),
    "ozyineleme": ("recursion",),
    "karmasiklik": ("complexity", "analysis"),
    "isaretci": ("pointer",),
    "sinif": ("class",),
    "kalitim": ("inheritance",),
    "graf": ("graph",),
    "hash": ("hash",),
}


@dataclass(slots=True)
class WeekRef:
    course: str
    week_no: int
    topics: str
    dates: str | None = None
    readings: str | None = None
    lab: str | None = None
    assessment: str | None = None
    sections: list[str] = field(default_factory=list)  # "Kitap: 3.2 Başlık (s. 40-43)"
    notes: list[str] = field(default_factory=list)  # "CSE 221 notları: Map (Karnaugh ...)"
    sheets: list[str] = field(default_factory=list)  # "Labwork01 - Part II.pdf"

    def as_dict(self, materials: bool = True) -> dict[str, Any]:
        found: dict[str, Any] = {"week": self.week_no, "topics": self.topics}
        for key in ("dates", "readings", "lab", "assessment"):
            if getattr(self, key):
                found[key] = getattr(self, key)
        if materials:
            for key in ("sections", "notes", "sheets"):
                if getattr(self, key):
                    found[key] = getattr(self, key)
        return found

    def to_read(self) -> str:
        """One line of what to read / do ("okuma: 3.5, 3.6 · notlar: ... · lab: ...")."""
        parts = []
        if self.readings:
            parts.append(f"okuma: {self.readings}")
        if self.sections:
            parts.append("bölümler: " + "; ".join(self.sections))
        if self.lab:
            parts.append(f"lab: {self.lab}")
        if self.sheets:
            parts.append("föy: " + ", ".join(self.sheets))
        if self.notes:
            parts.append("notlar: " + ", ".join(self.notes))
        if self.assessment:
            parts.append(f"sınav/teslim: {self.assessment}")
        return " · ".join(parts)


def _pages(start: int, end: int) -> str:
    return f"s. {start}" if start == end else f"s. {start}-{end}"


async def course_weeks(
    session: AsyncSession, course: Course, week_nos: Iterable[int] | None = None
) -> list[WeekRef]:
    """The course's weeks (all, or `week_nos`) with what is mapped to each."""
    query = select(SyllabusWeek).where(SyllabusWeek.course_id == course.id)
    wanted = sorted(set(week_nos)) if week_nos is not None else None
    if wanted is not None:
        query = query.where(SyllabusWeek.week_no.in_(wanted))
    rows = (await session.scalars(query.order_by(SyllabusWeek.week_no))).all()
    refs = {
        r.week_no: WeekRef(
            course.code, r.week_no, r.topics, r.dates_text, r.readings, r.lab, r.assessment
        )
        for r in rows
    }
    if not refs:
        return []
    numbers = list(refs)
    sections = (
        await session.execute(
            select(MaterialSection, CourseMaterial)
            .join(CourseMaterial, CourseMaterial.id == MaterialSection.material_id)
            .where(
                MaterialSection.course_id == course.id,
                MaterialSection.week_nos.overlap(numbers),
            )
            .order_by(CourseMaterial.id, MaterialSection.page_start)
        )
    ).all()
    shown: set[int] = set()
    for section, material in sections:
        sheet = material.kind in SHEET_KINDS and section.title == PurePath(material.title).stem
        for week in section.week_nos:
            ref = refs.get(week)
            if ref is None:
                continue
            if sheet:
                ref.sheets.append(material.title)
            else:
                label = " ".join(p for p in (section.number, section.title) if p)
                ref.sections.append(
                    f"{material.title}: {label} ({_pages(section.page_start, section.page_end)})"
                )
        shown.add(material.id)
    tabs = (
        await session.execute(
            select(SourceItem, CourseMaterial)
            .join(CourseSource, CourseSource.id == SourceItem.source_id)
            .join(CourseMaterial, CourseMaterial.id == SourceItem.material_id)
            .where(
                CourseSource.course_id == course.id,
                SourceItem.removed_at.is_(None),
                SourceItem.week_nos.overlap(numbers),
            )
            .order_by(SourceItem.position)
        )
    ).all()
    for item, material in tabs:
        for week in item.week_nos:
            if week in refs:
                topic = f" ({item.topic})" if item.topic else ""
                refs[week].notes.append(f"{material.title}{topic}")
        shown.add(material.id)
    uploaded = (
        await session.scalars(
            select(CourseMaterial).where(
                CourseMaterial.course_id == course.id,
                CourseMaterial.week_no.in_(numbers),
                CourseMaterial.kind.not_in(("syllabus",)),
            )
        )
    ).all()
    for material in uploaded:
        if material.id not in shown and material.week_no in refs:
            refs[material.week_no].notes.append(material.title)
    return [refs[n] for n in sorted(refs)]


def topics_of(notes: str | None) -> list[str]:
    """The topics add_event wrote into the exam's notes ("Konular: a, b")."""
    for line in (notes or "").splitlines():
        if line.startswith("Konular: "):
            return [t.strip() for t in line.removeprefix("Konular: ").split(",") if t.strip()]
    return []


def is_final(exam: Event) -> bool:
    return "final" in exam.title.lower()


async def covered_weeks(
    session: AsyncSession, exam: Event, course: Course, tz: ZoneInfo
) -> list[SyllabusWeek]:
    """Syllabus weeks the exam covers: after the course's previous exam, up to the exam's
    own week (exam weeks themselves left out); a final covers everything."""
    weeks = (
        await session.scalars(
            select(SyllabusWeek)
            .where(SyllabusWeek.course_id == course.id)
            .order_by(SyllabusWeek.week_no)
        )
    ).all()
    teaching = [
        w for w in weeks if "sınav" not in w.topics.lower() and "exam" not in w.topics.lower()
    ]
    exam_week = (await week_facts(session, exam.start_at.astimezone(tz).date(), tz)).week_no
    if is_final(exam) or exam_week is None:
        return list(teaching)
    previous = await session.scalar(
        select(Event)
        .where(
            Event.course_id == course.id,
            Event.kind == EventKind.EXAM,
            Event.start_at < exam.start_at,
        )
        .order_by(Event.start_at.desc())
        .limit(1)
    )
    after = 0
    if previous is not None:
        after = (
            await week_facts(session, previous.start_at.astimezone(tz).date(), tz)
        ).week_no or 0
    return [w for w in teaching if after < w.week_no < exam_week] or list(teaching)


async def term_week(session: AsyncSession, day: dt.date, tz: ZoneInfo) -> int | None:
    return (await week_facts(session, day, tz)).week_no


def words(text: str) -> set[str]:
    found = {w for w in WORD.findall(normalize(text)) if w not in COMMON}
    for word in list(found):
        for turkish, english in GLOSSARY.items():
            if word.startswith(turkish):
                found.update(english)
    return found


def _alike(asked: set[str], mine: set[str]) -> bool:
    return any(a in mine or any(m.startswith(a) or a.startswith(m) for m in mine) for a in asked)


@dataclass(slots=True)
class TopicMatch:
    weeks: list[int]  # weeks matching any of the user's topics
    missing: list[str]  # topics the syllabus does not mention

    @property
    def complete(self) -> bool:
        """Every topic found: the exam is those weeks (else the covered weeks stay)."""
        return bool(self.weeks) and not self.missing


def match_topics(told: list[str], weeks: list[WeekRef]) -> TopicMatch:
    """The user's topics ("Karnaugh", "kanonik formlar") in the syllabus weeks' topics and
    readings ("Karnaugh Maps", "Canonical Forms"): word prefixes + a small glossary."""
    found: set[int] = set()
    missing = []
    for topic in told:
        asked = words(topic)
        hits = {
            w.week_no
            for w in weeks
            if asked and _alike(asked, words(f"{w.topics} {w.readings or ''}"))
        }
        if hits:
            found |= hits
        else:
            missing.append(topic)
    return TopicMatch(sorted(found), missing)


async def next_week_lines(session: AsyncSession, monday: dt.date, tz: ZoneInfo) -> list[str]:
    """For the Sunday plan: each course's week starting `monday`, what to read / do."""
    week = await term_week(session, monday, tz)
    if week is None:
        return []
    lines = []
    for course in (await session.scalars(select(Course).order_by(Course.code))).all():
        for ref in await course_weeks(session, course, [week]):
            extra = ref.to_read()
            lines.append(
                f"{course.code} ({week}. hafta): {ref.topics}" + (f" · {extra}" if extra else "")
            )
    return lines
