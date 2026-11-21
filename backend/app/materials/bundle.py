"""A portable bundle of the course materials: made in dev, loaded into live.

    python -m app.materials.bundle export [/bundles/<name>] [--course "CSE 221" ...]
    python -m app.materials.bundle import /tmp/yaver-bundle [--dry-run]
    python -m app.materials.bundle undo <change_set_id>

A bundle is a folder: manifest.json (format, embedding model, counts, data.json.gz's SHA-256),
data.json.gz (courses, materials with their passages - embeddings as little-endian float32,
base64 - and tables of contents, weekly plans, books, course sources) and files/<sha256>.<ext>
(the PDFs / .docx). Nothing in it refers to a database id: courses go by code (and aliases),
materials by the SHA-256 of their file, so it loads into any database.

Import is idempotent and undoable: everything it writes is one change set in change_log (a
material it creates takes its passages and sections with it on undo; one it replaces logs
the old passages with their embeddings). A second import of the same bundle writes nothing.
The live side: scripts/import-materials-live.ps1 (backup first, then this inside the api).
"""

import argparse
import asyncio
import base64
import datetime as dt
import gzip
import hashlib
import json
import logging
import struct
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.core.change_log import NothingToUndoError, snapshot, undo_change_set
from app.db.models import (
    Attachment,
    ChangeLog,
    Course,
    CourseBook,
    CourseMaterial,
    CourseSource,
    MaterialChunk,
    MaterialSection,
    SourceItem,
    SyllabusWeek,
    Term,
)
from app.db.models.enums import ChangeOp
from app.db.models.materials import EMBEDDING_DIM
from app.db.session import get_sessionmaker
from app.materials.ingest import MIME, Courses, compact
from app.materials.sources import export_sources

logger = logging.getLogger("app.materials.bundle")

FORMAT = "yaver-materials"
VERSION = 1
REQUIRED_TABLES = (
    "course_materials",
    "material_chunks",
    "material_sections",
    "course_books",
    "course_sources",
    "source_items",
)


class BundleError(ValueError):
    """A bundle that cannot be loaded here (broken, other embedding model, old database)."""


# ---- encoding ---------------------------------------------------------------------------


def pack_vector(vector: Any) -> str:
    values = [float(x) for x in vector]
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode("ascii")


def unpack_vector(encoded: str) -> list[float]:
    raw = base64.b64decode(encoded)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def fingerprint(material: dict[str, Any]) -> str:
    """What makes two copies of a material the same (embeddings follow from the text)."""
    keys = ("course", "kind", "title", "pages", "week_no", "source_text")
    body = {k: material.get(k) for k in keys}
    body["chunks"] = [
        [c["week_no"], c["page_start"], c["page_end"], c["content"]] for c in material["chunks"]
    ]
    body["sections"] = [
        [s["number"], s["title"], s["page_start"], s["page_end"], s["week_nos"]]
        for s in material["sections"]
    ]
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---- export -----------------------------------------------------------------------------


async def material_dict(
    session: AsyncSession, material: CourseMaterial, code: str | None, sha: str | None
) -> dict[str, Any]:
    chunks = (
        await session.scalars(
            select(MaterialChunk)
            .where(MaterialChunk.material_id == material.id)
            .order_by(MaterialChunk.page_start, MaterialChunk.id)
        )
    ).all()
    sections = (
        await session.scalars(
            select(MaterialSection)
            .where(MaterialSection.material_id == material.id)
            .order_by(MaterialSection.page_start, MaterialSection.id)
        )
    ).all()
    return {
        "sha256": sha,
        "course": code,
        "kind": material.kind,
        "title": material.title,
        "pages": material.pages,
        "week_no": material.week_no,
        "source_text": material.source_text,
        "chunks": [
            {
                "week_no": c.week_no,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "content": c.content,
                "embedding": pack_vector(c.embedding),
            }
            for c in chunks
        ],
        "sections": [
            {
                "number": s.number,
                "title": s.title,
                "page_start": s.page_start,
                "page_end": s.page_end,
                "week_nos": list(s.week_nos or []),
            }
            for s in sections
        ],
    }


def _empty_folder(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise BundleError(f"{out} is not empty")
    (out / "files").mkdir(parents=True, exist_ok=True)


async def export_bundle(
    session: AsyncSession, out: Path, upload_dir: Path, only: list[str] | None = None
) -> dict[str, Any]:
    """Writes the bundle folder; returns its manifest."""
    await asyncio.to_thread(_empty_folder, out)
    wanted = Courses(list((await session.scalars(select(Course))).all()), {})
    courses = [c for c in wanted.courses if not only or any(wanted.by_code(o) is c for o in only)]
    by_id = {c.id: c for c in courses}
    data: dict[str, Any] = {
        "courses": [],
        "materials": [],
        "weeks": [],
        "books": [],
        "sources": [],
    }
    materials = (
        await session.execute(
            select(CourseMaterial, Attachment)
            .join(Attachment, Attachment.id == CourseMaterial.attachment_id)
            .where(CourseMaterial.course_id.in_(by_id))
            .order_by(CourseMaterial.id)
        )
    ).all()
    sha_of: dict[int, str] = {}
    used: set[int] = set()
    for material, attachment in materials:
        course_id = material.course_id or 0
        raw = await asyncio.to_thread((upload_dir / attachment.path).read_bytes)
        if _sha256(raw) != attachment.sha256:
            raise BundleError(f"{attachment.path}: the file does not match its SHA-256")
        extension = Path(attachment.path).suffix.lower()
        name = f"files/{attachment.sha256}{extension}"
        await asyncio.to_thread((out / name).write_bytes, raw)
        item = await material_dict(session, material, by_id[course_id].code, attachment.sha256)
        item["file"] = {
            "path": name,
            "filename": attachment.filename or material.title,
            "mime": attachment.mime,
            "size_bytes": attachment.size_bytes,
        }
        data["materials"].append(item)
        sha_of[material.id] = attachment.sha256
        used.add(course_id)
    for week in (
        await session.scalars(
            select(SyllabusWeek)
            .where(SyllabusWeek.course_id.in_(by_id))
            .order_by(SyllabusWeek.course_id, SyllabusWeek.week_no)
        )
    ).all():
        data["weeks"].append(
            {
                "course": by_id[week.course_id].code,
                "week_no": week.week_no,
                "topics": week.topics,
                "dates_text": week.dates_text,
                "readings": week.readings,
                "lab": week.lab,
                "assessment": week.assessment,
                "material": sha_of.get(week.material_id or 0),
            }
        )
        used.add(week.course_id)
    for book in (
        await session.scalars(
            select(CourseBook)
            .where(CourseBook.course_id.in_(by_id))
            .order_by(CourseBook.course_id, CourseBook.id)
        )
    ).all():
        data["books"].append(
            {
                "course": by_id[book.course_id].code,
                "title": book.title,
                "authors": book.authors,
                "edition": book.edition,
                "required": book.required,
                "material": sha_of.get(book.material_id or 0),
            }
        )
        used.add(book.course_id)
    data["sources"] = await export_sources(session, by_id, used)
    data["courses"] = [
        {"code": c.code, "name": c.name, "aliases": list(c.aliases or [])}
        for c in courses
        if c.id in used
    ]
    blob = gzip.compress(json.dumps(data, ensure_ascii=False).encode(), mtime=0)
    await asyncio.to_thread((out / "data.json.gz").write_bytes, blob)
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "embedding_model": get_settings().embedding_model,
        "embedding_dim": EMBEDDING_DIM,
        "data_sha256": _sha256(blob),
        "counts": {
            "courses": len(data["courses"]),
            "materials": len(data["materials"]),
            "passages": sum(len(m["chunks"]) for m in data["materials"]),
            "sections": sum(len(m["sections"]) for m in data["materials"]),
            "weeks": len(data["weeks"]),
            "books": len(data["books"]),
            "sources": len(data["sources"]),
        },
        "courses": [c["code"] for c in data["courses"]],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    return manifest


# ---- import -----------------------------------------------------------------------------


@dataclass
class Counts:
    new: int = 0
    updated: int = 0
    same: int = 0


@dataclass
class ImportReport:
    bundle: str
    dry_run: bool = False
    change_set_id: str | None = None
    courses_created: list[str] = field(default_factory=list)
    courses_updated: list[str] = field(default_factory=list)
    materials: Counts = field(default_factory=Counts)
    weeks: Counts = field(default_factory=Counts)
    books: Counts = field(default_factory=Counts)
    sources: Counts = field(default_factory=Counts)
    passages_written: int = 0
    files_written: int = 0
    notes: list[str] = field(default_factory=list)


class Log:
    """change_log entries of one import (one change set)."""

    def __init__(self, session: AsyncSession, change_set_id: uuid.UUID):
        self.session = session
        self.change_set_id = change_set_id
        self.count = 0

    def add(
        self,
        obj: Any,
        op: ChangeOp,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            ChangeLog(
                change_set_id=self.change_set_id,
                entity=obj.__tablename__,
                entity_id=obj.id,
                op=op,
                before_json=before,
                after_json=after,
                agent_id=None,
            )
        )
        self.count += 1

    async def created(self, obj: Any) -> None:
        await self.session.flush()
        self.add(obj, ChangeOp.CREATE, after=plain(obj))

    def updated(self, obj: Any, before: dict[str, Any]) -> None:
        self.add(obj, ChangeOp.UPDATE, before=before, after=plain(obj))

    async def deleted(self, obj: Any) -> None:
        self.add(obj, ChangeOp.DELETE, before=plain(obj))
        await self.session.delete(obj)


def plain(obj: Any) -> dict[str, Any]:
    """snapshot() that also stores an embedding (a numpy array from pgvector) as a list."""
    values = snapshot(obj)
    if "embedding" in values and values["embedding"] is not None:
        values["embedding"] = [float(x) for x in values["embedding"]]
    return values


def read_bundle(folder: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_file = folder / "manifest.json"
    if not manifest_file.is_file():
        raise BundleError(f"{folder}: no manifest.json")
    manifest = json.loads(manifest_file.read_text("utf-8"))
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise BundleError(f"not a {FORMAT} v{VERSION} bundle: {manifest.get('format')}")
    model = get_settings().embedding_model
    if manifest.get("embedding_model") != model or manifest.get("embedding_dim") != EMBEDDING_DIM:
        raise BundleError(
            f"embedding model differs: bundle {manifest.get('embedding_model')} "
            f"({manifest.get('embedding_dim')}), here {model} ({EMBEDDING_DIM})"
        )
    blob = (folder / "data.json.gz").read_bytes()
    if _sha256(blob) != manifest.get("data_sha256"):
        raise BundleError("data.json.gz does not match the manifest (copied in part?)")
    data = json.loads(gzip.decompress(blob))
    for material in data["materials"]:
        raw = (folder / material["file"]["path"]).read_bytes()
        if _sha256(raw) != material["sha256"]:
            raise BundleError(f"{material['file']['path']}: broken copy")
    return manifest, data


async def _check_schema(session: AsyncSession) -> None:
    for table in REQUIRED_TABLES:
        found = await session.scalar(text("select to_regclass(:t)"), {"t": table})
        if found is None:
            raise BundleError(
                f"table {table} is missing: this database is older than the bundle "
                "(deploy the release with the materials first)"
            )


async def _course(
    session: AsyncSession, log: Log, courses: Courses, item: dict[str, Any], report: ImportReport
) -> Course:
    course = courses.by_code(item["code"])
    for alias in item["aliases"]:
        course = course or courses.by_code(alias)
    if course is None:
        today = dt.datetime.now(get_settings().tz).date()
        term = await session.scalar(
            select(Term).where(Term.start_date <= today, Term.end_date >= today)
        )
        course = Course(
            code=item["code"],
            name=item["name"],
            aliases=list(item["aliases"]),
            term_id=term.id if term else None,
        )
        session.add(course)
        await log.created(course)
        courses.courses.append(course)
        report.courses_created.append(course.code)
        return course
    known = {compact(a) for a in [course.code, *(course.aliases or [])]}
    missing = [
        a for a in [item["code"], *item["aliases"]] if compact(a) not in known and len(a) <= 60
    ]
    if missing:
        before = plain(course)
        course.aliases = [*(course.aliases or []), *missing]
        await session.flush()
        log.updated(course, before)
        report.courses_updated.append(f"{course.code} (+{', '.join(missing)})")
    return course


def _store(upload_dir: Path, sha: str, extension: str, raw: bytes, now: dt.datetime) -> str:
    relative = f"{now:%Y/%m}/{sha}{extension}"
    target = upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(raw)
    return relative


async def _material(
    session: AsyncSession,
    log: Log,
    folder: Path,
    upload_dir: Path,
    course: Course,
    item: dict[str, Any],
    report: ImportReport,
    now: dt.datetime,
) -> CourseMaterial:
    """A material with a file: found by the file's SHA-256, else created with its file."""
    sha = item["sha256"]
    found = (
        await session.execute(
            select(CourseMaterial, Attachment)
            .join(Attachment, Attachment.id == CourseMaterial.attachment_id)
            .where(Attachment.sha256 == sha)
            .order_by(CourseMaterial.id)
        )
    ).first()
    if found is not None:
        return await write_material(session, log, course, item, report, now, found[0])
    attachment = await session.scalar(
        select(Attachment).where(Attachment.sha256 == sha).order_by(Attachment.id)
    )
    if attachment is None:
        raw = await asyncio.to_thread((folder / item["file"]["path"]).read_bytes)
        extension = Path(item["file"]["path"]).suffix.lower()
        path = (
            f"{now:%Y/%m}/{sha}{extension}"
            if report.dry_run
            else await asyncio.to_thread(_store, upload_dir, sha, extension, raw, now)
        )
        report.files_written += 0 if report.dry_run else 1
        attachment = Attachment(
            path=path,
            mime=item["file"]["mime"] or MIME.get(extension, "application/octet-stream"),
            width=0,
            height=0,
            size_bytes=item["file"]["size_bytes"],
            sha256=sha,
            filename=item["file"]["filename"],
        )
        session.add(attachment)
        await log.created(attachment)
    return await write_material(session, log, course, item, report, now, None, attachment.id)


async def write_material(
    session: AsyncSession,
    log: Log,
    course: Course,
    item: dict[str, Any],
    report: ImportReport,
    now: dt.datetime,
    existing: CourseMaterial | None,
    attachment_id: int | None = None,
) -> CourseMaterial:
    """`existing` the same (nothing written), repaired (old passages logged) or None
    (created; its passages and sections go with it on undo: ON DELETE CASCADE)."""
    item = {**item, "course": course.code}
    if existing is not None:
        material = existing
        current_course = (
            await session.get(Course, material.course_id) if material.course_id else None
        )
        current = await material_dict(
            session, material, current_course.code if current_course else None, None
        )
        if fingerprint(current) == fingerprint(item):
            report.materials.same += 1
            return material
        before = plain(material)
        material.course_id = course.id
        material.kind = item["kind"]
        material.title = item["title"]
        material.pages = item["pages"]
        material.week_no = item["week_no"]
        material.source_text = item["source_text"]
        material.indexed_at = now
        await session.flush()
        log.updated(material, before)
        for old in (
            await session.scalars(
                select(MaterialChunk).where(MaterialChunk.material_id == material.id)
            )
        ).all():
            await log.deleted(old)
        for old_section in (
            await session.scalars(
                select(MaterialSection).where(MaterialSection.material_id == material.id)
            )
        ).all():
            await log.deleted(old_section)
        await session.flush()
        report.materials.updated += 1
        logged = True
    else:
        material = CourseMaterial(
            course_id=course.id,
            attachment_id=attachment_id,
            kind=item["kind"],
            title=item["title"],
            pages=item["pages"],
            week_no=item["week_no"],
            source_text=item["source_text"],
            indexed_at=now,
        )
        session.add(material)
        await log.created(material)
        report.materials.new += 1
        logged = False
    added: list[Any] = []
    for chunk in item["chunks"]:
        vector = unpack_vector(chunk["embedding"])
        if len(vector) != EMBEDDING_DIM:
            raise BundleError(f"{item['title']}: an embedding of {len(vector)} numbers")
        added.append(
            MaterialChunk(
                material_id=material.id,
                course_id=course.id,
                week_no=chunk["week_no"],
                page_start=chunk["page_start"],
                page_end=chunk["page_end"],
                content=chunk["content"],
                embedding=vector,
            )
        )
    for section in item["sections"]:
        added.append(
            MaterialSection(
                material_id=material.id,
                course_id=course.id,
                number=section["number"],
                title=section["title"],
                page_start=section["page_start"],
                page_end=section["page_end"],
                week_nos=section["week_nos"],
            )
        )
    session.add_all(added)
    await session.flush()
    if logged:
        for obj in added:
            after = {"id": obj.id, "title": getattr(obj, "title", None) or item["title"]}
            log.add(obj, ChangeOp.CREATE, after=after)
    report.passages_written += len(item["chunks"])
    return material


async def _upsert(
    session: AsyncSession,
    log: Log,
    model: Any,
    where: dict[str, Any],
    values: dict[str, Any],
    counts: Counts,
) -> Any:
    row = await session.scalar(
        select(model).where(*(getattr(model, k) == v for k, v in where.items()))
    )
    if row is None:
        row = model(**where, **values)
        session.add(row)
        await log.created(row)
        counts.new += 1
        return row
    if all(getattr(row, k) == v for k, v in values.items()):
        counts.same += 1
        return row
    before = plain(row)
    for key, value in values.items():
        setattr(row, key, value)
    await session.flush()
    log.updated(row, before)
    counts.updated += 1
    return row


async def import_bundle(
    session: AsyncSession,
    folder: Path,
    upload_dir: Path,
    *,
    dry_run: bool = False,
    now: dt.datetime | None = None,
) -> ImportReport:
    """Loads a bundle in the caller's session and commits it (dry run: rolls back)."""
    manifest, data = await asyncio.to_thread(read_bundle, folder)
    await _check_schema(session)
    now = now or dt.datetime.now(dt.UTC)
    report = ImportReport(bundle=f"{folder.name} ({manifest['created_at']})", dry_run=dry_run)
    log = Log(session, uuid.uuid4())
    courses = Courses(list((await session.scalars(select(Course))).all()), {})
    by_code: dict[str, Course] = {}
    for item in data["courses"]:
        by_code[item["code"]] = await _course(session, log, courses, item, report)
    material_ids: dict[str, int] = {}
    for item in data["materials"]:
        material = await _material(
            session, log, folder, upload_dir, by_code[item["course"]], item, report, now
        )
        material_ids[item["sha256"]] = material.id
    for week in data["weeks"]:
        await _upsert(
            session,
            log,
            SyllabusWeek,
            {"course_id": by_code[week["course"]].id, "week_no": week["week_no"]},
            {
                "topics": week["topics"],
                "dates_text": week["dates_text"],
                "readings": week["readings"],
                "lab": week["lab"],
                "assessment": week["assessment"],
                "material_id": material_ids.get(week["material"] or ""),
            },
            report.weeks,
        )
    for book in data["books"]:
        await _upsert(
            session,
            log,
            CourseBook,
            {"course_id": by_code[book["course"]].id, "title": book["title"]},
            {
                "authors": book["authors"],
                "edition": book["edition"],
                "required": book["required"],
                "material_id": material_ids.get(book["material"] or ""),
            },
            report.books,
        )
    for source in data.get("sources", []):
        await _source(session, log, by_code[source["course"]], source, report, now)
    await session.flush()
    if log.count:
        report.change_set_id = str(log.change_set_id)
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return report


def _when(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


async def _source(
    session: AsyncSession,
    log: Log,
    course: Course,
    data: dict[str, Any],
    report: ImportReport,
    now: dt.datetime,
) -> None:
    """A course source by its url, its tabs by name, each tab's material through the tab."""
    source = await _upsert(
        session,
        log,
        CourseSource,
        {"url": data["url"]},
        {"course_id": course.id, "kind": data["kind"], "title": data["title"]},
        Counts(),
    )
    checked = _when(data["checked_at"])
    if checked and (source.checked_at is None or source.checked_at < checked):
        source.checked_at = checked  # the next daily check starts from the bundle's state
        source.changed_at = _when(data["changed_at"])
    for item in data["items"]:
        row = await session.scalar(
            select(SourceItem).where(
                SourceItem.source_id == source.id, SourceItem.key == item["key"]
            )
        )
        existing = (
            await session.get(CourseMaterial, row.material_id) if row and row.material_id else None
        )
        material = (
            await write_material(session, log, course, item["material"], report, now, existing)
            if item["material"]
            else None
        )
        await _upsert(
            session,
            log,
            SourceItem,
            {"source_id": source.id, "key": item["key"]},
            {
                "position": item["position"],
                "topic": item["topic"],
                "week_nos": item["week_nos"],
                "digest": item["digest"],
                "links": item["links"],
                "material_id": material.id if material else None,
                "changed_at": _when(item["changed_at"]),
                "removed_at": _when(item["removed_at"]),
            },
            report.sources,
        )


# ---- command line -------------------------------------------------------------------------


async def _main(args: argparse.Namespace, sessionmaker: async_sessionmaker[AsyncSession]) -> Any:
    settings = get_settings()
    async with sessionmaker() as session:
        if args.command == "export":
            stamp = dt.datetime.now(settings.tz).strftime("%Y%m%d-%H%M")
            out = Path(args.out or f"/bundles/materials-{stamp}")
            return {
                "folder": str(out),
                **await export_bundle(session, out, settings.upload_dir, args.course),
            }
        if args.command == "import":
            report = await import_bundle(
                session, Path(args.folder), settings.upload_dir, dry_run=args.dry_run
            )
            return asdict(report)
        try:
            entries = await undo_change_set(
                session, uuid.UUID(args.change_set_id), dt.datetime.now(dt.UTC)
            )
        except NothingToUndoError:
            return {"undone": 0, "note": "nothing to undo (already undone, or no such set)"}
        await session.commit()
        return {"undone": len(entries), "change_set_id": args.change_set_id}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.materials.bundle")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="dev database -> a bundle folder")
    export.add_argument("out", nargs="?", help="default /bundles/materials-YYYYMMDD-HHMM")
    export.add_argument("--course", action="append", help="only these courses (code or alias)")
    load = sub.add_parser("import", help="a bundle folder -> this database (idempotent)")
    load.add_argument("folder")
    load.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    undo = sub.add_parser("undo", help="undo an import by its change_set_id")
    undo.add_argument("change_set_id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    args = parse_args(argv)
    try:
        result = asyncio.run(_main(args, get_sessionmaker()))
    except BundleError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
