"""Course sources: a public Google Sheets of shared notes, checked every day (Scholar's
`source_watch` shift job) - CSE 221's has one tab per topic (num1, compl., ... Map, comb1)
whose notes are mostly images.

    python -m app.materials.sources add "CSE 221" https://docs.google.com/spreadsheets/d/<id>
    python -m app.materials.sources check [--id N]
    python -m app.materials.sources list

A check downloads the whole workbook (/export?format=xlsx), reads it in code (zip + XML, no
extra dependency): per tab its cell text, its links and its images. A digest of those says
what is new or changed; only those tabs are read by the model (Sonnet, `source_notes`: the
images -> text) and mapped to the course's weeks (`material_map`), then saved as a searchable
material ("CSE 221 notları: Map"). Public PDFs a tab links to are added as materials too.
An unchanged source costs one download and no model call.
"""

import argparse
import asyncio
import datetime as dt
import hashlib
import io
import json
import logging
import posixpath
import re
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx2
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import json_schema
from app.config import get_settings
from app.db.models import (
    Attachment,
    Course,
    CourseMaterial,
    CourseSource,
    SourceItem,
    SyllabusWeek,
)
from app.db.session import get_sessionmaker
from app.llm.router import LLMUnavailableError
from app.llm.types import ChatMessage, ImagePart, LLMRequest, ToolSpec
from app.materials import mapping
from app.rag.pdf import is_pdf, page_texts
from app.rag.store import index_material
from app.services.images import ImageError, process_image

logger = logging.getLogger("app.materials.sources")

PURPOSE = "source_notes"  # smart (Sonnet): images of notes -> text
IMAGES_PER_CALL = 4  # longer answers came back with `pages` as one string
MAX_DOWNLOAD = 60 * 1024 * 1024
MAX_LINKED_PDF = 30 * 1024 * 1024
SHEET_ID = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{20,})")
DRIVE_FILE = re.compile(
    r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:.*&)?id=)([A-Za-z0-9_-]{20,})"
)
GOOGLE_DOC = re.compile(r"docs\.google\.com/(document|presentation)/d/([A-Za-z0-9_-]{20,})")
URL = re.compile(r"https?://[^\s\"'<>)]+")
HYPERLINK_FORMULA = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
R_ID = f"{{{NS['r']}}}id"
R_EMBED = f"{{{NS['r']}}}embed"


class SourceError(ValueError):
    """Not a source we can read (not a public Google Sheets, download failed, not xlsx)."""


# ---- the workbook -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SheetImage:
    name: str  # xl/media/image27.png
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(slots=True)
class Sheet:
    name: str
    position: int
    texts: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    images: list[SheetImage] = field(default_factory=list)

    @property
    def digest(self) -> str:
        body = json.dumps(
            [self.name, self.texts, self.links, [i.sha256 for i in self.images]],
            ensure_ascii=False,
        )
        return hashlib.sha256(body.encode()).hexdigest()


def export_url(url: str) -> str:
    match = SHEET_ID.search(url)
    if not match:
        raise SourceError(f"not a Google Sheets link: {url}")
    return f"https://docs.google.com/spreadsheets/d/{match[1]}/export?format=xlsx"


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """rId -> (absolute part path or external URL, target mode) of a part's relationships."""
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", f"{name}.rels")
    if rels_path not in archive.namelist():
        return {}
    root = ElementTree.fromstring(archive.read(rels_path))
    found = {}
    for rel in root.findall("pr:Relationship", NS):
        target, mode = rel.get("Target", ""), rel.get("TargetMode", "")
        if mode != "External":
            target = posixpath.normpath(posixpath.join(folder, target))
        found[rel.get("Id", "")] = (target, mode)
    return found


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in root.findall("m:si", NS)
    ]


def read_workbook(raw: bytes) -> list[Sheet]:
    """Tabs in order with their cell text (row by row), links and images (top to bottom)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise SourceError(f"not an xlsx file: {exc}") from exc
    strings = _shared_strings(archive)
    targets = _rels(archive, "xl/workbook.xml")
    sheets: list[Sheet] = []
    for position, node in enumerate(workbook.findall("m:sheets/m:sheet", NS)):
        sheet = Sheet(node.get("name", f"Sayfa {position + 1}"), position)
        part = targets.get(node.get(R_ID, ""), ("", ""))[0]
        if part in archive.namelist():
            _read_sheet(archive, part, strings, sheet)
        sheet.links = list(dict.fromkeys(sheet.links))
        sheets.append(sheet)
    return sheets


def _read_sheet(archive: zipfile.ZipFile, part: str, strings: list[str], sheet: Sheet) -> None:
    root = ElementTree.fromstring(archive.read(part))
    rels = _rels(archive, part)
    for row in root.iterfind("m:sheetData/m:row", NS):
        values = []
        for cell in row.findall("m:c", NS):
            kind = cell.get("t")
            value = cell.findtext("m:v", default="", namespaces=NS)
            if kind == "s" and value.isdigit() and int(value) < len(strings):
                value = strings[int(value)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter(f"{{{NS['m']}}}t"))
            formula = cell.findtext("m:f", default="", namespaces=NS)
            sheet.links += HYPERLINK_FORMULA.findall(formula)
            if value.strip():
                values.append(value.strip())
                sheet.links += URL.findall(value)
        if values:
            sheet.texts.append(" | ".join(values))
    for link in root.iterfind("m:hyperlinks/m:hyperlink", NS):
        target, mode = rels.get(link.get(R_ID, ""), ("", ""))
        if mode == "External" and target.startswith("http"):
            sheet.links.append(target)
    for drawing in root.iterfind("m:drawing", NS):
        part_drawing = rels.get(drawing.get(R_ID, ""), ("", ""))[0]
        if part_drawing in archive.namelist():
            _read_drawing(archive, part_drawing, sheet)


def _read_drawing(archive: zipfile.ZipFile, part: str, sheet: Sheet) -> None:
    root = ElementTree.fromstring(archive.read(part))
    rels = _rels(archive, part)
    placed: list[tuple[int, int, str]] = []
    for anchor in root:
        row = int(anchor.findtext("xdr:from/xdr:row", default="0", namespaces=NS) or 0)
        col = int(anchor.findtext("xdr:from/xdr:col", default="0", namespaces=NS) or 0)
        for blip in anchor.iter(f"{{{NS['a']}}}blip"):
            media = rels.get(blip.get(R_EMBED, ""), ("", ""))[0]
            if media in archive.namelist():
                placed.append((row, col, media))
        for click in anchor.iter(f"{{{NS['a']}}}hlinkClick"):
            target, mode = rels.get(click.get(R_ID, ""), ("", ""))
            if mode == "External" and target.startswith("http"):
                sheet.links.append(target)
    for _, _, media in sorted(placed):
        sheet.images.append(SheetImage(media, archive.read(media)))


async def download(url: str, client: httpx2.AsyncClient | None = None) -> bytes:
    own = client is None
    client = client or httpx2.AsyncClient(follow_redirects=True, timeout=60)
    try:
        response = await client.get(url)
        if response.status_code != 200:
            raise SourceError(f"download failed ({response.status_code}): {url}")
        if len(response.content) > MAX_DOWNLOAD:
            raise SourceError(f"too large ({len(response.content)} bytes): {url}")
        return response.content
    except httpx2.HTTPError as exc:
        raise SourceError(f"download failed: {exc}") from exc
    finally:
        if own:
            await client.aclose()


# ---- the model reads a tab -----------------------------------------------------------------


class NotePage(BaseModel):
    image: int = Field(ge=1, description="the image's number in this request")
    text: str = Field(description="everything the image says, as text / markdown")


class SheetNotes(BaseModel):
    topic: str = Field(description="what the tab is about, a few words, in the notes' language")
    # list | str: Sonnet sometimes writes a long array as a JSON string (read in code)
    pages: list[NotePage] | str = Field(default_factory=list)
    unclear: list[str] = Field(default_factory=list)


NOTES_TOOL = ToolSpec(
    "notes", "Return the tab's topic and each image as text.", json_schema(SheetNotes)
)
NOTES_PROMPT = (
    "You get the images of one tab of a course's shared notes (lecture notes, board photos, "
    "slides, solved examples) and the tab's name and cell text. Call `notes` once: topic = "
    "what the tab is about in a few words; for each image (numbered in the order given) its "
    "full content as text: definitions, rules, tables as markdown, every step of the worked "
    "examples, formulas in plain text (F = A'B + AB'). Keep the notes' language. Write only "
    "what is in the image; parts you cannot read go into unclear, never guess them."
)


@dataclass(slots=True)
class Transcript:
    topic: str
    pages: list[str]  # one per image (the cell text first, when there is any)
    unclear: list[str] = field(default_factory=list)


async def transcribe(llm: Any, course: str, sheet: Sheet, agent_id: str) -> Transcript:
    settings = get_settings()
    cells = "\n".join(sheet.texts)
    pages: list[str] = [f"[{sheet.name}] hücreler:\n{cells}"] if cells else []
    topic = ""
    unclear: list[str] = []
    images: list[ImagePart] = []
    for image in sheet.images:
        try:
            clean = process_image(
                image.data, max_bytes=20 * 1024 * 1024, max_edge=settings.image_max_edge
            )
        except ImageError as exc:
            unclear.append(f"{image.name}: {exc.code}")
            continue
        images.append(ImagePart(clean.mime, clean.data))
    for start in range(0, len(images), IMAGES_PER_CALL):
        batch = images[start : start + IMAGES_PER_CALL]
        response = await llm.complete(
            LLMRequest(
                system=NOTES_PROMPT,
                messages=[
                    ChatMessage(
                        "user",
                        f"Ders: {course}\nSekme: {sheet.name}\nHücreler: {cells or '-'}\n"
                        f"Görseller {start + 1}-{start + len(batch)} (bu istekte 1-{len(batch)}).",
                        images=batch,
                    )
                ],
                tools=[NOTES_TOOL],
                tool_choice="required",
                max_tokens=8192,
            ),
            purpose=PURPOSE,
            agent_id=agent_id,
        )
        call = next((c for c in response.tool_calls if c.name == NOTES_TOOL.name), None)
        if call is None or call.arguments is None:
            raise SourceError(f"{sheet.name}: the model did not call notes")
        notes = SheetNotes.model_validate(call.arguments)
        if isinstance(notes.pages, str):
            try:
                notes.pages = [NotePage.model_validate(p) for p in json.loads(notes.pages)]
            except (ValueError, TypeError) as exc:
                raise SourceError(f"{sheet.name}: pages unreadable") from exc
        topic = topic or notes.topic.strip()
        unclear += notes.unclear
        by_number = {p.image: p.text.strip() for p in notes.pages if isinstance(p, NotePage)}
        for number in range(1, len(batch) + 1):
            text = by_number.get(number, "")
            pages.append(f"[{sheet.name}] görsel {start + number}:\n{text}" if text else "")
    return Transcript(topic or sheet.name, pages, unclear)


# ---- a check ------------------------------------------------------------------------------


@dataclass
class CheckResult:
    source: str
    course: str
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0
    linked_files: list[str] = field(default_factory=list)
    weeks: dict[str, list[int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def news(self) -> bool:
        return bool(self.new or self.changed or self.linked_files)

    def message(self, first: bool) -> str | None:
        """For the user: "CSE 221'e yeni not: Map" (None: nothing new)."""
        if not self.news:
            return None
        if first:
            return f"{self.course} notları okundu: {len(self.new)} sekme ({', '.join(self.new)})."
        parts = []
        if self.new:
            parts.append(f"{self.course}'e yeni not: {', '.join(self.new)}")
        if self.changed:
            parts.append(f"{self.course} notlarında güncelleme: {', '.join(self.changed)}")
        if self.linked_files:
            parts.append(f"bağlantılı dosya eklendi: {', '.join(self.linked_files)}")
        return ". ".join(parts) + "."


async def _plan(session: AsyncSession, course_id: int) -> list[mapping.PlanWeek]:
    rows = (
        await session.scalars(
            select(SyllabusWeek)
            .where(SyllabusWeek.course_id == course_id)
            .order_by(SyllabusWeek.week_no)
        )
    ).all()
    return [mapping.PlanWeek(r.week_no, r.topics, r.readings, r.lab) for r in rows]


def material_title(source: CourseSource, sheet: str) -> str:
    return f"{source.title}: {sheet}"[:300]


async def check_source(
    session: AsyncSession,
    llm: Any,
    source: CourseSource,
    now: dt.datetime,
    *,
    raw: bytes | None = None,
    client: httpx2.AsyncClient | None = None,
    agent_id: str = "document_reader",
    upload_dir: Path | None = None,
) -> CheckResult:
    """Reads the source, writes what is new / changed (the caller commits)."""
    course = await session.get(Course, source.course_id)
    code = course.code if course else "?"
    result = CheckResult(source.title, code)
    try:
        raw = raw if raw is not None else await download(export_url(source.url), client)
        sheets = await asyncio.to_thread(read_workbook, raw)
    except SourceError as exc:
        source.checked_at, source.last_error = now, str(exc)
        result.error = str(exc)
        return result
    items = {
        i.key: i
        for i in (
            await session.scalars(select(SourceItem).where(SourceItem.source_id == source.id))
        ).all()
    }
    todo: list[tuple[Sheet, SourceItem | None, Transcript]] = []
    for sheet in sheets:
        item = items.get(sheet.name[:100])
        if item is not None and item.digest == sheet.digest and item.removed_at is None:
            result.unchanged += 1
            if item.position != sheet.position:
                item.position = sheet.position
            continue
        try:
            transcript = await transcribe(llm, code, sheet, agent_id)
        except (SourceError, LLMUnavailableError, ValidationError) as exc:
            # this tab waits for the next check; the others are saved
            logger.warning("source %s, tab %s: %s", source.title, sheet.name, exc)
            result.notes.append(f"{sheet.name}: okunamadı, sonraki kontrolde yeniden")
            continue
        todo.append((sheet, item, transcript))
        result.notes += [f"{sheet.name}: {u}" for u in transcript.unclear]
    plan = await _plan(session, source.course_id)
    entries = [
        mapping.Entry(None, f"{s.name} ({t.topic})", " ".join(" ".join(t.pages).split())[:1500])
        for s, _, t in todo
    ]
    weeks = await mapping.map_to_weeks(llm, code, plan, entries) if todo and plan else {}
    for index, (sheet, item, transcript) in enumerate(todo):
        week_nos = weeks.get(index, [])
        material = (
            await session.get(CourseMaterial, item.material_id)
            if item and item.material_id
            else None
        )
        if material is None:
            material = CourseMaterial(
                course_id=source.course_id,
                kind="notes",
                title=material_title(source, sheet.name),
                pages=max(1, len(transcript.pages)),
                week_no=None,
            )
            session.add(material)
            await session.flush()
        material.title = material_title(source, sheet.name)
        material.pages = max(1, len(transcript.pages))
        material.week_no = week_nos[0] if len(week_nos) == 1 else None
        material.source_text = "\n\n".join(p for p in transcript.pages if p)
        await index_material(session, material, transcript.pages, now)
        if item is None:
            item = SourceItem(source_id=source.id, key=sheet.name[:100], digest=sheet.digest)
            session.add(item)
            result.new.append(sheet.name)
        else:
            result.changed.append(sheet.name)
        item.position = sheet.position
        item.topic = transcript.topic[:300]
        item.week_nos = week_nos
        item.digest = sheet.digest
        item.links = sheet.links
        item.material_id = material.id
        item.changed_at = now
        item.removed_at = None
        result.weeks[sheet.name] = week_nos
        for link in sheet.links:
            title = await _linked_file(
                session,
                source,
                link,
                week_nos,
                now,
                client,
                upload_dir or get_settings().upload_dir,
            )
            if title:
                result.linked_files.append(title)
    present = {s.name[:100] for s in sheets}
    for key, item in items.items():
        if key not in present and item.removed_at is None:
            item.removed_at = now
            result.removed.append(key)
    source.checked_at, source.last_error = now, None
    if result.news or result.removed:
        source.changed_at = now
    await session.flush()
    return result


def download_url(link: str) -> str | None:
    """A public file's direct download address (Drive file, Google Doc as PDF, a .pdf)."""
    if match := DRIVE_FILE.search(link):
        return f"https://drive.google.com/uc?export=download&id={match[1]}"
    if match := GOOGLE_DOC.search(link):
        return f"https://docs.google.com/{match[1]}/d/{match[2]}/export?format=pdf"
    if link.lower().split("?")[0].endswith(".pdf"):
        return link
    return None


async def _linked_file(
    session: AsyncSession,
    source: CourseSource,
    link: str,
    week_nos: list[int],
    now: dt.datetime,
    client: httpx2.AsyncClient | None,
    upload_dir: Path,
) -> str | None:
    """A public PDF a tab links to -> a material (once: by its SHA-256). Its title or None."""
    url = download_url(link)
    if url is None:
        return None
    try:
        raw = await download(url, client)
    except SourceError as exc:
        logger.info("linked file %s: %s", link, exc)
        return None
    if not is_pdf(raw) or len(raw) > MAX_LINKED_PDF:
        return None  # a sign-in page or something else: not public
    digest = hashlib.sha256(raw).hexdigest()
    if await session.scalar(select(Attachment.id).where(Attachment.sha256 == digest)):
        return None
    from app.api.uploads import store_pdf

    path = await asyncio.to_thread(store_pdf, raw, upload_dir, now)
    pages = await asyncio.to_thread(page_texts, raw)
    name = f"{source.title} - bağlantı {digest[:8]}.pdf"
    attachment = Attachment(
        path=path,
        mime="application/pdf",
        width=0,
        height=0,
        size_bytes=len(raw),
        sha256=digest,
        filename=name,
    )
    session.add(attachment)
    await session.flush()
    material = CourseMaterial(
        course_id=source.course_id,
        attachment_id=attachment.id,
        kind="notes",
        title=name,
        pages=len(pages),
        week_no=week_nos[0] if len(week_nos) == 1 else None,
    )
    session.add(material)
    await session.flush()
    await index_material(session, material, pages, now)
    return name


# ---- bundle (app.materials.bundle) ----------------------------------------------------------


async def export_sources(
    session: AsyncSession, by_id: dict[int, Course], used: set[int]
) -> list[dict[str, Any]]:
    from app.materials.bundle import material_dict

    found = []
    sources = (
        await session.scalars(
            select(CourseSource).where(CourseSource.course_id.in_(by_id)).order_by(CourseSource.id)
        )
    ).all()
    for source in sources:
        code = by_id[source.course_id].code
        items = []
        for item in (
            await session.scalars(
                select(SourceItem)
                .where(SourceItem.source_id == source.id)
                .order_by(SourceItem.position)
            )
        ).all():
            material = (
                await session.get(CourseMaterial, item.material_id) if item.material_id else None
            )
            items.append(
                {
                    "key": item.key,
                    "position": item.position,
                    "topic": item.topic,
                    "week_nos": list(item.week_nos or []),
                    "digest": item.digest,
                    "links": list(item.links or []),
                    "changed_at": item.changed_at.isoformat() if item.changed_at else None,
                    "removed_at": item.removed_at.isoformat() if item.removed_at else None,
                    "material": await material_dict(session, material, code, None)
                    if material
                    else None,
                }
            )
        found.append(
            {
                "course": code,
                "kind": source.kind,
                "url": source.url,
                "title": source.title,
                "checked_at": source.checked_at.isoformat() if source.checked_at else None,
                "changed_at": source.changed_at.isoformat() if source.changed_at else None,
                "items": items,
            }
        )
        used.add(source.course_id)
    return found


# ---- command line --------------------------------------------------------------------------


async def _main(args: argparse.Namespace) -> Any:
    from app.llm.router import get_router
    from app.materials.ingest import Courses

    async with get_sessionmaker()() as session:
        if args.command == "add":
            courses = Courses(list((await session.scalars(select(Course))).all()), {})
            course = courses.by_code(args.course)
            if course is None:
                raise SourceError(f"no course {args.course}")
            export_url(args.url)  # a Google Sheets link
            existing = await session.scalar(
                select(CourseSource).where(CourseSource.url == args.url)
            )
            if existing is not None:
                return {"source": existing.id, "note": "already there"}
            source = CourseSource(
                course_id=course.id, url=args.url, title=args.title or f"{course.code} notları"
            )
            session.add(source)
            await session.commit()
            return {"source": source.id, "course": course.code, "title": source.title}
        if args.command == "list":
            rows = (await session.scalars(select(CourseSource).order_by(CourseSource.id))).all()
            return [
                {
                    "id": s.id,
                    "title": s.title,
                    "url": s.url,
                    "checked_at": s.checked_at,
                    "error": s.last_error,
                }
                for s in rows
            ]
        query = select(CourseSource).order_by(CourseSource.id)
        if args.id:
            query = query.where(CourseSource.id == args.id)
        results = []
        llm = get_router()
        for source in (await session.scalars(query)).all():
            first = source.checked_at is None
            result = await check_source(session, llm, source, dt.datetime.now(dt.UTC))
            await session.commit()
            results.append({**asdict(result), "message": result.message(first)})
        return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.materials.sources")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="a course's public Google Sheets")
    add.add_argument("course")
    add.add_argument("url")
    add.add_argument("--title", help='default "<code> notları"')
    check = sub.add_parser("check", help="read new / changed tabs now")
    check.add_argument("--id", type=int)
    sub.add_parser("list")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    for noisy in ("httpx", "httpx2", "app.llm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        result = asyncio.run(_main(parse_args(argv)))
    except SourceError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
