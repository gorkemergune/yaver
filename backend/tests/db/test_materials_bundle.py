"""The materials bundle (app.materials.bundle): what ingest wrote in one database is exported,
loaded into an empty one (courses by code, files by SHA-256, the same embeddings), loading it
again writes nothing, a changed copy is repaired, and every import is undone as one change set."""

import datetime as dt
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.change_log import undo_change_set
from app.db.models import (
    Attachment,
    Course,
    CourseBook,
    CourseMaterial,
    MaterialChunk,
    MaterialSection,
    SyllabusWeek,
)
from app.materials import bundle
from app.materials.ingest import parse_args, run
from tests.agent_fakes import ScriptedLLM
from tests.db.test_materials import fake_embeddings  # noqa: F401 - autouse fixture
from tests.db.test_materials_ingest import EE211, HUM, LAB_WEEKS, folder

TABLES = (MaterialChunk, MaterialSection, CourseMaterial, SyllabusWeek, CourseBook, Attachment)


async def counts(session: AsyncSession) -> dict[str, int]:
    found: dict[str, int] = {}
    for model in (Course, *TABLES):
        number = await session.scalar(select(func.count()).select_from(model))
        found[model.__tablename__] = number or 0
    return found


async def loaded(session: AsyncSession, tmp_path: Path) -> Path:
    """Ingest the example folder, export it; returns the bundle folder."""
    uploads = tmp_path / "uploads"
    root = folder(tmp_path)
    args = parse_args([str(root), "--term-start", "2026-09-28", "--create-courses"])
    args.upload_dir = str(uploads)
    sessionmaker = async_sessionmaker(session.bind, expire_on_commit=False)
    await run(
        args,
        sessionmaker=sessionmaker,
        llm=ScriptedLLM({"document_reader": [EE211, HUM, LAB_WEEKS]}),
    )
    out = tmp_path / "bundle"
    manifest = await bundle.export_bundle(session, out, uploads)
    assert manifest["counts"]["materials"] == 3
    assert sorted(manifest["courses"]) == ["EE 211", "HUM 103"]
    return out


async def wipe(session: AsyncSession) -> None:
    for model in TABLES:
        await session.execute(delete(model))
    await session.execute(delete(Course).where(Course.code == "HUM 103"))
    await session.commit()


async def test_export_import_again_and_undo(session: AsyncSession, tmp_path: Path) -> None:
    out = await loaded(session, tmp_path)
    full = await counts(session)
    vector = await session.scalar(select(MaterialChunk.embedding).order_by(MaterialChunk.id))
    await wipe(session)
    empty = await counts(session)
    uploads = tmp_path / "live-uploads"

    first = await bundle.import_bundle(session, out, uploads)

    assert await counts(session) == full
    assert first.courses_created == ["HUM 103"]  # EE 211 stayed: found by its code
    assert (first.materials.new, first.weeks.new, first.books.new) == (3, 4, 1)
    assert first.files_written == 3
    assert len(list(uploads.rglob("*.*"))) == 3
    again_vector = await session.scalar(select(MaterialChunk.embedding).order_by(MaterialChunk.id))
    assert vector is not None
    assert again_vector is not None
    assert [round(float(x), 5) for x in again_vector] == [round(float(x), 5) for x in vector]

    second = await bundle.import_bundle(session, out, uploads)
    assert second.change_set_id is None  # nothing written
    assert (second.materials.same, second.weeks.same, second.books.same) == (3, 4, 1)

    # a changed copy is repaired; undoing the repair brings the change back
    await session.execute(update(SyllabusWeek).values(topics="BOZUK"))
    await session.execute(
        delete(MaterialChunk).where(
            MaterialChunk.id == select(func.max(MaterialChunk.id)).scalar_subquery()
        )
    )
    await session.commit()
    repair = await bundle.import_bundle(session, out, uploads)
    assert (repair.materials.updated, repair.weeks.updated) == (1, 4)
    assert await counts(session) == full
    assert repair.change_set_id is not None
    await undo_change_set(session, uuid.UUID(repair.change_set_id), dt.datetime.now(dt.UTC))
    await session.commit()
    assert set((await session.scalars(select(SyllabusWeek.topics))).all()) == {"BOZUK"}
    assert (
        await session.scalar(select(func.count()).select_from(MaterialChunk))
        == full["material_chunks"] - 1
    )

    # undoing the first import leaves the database as it was before it
    assert first.change_set_id is not None
    await undo_change_set(session, uuid.UUID(first.change_set_id), dt.datetime.now(dt.UTC))
    await session.commit()
    assert await counts(session) == empty


async def test_dry_run_writes_nothing(session: AsyncSession, tmp_path: Path) -> None:
    out = await loaded(session, tmp_path)
    await wipe(session)
    before = await counts(session)
    report = await bundle.import_bundle(session, out, tmp_path / "up", dry_run=True)
    assert report.materials.new == 3
    assert report.files_written == 0
    assert await counts(session) == before
    assert not (tmp_path / "up").exists()


async def test_a_broken_or_foreign_bundle_is_refused(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = await loaded(session, tmp_path)
    file = next((out / "files").iterdir())
    raw = file.read_bytes()
    file.write_bytes(raw[:-10])
    with pytest.raises(bundle.BundleError, match="broken copy"):
        bundle.read_bundle(out)
    file.write_bytes(raw)

    manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    manifest["embedding_model"] = "some/other-model"
    (out / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(bundle.BundleError, match="embedding model differs"):
        bundle.read_bundle(out)


def test_vectors_survive_packing() -> None:
    vector = [0.1, -2.5, 3.25e-7, 0.0]
    assert bundle.unpack_vector(bundle.pack_vector(vector)) == pytest.approx(vector, rel=1e-6)
