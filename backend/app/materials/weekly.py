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


async def titles_like(
    session: AsyncSession, query: str, course_id: int | None
) -> list[dict[str, Any]]:
    """Materials whose file / tab name is in the question ("labwork01 part 2" ->
    "Labwork01 - Part II.pdf") with their course and weeks: a name is not found by meaning."""
    asked = _compact(query.replace(" ii", " 2").replace(" i ", " 1 "))
    query_rows = select(CourseMaterial, Course.code).join(
        Course, Course.id == CourseMaterial.course_id
    )
    if course_id is not None:
        query_rows = query_rows.where(CourseMaterial.course_id == course_id)
    found = []
    for material, code in (await session.execute(query_rows)).all():
        stem = PurePath(material.title).stem.split(": ")[-1]
        name = _compact(stem.replace(" II", " 2").replace(" I", " 1"))
        if len(name) < 4 or name not in asked:
            continue
        weeks = sorted(
            {
                w
                for row in (
                    await session.scalars(
                        select(MaterialSection.week_nos).where(
                            MaterialSection.material_id == material.id
                        )
                    )
                ).all()
                for w in row
            }
            | ({material.week_no} if material.week_no else set())
            | {
                w
                for row in (
                    await session.scalars(
                        select(SourceItem.week_nos).where(SourceItem.material_id == material.id)
                    )
                ).all()
                for w in row
            }
        )
        found.append({"file": material.title, "course": code, "weeks": weeks})
    return found[:5]


NUMBERED = re.compile(
    r"(?:\b(\d{1,2})\s*\.?\s*(?:deney|experiment|lab|deneyi)\b"
    r"|\b(?:deney|experiment|lab)\w*\s*#?\s*(\d{1,2})\b)"
)


async def sections_numbered(
    session: AsyncSession, query: str, course_id: int | None
) -> list[dict[str, Any]]:
    """ "5. deney" / "deney 5" / "lab 5" -> the section "Experiment #5 ..." of a lab book, with
    its pages and weeks (the table of contents is in the database; meaning search may miss
    a Turkish number for an English title)."""
    match = NUMBERED.search(normalize(query))
    if not match:
        return []
    number = match[1] or match[2]
    pattern = re.compile(rf"(?:experiment|deney|lab)\w*\s*#?\s*0?{number}\b", re.IGNORECASE)
    statement = select(MaterialSection, CourseMaterial.title).join(
        CourseMaterial, CourseMaterial.id == MaterialSection.material_id
    )
    if course_id is not None:
        statement = statement.where(MaterialSection.course_id == course_id)
    found = []
    for section, title in (await session.execute(statement)).all():
        if pattern.search(normalize(section.title)):
            found.append(
                {
                    "file": title,
                    "section": section.title,
                    "pages": _pages(section.page_start, section.page_end),
                    "weeks": list(section.week_nos or []),
                }
            )
    return found[:3]


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize(text))


async def syllabus_files(session: AsyncSession, course_id: int) -> list[str]:
    """The file(s) the course's weekly plan was read from, to cite ("CSE221 ... Syllabus.pdf")."""
    rows = await session.scalars(
        select(CourseMaterial.title)
        .join(SyllabusWeek, SyllabusWeek.material_id == CourseMaterial.id)
        .where(SyllabusWeek.course_id == course_id)
        .distinct()
    )
    return sorted(rows.all())


async def week_material_ids(session: AsyncSession, course_id: int, week: int) -> list[int]:
    """Materials mapped to the week: book / lab sections, shared-notes tabs, sheets, notes
    saved for that week (a tab of weeks 4-5 has no single week_no on its passages)."""
    ids: set[int | None] = set(
        (
            await session.scalars(
                select(MaterialSection.material_id).where(
                    MaterialSection.course_id == course_id, MaterialSection.week_nos.overlap([week])
                )
            )
        ).all()
    )
    ids |= set(
        (
            await session.scalars(
                select(SourceItem.material_id)
                .join(CourseSource, CourseSource.id == SourceItem.source_id)
                .where(
                    CourseSource.course_id == course_id,
                    SourceItem.removed_at.is_(None),
                    SourceItem.week_nos.overlap([week]),
                    SourceItem.material_id.is_not(None),
                )
            )
        ).all()
    )
    ids |= set(
        (
            await session.scalars(
                select(CourseMaterial.id).where(
                    CourseMaterial.course_id == course_id, CourseMaterial.week_no == week
                )
            )
        ).all()
    )
    return sorted(i for i in ids if i is not None)


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
