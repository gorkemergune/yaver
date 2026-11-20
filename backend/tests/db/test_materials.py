"""Course materials: a syllabus PDF read in code, proposed as a table, saved after "evet"
with searchable passages (fake embeddings here), then found by search_materials."""

import hashlib
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.api.uploads import store_pdf
from app.core.change_log import undo_change_set
from app.db.models import (
    Attachment,
    Course,
    CourseMaterial,
    MaterialChunk,
    Proposal,
    SyllabusWeek,
)
from app.db.models.enums import ProposalKind, ProposalStatus
from app.llm.types import LLMRequest, LLMResponse
from app.rag import embed as embed_module
from app.rag.chunk import chunk_pages
from app.rag.pdf import is_pdf, page_texts
from tests.agent_fakes import NOW, ScriptedLLM, call, say
from tests.db.test_agent_tools import context
from tests.db.test_api_web import client, llm  # noqa: F401 - fixtures
from tests.db.test_vision import last_user_text, yaver_with_uploads

REPO = Path(__file__).resolve().parents[3]
SYLLABUS_PDF = REPO / "examples" / "syllabus" / "ee211_syllabus.pdf"
WEEKS = [
    {"week_no": 1, "topics": "Temel kavramlar: akım, gerilim, güç"},
    {"week_no": 7, "topics": "Thevenin ve Norton eşdeğer devreleri"},
    {"week_no": 8, "topics": "Ara sınav"},
]


class WordEmbedder:
    """Bag of words hashed into 384 dims: shared words = close vectors (no model download)."""

    dim = 384

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vector = [0.0] * self.dim
            for word in re.findall(r"\w+", text.lower()):
                vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            out.append([x / norm for x in vector])
        return out


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed_module, "get_embedder", WordEmbedder)


def test_pdf_text_and_chunks() -> None:
    raw = SYLLABUS_PDF.read_bytes()
    assert is_pdf(raw)
    assert not is_pdf(b"\x89PNG....")
    pages = page_texts(raw)
    assert len(pages) == 2
    assert "Thevenin" in pages[1]
    chunks = chunk_pages(pages, target=400, overlap=80)
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 2
    assert all(len(c.content) <= 400 + 80 + 2 for c in chunks)
    spanning = chunk_pages(["a" * 50, "b" * 50])
    assert (spanning[0].page_start, spanning[0].page_end) == (1, 2)  # "s. 1-2"


async def stored_pdf(session: AsyncSession, upload_dir: Path) -> Attachment:
    raw = SYLLABUS_PDF.read_bytes()
    attachment = Attachment(
        path=store_pdf(raw, upload_dir, NOW),
        mime="application/pdf",
        width=0,
        height=0,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        filename="ee211_syllabus.pdf",
    )
    session.add(attachment)
    await session.flush()
    return attachment


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_syllabus_is_proposed_then_saved_and_searchable(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agent.tools import materials as materials_tools
    from app.config import Settings

    monkeypatch.setattr(
        materials_tools, "get_settings", lambda: Settings(_env_file=None, upload_dir=tmp_path)
    )
    fake = ScriptedLLM()
    yaver = yaver_with_uploads(fake, tmp_path)
    attachment = await stored_pdf(session, tmp_path)
    seen: list[str] = []
    classify_input: list[str] = []

    def classify(request: LLMRequest) -> LLMResponse:
        classify_input.append(request.messages[0].content)
        return call("document_kind", kind="syllabus", course="EE211", summary="EE211 syllabus")

    def show(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("EE211 syllabus'unu şöyle okudum: ... Kaydedeyim mi?")

    fake.add(
        "document_reader",
        classify,
        call("syllabus", course_code="EE211", course_name="Devre Teorisi I", weeks=WEEKS),
    )
    fake.add("yaver", show)
    first = await yaver.handle(
        session, "bu dersin syllabus'u", now=NOW, attachment_ids=[attachment.id]
    )

    assert fake.purposes[:2] == ["document_classify", "syllabus_parse"]
    assert "[s. 2]" in classify_input[0]  # the PDF's own text, page by page
    assert seen[0].startswith("bu dersin syllabus'u\n\n[PDF 1: ee211_syllabus.pdf, 2 sayfa")
    assert "EE211 Devre Teorisi I syllabus'u, 3 hafta -> öneri #1, henüz kaydedilmedi" in seen[0]
    assert "| 7 | Thevenin ve Norton eşdeğer devreleri |" in seen[0]
    assert await count(session, SyllabusWeek) == 0  # nothing before "evet"
    assert first.change_set_id is None
    proposal = await session.get(Proposal, 1)
    assert proposal is not None
    assert proposal.kind is ProposalKind.SYLLABUS

    # "evet" to the open proposal: applied by the code (app.agent.pending)
    fake.add("yaver", say("Syllabus'u kaydettim."))
    done = await yaver.handle(session, "evet", conversation_id=first.conversation_id, now=NOW)
    assert [t["tool"] for t in done.trace] == ["apply_proposal"]
    fake.assert_done()

    assert await count(session, SyllabusWeek) == 3
    material = await session.scalar(select(CourseMaterial))
    assert material is not None
    assert (material.kind, material.title, material.pages) == ("syllabus", "ee211_syllabus.pdf", 2)
    assert material.indexed_at is not None
    course = await session.scalar(select(Course).where(Course.code == "EE211"))
    assert course is not None  # created from the syllabus
    assert await count(session, MaterialChunk) >= 2
    await session.refresh(proposal)
    assert proposal.status is ProposalStatus.APPLIED

    ctx = context(session, "academic")
    found = await run_tool(
        "search_materials", {"query": "Thevenin direnci nedir", "course": "EE211"}, ctx
    )
    top = found["results"][0]
    assert top["source"] == "ee211_syllabus.pdf, s. 2"
    assert "Thevenin" in top["text"]
    assert top["course"] == "EE211"
    week = await run_tool("get_syllabus", {"course": "EE211", "week": 7}, ctx)
    assert week["weeks"] == [{"week": 7, "topics": "Thevenin ve Norton eşdeğer devreleri"}]
    assert "current_term_week" in week

    # one "Geri al": weeks, the material and (by cascade) its passages are gone
    assert done.change_set_id is not None
    await undo_change_set(session, done.change_set_id, NOW)
    assert await count(session, SyllabusWeek) == 0
    assert await count(session, CourseMaterial) == 0
    assert await count(session, MaterialChunk) == 0


async def test_scanned_or_other_pdfs(session: AsyncSession, tmp_path: Path) -> None:
    fake = ScriptedLLM()
    yaver = yaver_with_uploads(fake, tmp_path)
    attachment = await stored_pdf(session, tmp_path)
    seen: list[str] = []

    def show(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("...")

    fake.add("document_reader", call("document_kind", kind="other", summary="Bir fatura"))
    fake.add("yaver", show)
    await yaver.handle(session, "", now=NOW, attachment_ids=[attachment.id])
    assert "[PDF 1: ee211_syllabus.pdf, 2 sayfa: Bir fatura]" in seen[0]
    assert seen[0].endswith("Cevabın Türkçe olsun.)")
    assert "syllabus_parse" not in fake.purposes  # no Sonnet call for other documents


async def test_search_without_materials(session: AsyncSession) -> None:
    result = await run_tool("search_materials", {"query": "fazör"}, context(session))
    assert result["results"] == []
    assert "do not make it up" in result["note"]


async def test_pdf_upload(client: httpx2.AsyncClient, session: AsyncSession) -> None:  # noqa: F811
    files = [("files", ("../../EE211 syllabus.pdf", SYLLABUS_PDF.read_bytes(), "application/pdf"))]
    response = await client.post("/api/uploads", files=files)
    assert response.status_code == 200, response.text
    view: dict[str, Any] = response.json()["attachments"][0]
    assert view["mime"] == "application/pdf"
    assert view["filename"] == "EE211 syllabus.pdf"  # no path parts
    served = await client.get(view["url"])
    assert served.content[:5] == b"%PDF-"
