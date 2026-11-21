"""Course sources (app.materials.sources): a public Google Sheets of notes is read in code
(tabs, cell text, links, images), only new / changed tabs go to the model, each tab becomes a
searchable material mapped to the syllabus weeks, Scholar's daily `source_watch` tells the
user "CSE 221'e yeni not: Map", and the bundle carries it all to another database."""

import datetime as dt
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx2
import pytest
from PIL import Image
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    Course,
    CourseMaterial,
    CourseSource,
    Message,
    SourceItem,
    SyllabusWeek,
)
from app.materials import bundle, sources
from app.office.shift_jobs import run_shift_job
from app.office.state import Office
from app.rag.store import search
from tests.agent_fakes import NOW, ScriptedLLM, call
from tests.db.test_materials import fake_embeddings  # noqa: F401 - autouse fixture
from tests.db.test_shift_jobs import example_config, notes_of, office  # noqa: F401

URL = "https://docs.google.com/spreadsheets/d/1RgGYfPer3ndvdf7BJ6HaCVuNnpUTvTm2Qfsi7Ke_dzk"
DRIVE = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"
M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def png(color: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(out, format="PNG")
    return out.getvalue()


def rels(*items: tuple[str, str, bool]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Target="{target}"'
        + (' TargetMode="External"' if external else "")
        + "/>"
        for rid, target, external in items
    )
    return f'<Relationships xmlns="{P}">{body}</Relationships>'


def drawing(rows: list[int]) -> str:
    anchors = "".join(
        f"<xdr:oneCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:row>{row}</xdr:row></xdr:from>"
        f'<xdr:pic><xdr:blipFill><a:blip r:embed="rId{i + 1}"/></xdr:blipFill></xdr:pic>'
        "</xdr:oneCellAnchor>"
        for i, row in enumerate(rows)
    )
    return f'<xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}" xmlns:r="{R}">{anchors}</xdr:wsDr>'


def workbook(map_color: str = "blue", with_codes: bool = True) -> bytes:
    """num1 / codes (cells + links + two images) / Map (one image)."""
    tabs = [("num1", 1), ("Map", 2)] + ([("codes", 3)] if with_codes else [])
    files: dict[str, str | bytes] = {
        "xl/workbook.xml": f'<workbook xmlns="{M}" xmlns:r="{R}"><sheets>'
        + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for n, i in tabs)
        + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": rels(
            *((f"rId{i}", f"worksheets/sheet{i}.xml", False) for _, i in tabs)
        ),
        "xl/sharedStrings.xml": f'<sst xmlns="{M}"><si><t>decimal codes</t></si>'
        "<si><t>bcd</t></si></sst>",
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{M}" xmlns:r="{R}"><sheetData/>'
        '<drawing r:id="rId1"/></worksheet>',
        "xl/worksheets/_rels/sheet1.xml.rels": rels(("rId1", "../drawings/drawing1.xml", False)),
        "xl/drawings/drawing1.xml": drawing([9, 1]),  # the lower image is the second
        "xl/drawings/_rels/drawing1.xml.rels": rels(
            ("rId1", "../media/image1.png", False), ("rId2", "../media/image2.png", False)
        ),
        "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{M}" xmlns:r="{R}"><sheetData/>'
        '<drawing r:id="rId1"/></worksheet>',
        "xl/worksheets/_rels/sheet2.xml.rels": rels(("rId1", "../drawings/drawing2.xml", False)),
        "xl/drawings/drawing2.xml": drawing([0]),
        "xl/drawings/_rels/drawing2.xml.rels": rels(("rId1", "../media/image3.png", False)),
        "xl/worksheets/sheet3.xml": f'<worksheet xmlns="{M}" xmlns:r="{R}"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="str"><f>HYPERLINK("https://example.com/kod.pdf","pdf")</f>'
        "<v>pdf</v></c></row></sheetData>"
        f'<hyperlinks><hyperlink ref="A3" r:id="rId1"/></hyperlinks></worksheet>',
        "xl/worksheets/_rels/sheet3.xml.rels": rels(("rId1", DRIVE, True)),
        "xl/media/image1.png": png("red"),
        "xl/media/image2.png": png("green"),
        "xl/media/image3.png": png(map_color),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def notes(topic: str, *texts: str) -> Any:
    return call(
        "notes", topic=topic, pages=[{"image": i, "text": t} for i, t in enumerate(texts, 1)]
    )


def test_the_workbook_is_read_in_code() -> None:
    tabs = sources.read_workbook(workbook())
    assert [t.name for t in tabs] == ["num1", "Map", "codes"]
    num1, map_tab, codes = tabs
    assert [i.name for i in num1.images] == ["xl/media/image2.png", "xl/media/image1.png"]
    assert codes.texts == ["decimal codes | bcd", "pdf"]
    assert codes.links == ["https://example.com/kod.pdf", DRIVE]
    assert len(map_tab.images) == 1
    assert sources.read_workbook(workbook("purple"))[1].digest != map_tab.digest
    assert sources.read_workbook(workbook())[0].digest == num1.digest
    with pytest.raises(sources.SourceError):
        sources.read_workbook(b"not a zip")


def test_links_and_addresses() -> None:
    assert sources.export_url(URL + "/edit#gid=0").endswith("/export?format=xlsx")
    with pytest.raises(sources.SourceError):
        sources.export_url("https://example.com/sheet")
    assert sources.download_url(DRIVE) == (
        "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
    )
    assert sources.download_url("https://example.com/kod.pdf?x=1") == (
        "https://example.com/kod.pdf?x=1"
    )
    assert sources.download_url("https://example.com/page") is None


async def course_with_plan(session: AsyncSession) -> CourseSource:
    course = Course(code="CSE 221", name="Logic Design")
    session.add(course)
    await session.flush()
    for week, topics in ((1, "Number Systems"), (2, "Number Codes"), (4, "Karnaugh Maps")):
        session.add(SyllabusWeek(course_id=course.id, week_no=week, topics=topics))
    source = CourseSource(course_id=course.id, url=URL, title="CSE 221 notları")
    session.add(source)
    await session.commit()
    return source


def links_client(pdf: bytes) -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "drive.google.com" in str(request.url):
            return httpx2.Response(200, content=pdf)
        return httpx2.Response(200, content=b"<html>Sign in</html>")  # not public

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def first_run() -> dict[str, list[Any]]:
    return {
        "academic": [
            notes("Sayı sistemleri", "ikili sayılar", "sekizlik"),
            notes("Karnaugh haritası", "K-map gruplama: komşu hücreler ikişer, dörder gruplanır"),
        ],  # codes has no image: no call
        "document_reader": [
            call(
                "map_weeks",
                entries=[
                    {"index": 0, "weeks": [1]},
                    {"index": 1, "weeks": [4]},
                    {"index": 2, "weeks": [2]},
                ],
            )
        ],
    }


async def test_new_unchanged_changed_and_removed_tabs(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await course_with_plan(session)
    raw_pdf = (
        Path(__file__).parents[3] / "examples" / "syllabus" / "ee211_hafta7_notlar.pdf"
    ).read_bytes()
    llm = ScriptedLLM(first_run())

    first = await sources.check_source(
        session,
        llm,
        source,
        NOW,
        raw=workbook(),
        client=links_client(raw_pdf),
        agent_id="academic",
        upload_dir=tmp_path,
    )
    await session.commit()

    llm.assert_done()
    assert first.new == ["num1", "Map", "codes"]
    assert first.weeks == {"num1": [1], "Map": [4], "codes": [2]}
    short = hashlib.sha256(raw_pdf).hexdigest()[:8]
    assert first.linked_files == [f"CSE 221 notları - bağlantı {short}.pdf"]
    assert first.message(True) == "CSE 221 notları okundu: 3 sekme (num1, Map, codes)."
    item = await session.scalar(select(SourceItem).where(SourceItem.key == "Map"))
    assert item is not None
    assert (item.topic, item.week_nos) == ("Karnaugh haritası", [4])
    material = await session.get(CourseMaterial, item.material_id)
    assert material is not None
    assert (material.title, material.week_no, material.kind) == ("CSE 221 notları: Map", 4, "notes")
    assert "K-map gruplama" in (material.source_text or "")
    hits = await search(session, "K-map gruplama")
    assert any(h.title == "CSE 221 notları: Map" for h in hits)

    # the same workbook: one download, no model
    same = await sources.check_source(session, ScriptedLLM(), source, NOW, raw=workbook())
    assert (same.new, same.changed, same.unchanged, same.message(False)) == ([], [], 3, None)

    # Map's image changed, codes removed: only Map is read again
    again = ScriptedLLM(
        {
            "document_reader": [
                # pages as one JSON string (Sonnet does that for long arrays): read in code
                call(
                    "notes",
                    topic="Karnaugh haritası",
                    pages=json.dumps([{"image": 1, "text": "don't care"}]),
                ),
                call("map_weeks", entries=[{"index": 0, "weeks": [4]}]),
            ]
        }
    )
    changed = await sources.check_source(
        session, again, source, NOW + dt.timedelta(days=1), raw=workbook("purple", with_codes=False)
    )
    await session.commit()
    again.assert_done()
    assert (changed.changed, changed.removed, changed.unchanged) == (["Map"], ["codes"], 1)
    assert changed.message(False) == "CSE 221 notlarında güncelleme: Map."
    await session.refresh(material)
    assert "don't care" in (material.source_text or "")
    removed = await session.scalar(select(SourceItem).where(SourceItem.key == "codes"))
    assert removed is not None
    assert removed.removed_at is not None


async def test_a_tab_the_model_cannot_read_waits_for_the_next_check(
    session: AsyncSession, tmp_path: Path
) -> None:
    source = await course_with_plan(session)
    llm = ScriptedLLM(
        {
            "academic": [
                notes("Sayı sistemleri", "ikili", "sekizlik"),
                call("notes", topic="x", pages="not json"),
            ],
            "document_reader": [
                call("map_weeks", entries=[{"index": 0, "weeks": [1]}, {"index": 1, "weeks": [2]}])
            ],
        }
    )
    result = await sources.check_source(
        session,
        llm,
        source,
        NOW,
        raw=workbook(),
        client=links_client(b"no"),
        agent_id="academic",
        upload_dir=tmp_path,
    )
    await session.commit()
    assert result.new == ["num1", "codes"]
    assert "Map: okunamadı, sonraki kontrolde yeniden" in result.notes
    assert await session.scalar(select(SourceItem).where(SourceItem.key == "Map")) is None


async def test_scholars_shift_tells_the_user(
    session: AsyncSession,
    office: Office,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = await course_with_plan(session)
    source.checked_at = NOW - dt.timedelta(days=1)  # not the first check
    await session.commit()

    async def fake_download(url: str, client: object = None) -> bytes:
        assert url.endswith("/export?format=xlsx")
        return workbook(with_codes=False)

    monkeypatch.setattr(sources, "download", fake_download)
    llm = ScriptedLLM({"academic": first_run()["academic"][:2]})
    llm.scripts["document_reader"] = [
        call("map_weeks", entries=[{"index": 0, "weeks": [1]}, {"index": 1, "weeks": [4]}])
    ]

    text = await run_shift_job(
        "shift:academic:source_watch",
        now=NOW,
        settings=Settings(_env_file=None),
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        config=example_config(),
        office=office,
        llm=llm,
    )

    assert text == "CSE 221'e yeni not: num1, Map."
    assert await notes_of(session, "academic") == [text]
    message = await session.scalar(select(Message).order_by(Message.id.desc()))
    assert message is not None
    assert (message.agent_id, message.content, message.kind) == ("academic", text, "source_watch")


async def test_the_bundle_carries_the_source(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await course_with_plan(session)
    await sources.check_source(
        session,
        ScriptedLLM(first_run()),
        source,
        NOW,
        raw=workbook(),
        client=links_client(b"no"),
        agent_id="academic",
        upload_dir=tmp_path / "uploads",
    )
    await session.commit()
    out = tmp_path / "bundle"
    manifest = await bundle.export_bundle(session, out, tmp_path / "uploads")
    assert manifest["counts"]["sources"] == 1

    for model in (SourceItem, CourseSource, CourseMaterial, SyllabusWeek):
        await session.execute(delete(model))
    await session.commit()

    report = await bundle.import_bundle(session, out, tmp_path / "live-uploads")
    assert (report.sources.new, report.materials.new) == (3, 3)
    restored = await session.scalar(select(CourseSource))
    assert restored is not None
    assert restored.checked_at == NOW  # the daily check goes on from here
    items = (await session.scalars(select(SourceItem).order_by(SourceItem.position))).all()
    assert [(i.key, i.week_nos) for i in items] == [("num1", [1]), ("Map", [4]), ("codes", [2])]
    assert all(i.material_id for i in items)
    assert await session.scalar(select(func.count()).select_from(CourseMaterial)) == 3

    again = await bundle.import_bundle(session, out, tmp_path / "live-uploads")
    assert again.change_set_id is None
