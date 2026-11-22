"""Loads a folder of course materials into the database (see app.materials).

    python -m app.materials.ingest /materials [--dry-run] [--force]
        [--term-start 2026-09-28 --term-end 2027-01-22 --term-name "2026-27 Güz"]
        [--alias "BME 211=EE211"] [--create-courses]

Per file: course (code in the path or the first pages; never a guess between two), kind
(syllabus / lab / homework / book / notes), then
- syllabus: Sonnet reads the weekly plan, books and exams -> syllabus_weeks, course_books;
  written week dates are checked against the term;
- book / lab book: table of contents -> material_sections, sections mapped to weeks; only
  the mapped sections of a book are embedded (CPU), a lab book entirely;
- homework / lab sheet / notes: mapped to weeks, embedded.
A file already loaded (same SHA-256) is skipped unless --force. Ends with a JSON report.
"""

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.core.time_resolver import normalize
from app.db.models import (
    Attachment,
    Course,
    CourseBook,
    CourseMaterial,
    LlmUsage,
    MaterialSection,
    SyllabusWeek,
    Term,
)
from app.db.session import get_sessionmaker
from app.materials import mapping, syllabus, toc
from app.materials.text import UnreadableError, document_pages
from app.materials.weekly import compact
from app.rag.store import index_material

logger = logging.getLogger("app.materials.ingest")

SUFFIXES = (".pdf", ".docx")
BOOK_PAGES = 80  # a PDF this long with a table of contents is a book
SHEET_HINT_CHARS = 1500  # of a homework / lab sheet, for mapping it to weeks
MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
KIND_WORDS = (
    ("syllabus", ("syllabus", "izlence", "course outline", "course plan")),
    ("homework", ("homework", "hw", "odev", "assignment")),
    ("lab", ("lab", "labwork", "laboratory", "experiment", "deney")),
)


@dataclass
class FileReport:
    path: str
    status: str = "new"  # new | updated | skipped | unclear | error
    kind: str | None = None
    course: str | None = None
    pages: int = 0
    weeks: int = 0
    books: int = 0
    sections: int = 0
    mapped_sections: int = 0
    week_nos: list[int] = field(default_factory=list)
    passages: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class Report:
    files: list[FileReport] = field(default_factory=list)
    courses_created: list[str] = field(default_factory=list)
    term: str | None = None
    seconds: float = 0.0
    llm_usd: float = 0.0


# ---- courses -------------------------------------------------------------------------------


def code_pattern(code: str) -> re.Pattern[str] | None:
    """'CSE 211' -> cse 211 / cse211 / cse-211 in normalized text."""
    match = re.fullmatch(r"([a-z]+)\s*-?\s*(\d{3})", normalize(code).strip())
    if not match:
        return None
    return re.compile(rf"(?<![a-z]){match[1]}\s*[-_]?\s*{match[2]}(?!\d)")


class Courses:
    def __init__(self, courses: list[Course], aliases: dict[str, str]):
        self.courses = courses
        self.aliases = {compact(k): compact(v) for k, v in aliases.items()}  # "bme211" -> "ee211"

    def by_code(self, code: str | None) -> Course | None:
        if not code:
            return None
        key = compact(code)
        key = self.aliases.get(key, key)
        for course in self.courses:
            names = [course.code, *(course.aliases or [])]
            if key in {compact(n) for n in names}:
                return course
        return None

    def in_text(self, text: str) -> list[Course]:
        """Courses whose code (or a code alias) appears in the text, most mentions first."""
        norm = normalize(text)
        counts: dict[int, tuple[int, Course]] = {}
        names_of: list[tuple[Course, str]] = [
            (c, n) for c in self.courses for n in (c.code, *(c.aliases or []))
        ]
        names_of += [
            (c, alias)
            for alias, target in self.aliases.items()
            for c in self.courses
            if compact(c.code) == target
        ]
        for course, name in names_of:
            pattern = code_pattern(name)
            if pattern is None:
                if len(name) >= 8 and normalize(name) in norm:  # "uygarlik tarihi"
                    hits = norm.count(normalize(name))
                else:
                    continue
            else:
                hits = len(pattern.findall(norm))
            if hits:
                before = counts.get(course.id, (0, course))[0]
                counts[course.id] = (before + hits, course)
        return [c for _, c in sorted(counts.values(), key=lambda t: -t[0])]

    def find(self, relative: str, pages: list[str]) -> tuple[Course | None, str | None]:
        """(course, why not) from the path first, then the first two pages."""
        in_path = self.in_text(relative.replace("_", " "))
        if len(in_path) == 1:
            return in_path[0], None
        in_text = self.in_text("\n".join(pages[:2]))
        if in_text:
            return in_text[0], None if len(in_text) == 1 else "birden fazla ders kodu geçiyor"
        return None, "ders kodu bulunamadı"


# ---- kinds -----------------------------------------------------------------------------------


def guess_kind(relative: str, pages: list[str], has_sections: bool) -> str:
    name = normalize(Path(relative).stem.replace("_", " ").replace("-", " "))
    words = set(re.findall(r"[a-z]+", name))
    for kind, keys in KIND_WORDS:
        if any((k in words) if " " not in k and len(k) <= 3 else (k in name) for k in keys):
            return kind
    first = normalize(" ".join(pages[:2]))[:3000]
    if "syllabus" in first or "izlence" in first:
        return "syllabus"
    if len(pages) >= BOOK_PAGES and has_sections:
        return "book"
    return "notes"


# ---- one file -------------------------------------------------------------------------------


async def ingest_file(
    session: AsyncSession,
    llm: Any,
    root: Path,
    path: Path,
    courses: Courses,
    term: Term | None,
    args: argparse.Namespace,
    report: Report,
) -> FileReport:
    relative = str(path.relative_to(root))
    item = FileReport(relative)
    raw = await asyncio.to_thread(path.read_bytes)
    digest = hashlib.sha256(raw).hexdigest()
    existing = await session.scalar(
        select(CourseMaterial)
        .join(Attachment, Attachment.id == CourseMaterial.attachment_id)
        .where(Attachment.sha256 == digest)
    )
    if existing is not None and not args.force:
        item.status, item.kind = "skipped", existing.kind
        course = await session.get(Course, existing.course_id) if existing.course_id else None
        item.course = course.code if course else None
        return item
    try:
        pages = await asyncio.to_thread(document_pages, path.name, raw)
    except UnreadableError as exc:
        item.status = "error"
        item.notes.append(str(exc))
        return item
    item.pages = len(pages)
    if sum(len(p) for p in pages) < 80:
        item.status = "error"
        item.notes.append("metin yok (taranmış PDF olabilir)")
        return item
    found_sections = toc.sections(raw, pages) if path.suffix.lower() == ".pdf" else []
    item.kind = guess_kind(relative, pages, bool(found_sections))
    course, why = courses.find(relative, pages)

    parsed: syllabus.FullSyllabus | None = None
    if item.kind == "syllabus" and not args.dry_run:
        parsed, model = await syllabus.parse(llm, pages)
        item.notes.append(f"okuyan: {model}")
        by_syllabus = courses.by_code(parsed.course_code)
        if by_syllabus is not None:
            course, why = by_syllabus, None
        elif course is None and args.create_courses and parsed.course_code:
            course = Course(
                code=parsed.course_code.upper().strip()[:20],
                name=(parsed.course_name or parsed.course_code).strip()[:200],
                term_id=term.id if term else None,
            )
            session.add(course)
            await session.flush()
            courses.courses.append(course)
            report.courses_created.append(course.code)
            why = None
    if course is None:
        item.status = "unclear"
        item.notes.append(why or "ders bulunamadı")
        return item
    item.course = course.code
    if args.dry_run:
        item.status = "dry-run"
        item.sections = len(found_sections)
        return item

    now = dt.datetime.now(dt.UTC)
    material = existing or CourseMaterial(
        course_id=course.id, kind=item.kind, title=path.name, pages=len(pages), week_no=None
    )
    if existing is None:
        attachment = Attachment(
            path=await asyncio.to_thread(
                _store, raw, path.suffix.lower().lstrip("."), now, args.upload_dir
            ),
            mime=MIME[path.suffix.lower()],
            width=0,
            height=0,
            size_bytes=len(raw),
            sha256=digest,
            filename=path.name,
        )
        session.add(attachment)
        await session.flush()
        material.attachment_id = attachment.id
        session.add(material)
        await session.flush()
    else:
        item.status = "updated"
        material.course_id, material.kind = course.id, item.kind

    plan = await _plan(session, course)
    if parsed is not None:
        await _save_syllabus(session, course, material, parsed, term, item)
        plan = await _plan(session, course)
    index_pages = pages
    if found_sections and item.kind in ("book", "lab"):
        index_pages = await _save_sections(
            session, llm, course, material, found_sections, plan, pages, item
        )
    elif item.kind in ("homework", "lab", "notes") and plan:
        # the whole text squeezed (a sheet's first lines are often only instructions)
        hint = " ".join(" ".join(pages).split())[:SHEET_HINT_CHARS]
        entry = mapping.Entry(None, path.stem, hint)
        weeks = (await mapping.map_to_weeks(llm, course.code, plan, [entry])).get(0, [])
        item.week_nos = weeks
        material.week_no = weeks[0] if len(weeks) == 1 else None
        # one "section" = the whole sheet with all its weeks ("hangi hafta hangi lab")
        await session.execute(
            delete(MaterialSection).where(MaterialSection.material_id == material.id)
        )
        session.add(
            MaterialSection(
                material_id=material.id,
                course_id=course.id,
                number=None,
                title=path.stem[:300],
                page_start=1,
                page_end=max(1, len(pages)),
                week_nos=weeks,
            )
        )
        if not weeks:
            item.notes.append("haftası bulunamadı")
    started = time.monotonic()
    item.passages = await index_material(session, material, index_pages, now)
    logger.info(
        "  %s: %d passages embedded in %.1fs", relative, item.passages, time.monotonic() - started
    )
    await session.commit()
    return item


def _store(raw: bytes, extension: str, now: dt.datetime, upload_dir: str | None) -> str:
    from app.api.uploads import store_pdf  # the same layout as uploads (YYYY/MM/<sha>.<ext>)

    return store_pdf(
        raw, Path(upload_dir) if upload_dir else get_settings().upload_dir, now, extension
    )


async def _plan(session: AsyncSession, course: Course) -> list[mapping.PlanWeek]:
    rows = (
        await session.scalars(
            select(SyllabusWeek)
            .where(SyllabusWeek.course_id == course.id)
            .order_by(SyllabusWeek.week_no)
        )
    ).all()
    return [mapping.PlanWeek(r.week_no, r.topics, r.readings, r.lab) for r in rows]


async def _save_syllabus(
    session: AsyncSession,
    course: Course,
    material: CourseMaterial,
    parsed: syllabus.FullSyllabus,
    term: Term | None,
    item: FileReport,
) -> None:
    exam_notes = {e.week_no: f"{e.kind}: {e.when}" for e in parsed.exams if e.week_no}
    for week in parsed.weeks:
        row = await session.scalar(
            select(SyllabusWeek).where(
                SyllabusWeek.course_id == course.id, SyllabusWeek.week_no == week.week_no
            )
        )
        if row is None:
            row = SyllabusWeek(course_id=course.id, week_no=week.week_no, topics=week.topics)
            session.add(row)
        row.material_id = material.id
        row.topics = week.topics
        row.dates_text = (week.dates or None) and week.dates[:80]
        row.readings = week.readings
        row.lab = week.lab
        row.assessment = week.assessment or exam_notes.get(week.week_no)
    item.weeks = len(parsed.weeks)
    for book in parsed.books:
        title = book.title.strip()[:300]
        row_book = await session.scalar(
            select(CourseBook).where(CourseBook.course_id == course.id, CourseBook.title == title)
        )
        if row_book is None:
            row_book = CourseBook(course_id=course.id, title=title)
            session.add(row_book)
        row_book.authors = book.authors and book.authors[:300]
        row_book.edition = book.edition and book.edition[:60]
        row_book.required = book.required
    item.books = len(parsed.books)
    for exam in parsed.exams:
        item.notes.append(f"sınav: {exam.kind} {exam.when}")
    if parsed.unclear:
        item.notes.append("belirsiz: " + "; ".join(parsed.unclear))
    if not parsed.weeks:
        item.notes.append("haftalık plan yok (yalnız konu listesi)")
    if term is not None and parsed.weeks:
        check = syllabus.check_weeks(parsed.weeks, term.start_date)
        if check.ok or check.mismatches:
            item.notes.append(f"tarih kontrolü: {check.ok} hafta tutuyor")
        item.notes += [f"tarih uyuşmuyor: {m}" for m in check.mismatches]
    await session.flush()


async def _save_sections(
    session: AsyncSession,
    llm: Any,
    course: Course,
    material: CourseMaterial,
    found: list[toc.Section],
    plan: list[mapping.PlanWeek],
    pages: list[str],
    item: FileReport,
) -> list[str]:
    """Writes the table of contents with weeks; returns the pages to embed (a book: only
    the sections mapped to weeks; a lab book: all)."""
    await session.execute(delete(MaterialSection).where(MaterialSection.material_id == material.id))
    leaves = [
        s
        for s in found
        if not any(
            o.level > s.level and s.page_start <= o.page_start <= s.page_end and o is not s
            for o in found
        )
    ]
    entries = [mapping.Entry(s.number, s.title) for s in leaves]
    weeks = await mapping.map_to_weeks(llm, course.code, plan, entries) if plan else {}
    keep: set[int] = set()
    for section in found:
        week_nos = weeks.get(leaves.index(section), []) if section in leaves else []
        session.add(
            MaterialSection(
                material_id=material.id,
                course_id=course.id,
                number=section.number,
                title=section.title[:300],
                page_start=section.page_start,
                page_end=section.page_end,
                week_nos=week_nos,
            )
        )
        if week_nos:
            keep.update(range(section.page_start, section.page_end + 1))
            item.mapped_sections += 1
    item.sections = len(found)
    if not plan:
        item.notes.append("dersin haftalık planı yok: bölümler haftalara eşlenmedi")
    await session.flush()
    if item.kind != "book":
        return pages
    return [p if (i + 1) in keep else "" for i, p in enumerate(pages)]


# ---- the run ---------------------------------------------------------------------------------


async def _term(session: AsyncSession, args: argparse.Namespace, report: Report) -> Term | None:
    if args.term_start:
        start = dt.date.fromisoformat(args.term_start)
        term = await session.scalar(
            select(Term).where(Term.start_date <= start, Term.end_date >= start)
        )
        if term is None and not args.dry_run:
            end = (
                dt.date.fromisoformat(args.term_end)
                if args.term_end
                else start + dt.timedelta(weeks=17)
            )
            term = Term(name=args.term_name or f"{start.year} Güz", start_date=start, end_date=end)
            session.add(term)
            await session.flush()
        report.term = f"{term.name} ({term.start_date} - {term.end_date})" if term else None
        return term
    today = dt.datetime.now(get_settings().tz).date()
    term = await session.scalar(
        select(Term).where(Term.start_date <= today, Term.end_date >= today)
    )
    report.term = f"{term.name} ({term.start_date} - {term.end_date})" if term else None
    return term


async def run(
    args: argparse.Namespace,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    llm: Any = None,
) -> Report:
    from app.llm.router import get_router  # not at import time: tests run without providers

    root = Path(args.folder)
    files = await asyncio.to_thread(_files, root)
    if args.only:
        files = [p for p in files if re.search(args.only, str(p), re.IGNORECASE)]
    report = Report()
    started = time.monotonic()
    if llm is None and not args.dry_run:
        llm = get_router()
    aliases = dict(a.split("=", 1) for a in args.alias)
    async with (sessionmaker or get_sessionmaker())() as session:
        term = await _term(session, args, report)
        courses = Courses(list((await session.scalars(select(Course))).all()), aliases)
        await session.commit()
        since = dt.datetime.now(dt.UTC)
        # syllabi first: the other files are mapped to their weekly plans
        files.sort(key=lambda p: 0 if guess_kind(p.name, [], False) == "syllabus" else 1)
        for number, path in enumerate(files, start=1):
            logger.info("[%d/%d] %s", number, len(files), path.relative_to(root))
            try:
                item = await ingest_file(session, llm, root, path, courses, term, args, report)
            except Exception as exc:  # one broken file never stops the rest
                await session.rollback()  # expires every object: load the courses again
                courses.courses = list((await session.scalars(select(Course))).all())
                logger.exception("%s failed", path)
                item = FileReport(
                    str(path.relative_to(root)), status="error", notes=[repr(exc)[:300]]
                )
            report.files.append(item)
            logger.info(
                "  -> %s %s %s %s", item.status, item.kind, item.course, "; ".join(item.notes)
            )
        await session.commit()
        spent = await session.scalar(
            select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
                LlmUsage.created_at >= since
            )
        )
    report.seconds = round(time.monotonic() - started, 1)
    report.llm_usd = float(spent or 0)
    return report


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.materials.ingest")
    parser.add_argument("folder")
    parser.add_argument("--dry-run", action="store_true", help="classify only, write nothing")
    parser.add_argument("--force", action="store_true", help="read already loaded files again")
    parser.add_argument("--only", help="regex on the path")
    parser.add_argument("--term-start", help="YYYY-MM-DD: the term (created if missing)")
    parser.add_argument("--term-end")
    parser.add_argument("--term-name")
    parser.add_argument("--upload-dir", help="default: UPLOAD_DIR")
    parser.add_argument("--alias", action="append", default=[], help='"BME 211=EE211"')
    parser.add_argument(
        "--create-courses", action="store_true", help="a syllabus of an unknown course creates it"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    for noisy in ("httpx", "httpx2", "pypdf", "app.llm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    report = asyncio.run(run(parse_args(argv)))
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
