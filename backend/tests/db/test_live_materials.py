"""Live: a syllabus PDF (examples/syllabus, made-up course) read by Sonnet, saved after
"evet" with real local embeddings, then a question answered from it.

docker compose exec api pytest -m live -k materials -s
"""

import datetime as dt
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import Coordinator
from app.agent.team import get_team
from app.agent.tools import materials as materials_tools
from app.api.uploads import store_pdf
from app.config import Settings, get_settings
from app.db.models import Attachment, LlmUsage, MaterialChunk, Proposal, SyllabusWeek
from app.db.models.enums import ProposalKind
from app.db.models.study import StudySheet
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore

pytestmark = pytest.mark.live

PDF = Path(__file__).resolve().parents[3] / "examples" / "syllabus" / "ee211_syllabus.pdf"
NOW = dt.datetime(2026, 11, 23, 7, 0, tzinfo=dt.UTC)  # Monday 10:00 Istanbul


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    if not env_value(get_settings(), "ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    if not PDF.is_file():
        pytest.skip("examples/ not mounted")
    router = build_router(store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


async def test_syllabus_pdf_end_to_end(
    session: AsyncSession, router: LLMRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(upload_dir=tmp_path, app_password=None)
    monkeypatch.setattr(materials_tools, "get_settings", lambda: settings)
    yaver = Coordinator(router, get_team(), settings)
    raw = PDF.read_bytes()
    attachment = Attachment(
        path=store_pdf(raw, tmp_path, NOW),
        mime="application/pdf",
        width=0,
        height=0,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        filename="ee211_syllabus.pdf",
    )
    session.add(attachment)
    await session.commit()

    first = await yaver.handle(
        session, "EE211'in syllabus'u", now=NOW, attachment_ids=[attachment.id]
    )
    print(f"\n1> {first.reply}")
    proposal = await session.scalar(select(Proposal))
    assert proposal is not None
    assert proposal.kind is ProposalKind.SYLLABUS
    weeks = {e["week_no"]: e["topics"] for e in proposal.entries}
    print(f"   weeks: {len(weeks)}; 7 = {weeks.get(7)!r}")
    assert len(weeks) >= 12
    assert "thevenin" in weeks[7].lower()
    assert await session.scalar(select(func.count()).select_from(SyllabusWeek)) == 0

    second = await yaver.handle(session, "evet", conversation_id=first.conversation_id, now=NOW)
    print(f"2> {second.reply}")
    saved = await session.scalar(select(func.count()).select_from(SyllabusWeek))
    chunks = await session.scalar(select(func.count()).select_from(MaterialChunk))
    print(f"   saved weeks: {saved}, passages: {chunks}")
    assert saved == len(weeks)
    assert chunks is not None
    assert chunks >= 2

    third = await yaver.handle(
        session,
        "EE211'de Thevenin direnci nasıl bulunuyordu, notlarda ne yazıyor?",
        conversation_id=first.conversation_id,
        now=NOW,
    )
    print(f"3> {third.reply}")
    for agent in third.agents:
        print(f"   [{agent['name']}] {agent['reply']}")
    tools = [step["tool"] for step in third.trace]
    print(f"   tools: {tools}")
    assert "search_materials" in tools
    assert "söndür" in third.reply.lower() or "kaynak" in third.reply.lower()
    assert "ee211_syllabus.pdf" in third.reply  # the source is cited

    fourth = await yaver.handle(
        session,
        "EE211 7. hafta için çalışma kağıdı hazırla",
        conversation_id=first.conversation_id,
        now=NOW,
    )
    print(f"4> {fourth.reply}")
    sheet = await session.scalar(select(StudySheet))
    assert sheet is not None
    print(f"   sheet: {sheet.title!r}, {len(sheet.content_md)} chars, sources {sheet.sources}")
    print(sheet.content_md[:1500])
    assert "## Kaynaklar" in sheet.content_md
    assert "ee211_syllabus.pdf, s. " in sheet.content_md
    assert "#/sheet?id=" in fourth.reply  # the link reaches the user

    rows = (await session.scalars(select(LlmUsage).order_by(LlmUsage.id))).all()
    total = sum(r.cost_usd for r in rows)
    for row in rows:
        print(f"   {row.purpose:<18} {row.tier:<9} {row.provider}/{row.model} ${row.cost_usd}")
    print(f"   total ${total}")


NOTES_PDF = PDF.with_name("ee211_hafta7_notlar.pdf")


async def test_lecture_notes_pdf_named_by_the_user(
    session: AsyncSession, router: LLMRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import Course, CourseMaterial

    settings = Settings(upload_dir=tmp_path, app_password=None)
    monkeypatch.setattr(materials_tools, "get_settings", lambda: settings)
    yaver = Coordinator(router, get_team(), settings)
    session.add(Course(code="EE211", name="Devre Teorisi I"))
    raw = NOTES_PDF.read_bytes()
    attachment = Attachment(
        path=store_pdf(raw, tmp_path, NOW),
        mime="application/pdf",
        width=0,
        height=0,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        filename="ee211_hafta7_notlar.pdf",
    )
    session.add(attachment)
    await session.commit()

    first = await yaver.handle(
        session, "EE211 7. hafta ders notlarım", now=NOW, attachment_ids=[attachment.id]
    )
    print(f"\n1> {first.reply}")
    material = await session.scalar(select(CourseMaterial))
    assert material is not None
    print(f"   material: week {material.week_no}, indexed {material.indexed_at is not None}")
    if material.indexed_at is None:  # it asked instead of saving: confirm
        second = await yaver.handle(session, "evet", conversation_id=first.conversation_id, now=NOW)
        print(f"2> {second.reply}")
        await session.refresh(material)
    assert material.indexed_at is not None
    assert material.week_no == 7

    third = await yaver.handle(
        session,
        "Norton akımı nasıl bulunuyor, maksimum güç ne zaman oluyor?",
        conversation_id=first.conversation_id,
        now=NOW,
    )
    print(f"3> {third.reply}")
    assert "ee211_hafta7_notlar.pdf" in third.reply
    assert "R_L = R_Th" in third.reply or "R_Th" in third.reply
    rows = (await session.scalars(select(LlmUsage).order_by(LlmUsage.id))).all()
    print(f"   total ${sum(r.cost_usd for r in rows)}")
