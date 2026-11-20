"""Lecture notes (PDF or photo) -> pending material with a suggested course / week ->
save_material links and indexes them; one "Geri al" removes them."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import documents, intake
from app.agent.tools import materials as materials_tools
from app.config import Settings
from app.core.change_log import undo_change_set
from app.db.models import Course, CourseMaterial, MaterialChunk, SyllabusWeek
from app.llm.types import LLMRequest, LLMResponse
from app.rag import embed as embed_module
from tests.agent_fakes import NOW, ScriptedLLM, call, say
from tests.db.test_materials import WordEmbedder, stored_pdf
from tests.db.test_vision import last_user_text, stored_image, yaver_with_uploads

NOTES = [
    "EE211 Hafta 7 ders notu. Thevenin Norton eşdeğer devreleri.",
    "Thevenin eşdeğer devreleri: Thevenin direnci kaynaklar söndürülerek bulunur. "
    "Norton eşdeğer devreleri: akım kaynağı ve paralel direnç.",
]


@pytest.fixture(autouse=True)
def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(embed_module, "get_embedder", WordEmbedder)
    monkeypatch.setattr(intake, "MIN_SCORE", 0.1)  # bag-of-words scores are low
    monkeypatch.setattr(documents, "page_texts", lambda _: NOTES)
    monkeypatch.setattr(materials_tools, "page_texts", lambda _: NOTES)
    monkeypatch.setattr(
        materials_tools, "get_settings", lambda: Settings(_env_file=None, upload_dir=tmp_path)
    )


async def course_with_syllabus(session: AsyncSession) -> None:
    course = Course(code="EE211", name="Devre Teorisi I")
    session.add(course)
    await session.flush()
    for week, topics in [
        (6, "Süperpozisyon, kaynak dönüşümü"),
        (7, "Thevenin ve Norton eşdeğer devreleri"),
        (8, "Ara sınav"),
    ]:
        session.add(SyllabusWeek(course_id=course.id, week_no=week, topics=topics))
    await session.commit()


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_pdf_notes_are_suggested_then_saved(session: AsyncSession, tmp_path: Path) -> None:
    await course_with_syllabus(session)
    fake = ScriptedLLM()
    yaver = yaver_with_uploads(fake, tmp_path)
    attachment = await stored_pdf(session, tmp_path)
    seen: list[str] = []

    def ask(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("EE211 7. hafta notu olarak kaydedeyim mi?")

    fake.add(
        "document_reader",
        call("document_kind", kind="notes", course="EE211", summary="EE211 ders notu"),
    )
    fake.add("yaver", ask)
    first = await yaver.handle(session, "", now=NOW, attachment_ids=[attachment.id])

    assert "syllabus_parse" not in fake.purposes  # notes: no Sonnet call
    assert (
        "EE211 ders notu -> materyal #1, henüz kaydedilmedi; öneri: EE211, 7. hafta "
        "(syllabus: Thevenin ve Norton eşdeğer devreleri)]" in seen[0]
    )
    material = await session.get(CourseMaterial, 1)
    assert material is not None
    assert material.indexed_at is None  # pending
    assert await count(session, MaterialChunk) == 0

    fake.add(
        "yaver",
        call(
            "delegate", agent_id="academic", instruction="Materyal #1: EE211 7. hafta olarak kaydet"
        ),
        say("Atlas: notları kaydetti."),
    )
    fake.add(
        "academic",
        call("save_material", material_id=1, course="EE211", week=7),
        say("Kaydedildi."),
    )
    done = await yaver.handle(session, "evet", conversation_id=first.conversation_id, now=NOW)
    fake.assert_done()

    await session.refresh(material)
    saved = await session.get(CourseMaterial, 1)  # a new name: mypy narrowed the old one
    assert saved is not None
    assert saved.week_no == 7
    assert saved.indexed_at is not None
    chunks = (await session.scalars(select(MaterialChunk))).all()
    assert chunks
    assert {c.week_no for c in chunks} == {7}

    assert done.change_set_id is not None
    await undo_change_set(session, done.change_set_id, NOW)
    assert await count(session, CourseMaterial) == 0
    assert await count(session, MaterialChunk) == 0


async def test_photo_of_notes(session: AsyncSession, tmp_path: Path) -> None:
    await course_with_syllabus(session)
    fake = ScriptedLLM()
    yaver = yaver_with_uploads(fake, tmp_path)
    attachment = await stored_image(session, tmp_path)
    seen: list[str] = []

    def ask(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("Hangi derse kaydedeyim?")

    fake.add(
        "image_reader",
        call("image_contents", kind="document", summary="Ders notu sayfası"),
        call(
            "document_text",
            text=NOTES[1],
            course="EE211",
            lecture_notes=True,
        ),
    )
    fake.add("yaver", ask)
    await yaver.handle(session, "", now=NOW, attachment_ids=[attachment.id])

    assert (
        "[Görsel 1: ders notu -> materyal #1, henüz kaydedilmedi; öneri: EE211, 7. hafta" in seen[0]
    )
    assert NOTES[1] in seen[0]  # the text itself still goes to the team
    material = await session.get(CourseMaterial, 1)
    assert material is not None
    assert material.source_text == NOTES[1]

    from app.agent.tools import run_tool
    from tests.db.test_agent_tools import context

    ctx = context(session, "academic")
    result = await run_tool("save_material", {"material_id": 1, "course": "EE211", "week": 7}, ctx)
    assert result["material_saved"]["searchable_passages"] == 1
    found = await run_tool("search_materials", {"query": "Norton akım kaynağı"}, ctx)
    assert found["results"][0]["source"] == f"fotoğraf #{attachment.id}, s. 1"


async def test_no_course_no_suggestion(session: AsyncSession, tmp_path: Path) -> None:
    fake = ScriptedLLM()
    yaver = yaver_with_uploads(fake, tmp_path)
    attachment = await stored_pdf(session, tmp_path)
    seen: list[str] = []

    def ask(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("Hangi dersin notları?")

    fake.add("document_reader", call("document_kind", kind="notes", summary="Ders notu"))
    fake.add("yaver", ask)
    await yaver.handle(session, "", now=NOW, attachment_ids=[attachment.id])
    assert "-> materyal #1, henüz kaydedilmedi; ders ve hafta bilinmiyor, sorulacak]" in seen[0]
