"""Study sheets: passages picked in code, written by the (fake) smart tier, sources added
by code; read and downloaded over HTTP."""

import datetime as dt

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.agent.tools.study import with_sources
from app.db.models import Course, CourseMaterial, SyllabusWeek
from app.db.models.study import StudySheet
from app.llm.types import LLMRequest, LLMResponse
from app.rag import embed as embed_module
from app.rag.store import Hit, index_material
from tests.agent_fakes import NOW, ScriptedLLM, call
from tests.db.test_agent_tools import context
from tests.db.test_api_web import client, llm  # noqa: F401 - fixtures
from tests.db.test_materials import WordEmbedder

PAGES = [
    "EE211 ders notları. Hafta 7.",
    "Thevenin eşdeğeri: doğrusal iki uçlu bir devre, bir gerilim kaynağı ve ona seri bir "
    "dirençle değiştirilebilir. Thevenin direnci, bağımsız kaynaklar söndürülerek uçlardan "
    "görülen dirençtir.",
    "Norton eşdeğeri: bir akım kaynağı ve ona paralel bir direnç. R_N = R_Th, I_N = V_Th / R_Th.",
]


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed_module, "get_embedder", WordEmbedder)


async def notes(session: AsyncSession) -> Course:
    course = Course(code="EE211", name="Devre Teorisi I")
    session.add(course)
    await session.flush()
    session.add(SyllabusWeek(course_id=course.id, week_no=7, topics="Thevenin ve Norton eşdeğeri"))
    material = CourseMaterial(
        course_id=course.id, kind="notes", title="ee211_hafta7.pdf", pages=3, week_no=7
    )
    session.add(material)
    await session.flush()
    await index_material(session, material, PAGES, NOW)
    await session.commit()
    return course


def test_sources_are_built_by_code() -> None:
    hits = [
        Hit(1, "a.pdf", "notes", "EE211", 7, 2, 2, "x", 0.9),
        Hit(1, "a.pdf", "notes", "EE211", 7, 3, 3, "y", 0.8),
    ]
    text, sources = with_sources("Tanım [1]. Uydurma [7]. Formül [2] [1].", hits)
    assert text.startswith("Tanım [1]. Uydurma . Formül [2] [1].")  # [7] pointed nowhere
    assert text.endswith("## Kaynaklar\n\n- [1] a.pdf, s. 2\n- [2] a.pdf, s. 3\n")
    assert [s["n"] for s in sources] == [1, 2]


async def test_study_sheet_from_the_weeks_notes(session: AsyncSession) -> None:
    await notes(session)
    ctx = context(session, "academic")
    seen: list[str] = []

    def write(request: LLMRequest) -> LLMResponse:
        seen.append(request.messages[0].content)
        return call(
            "study_sheet",
            title="EE211 · 7. hafta: Thevenin ve Norton",
            markdown="## Özet\nThevenin direnci kaynaklar söndürülerek bulunur [1].\n"
            "## Formüller ve kurallar\n- R_N = R_Th [2]",
        )

    fake = ScriptedLLM({"study_sheet": [write]})
    ctx.llm = fake
    result = await run_tool("generate_study_sheet", {"course": "EE211", "week": 7}, ctx)

    assert fake.purposes == ["study_sheet"]
    assert "Haftanın konuları (syllabus): Thevenin ve Norton eşdeğeri" in seen[0]
    assert "[1] (ee211_hafta7.pdf, s. 1-3)" in seen[0]  # short pages packed, file + pages
    sheet_info = result["study_sheet"]
    assert sheet_info["link"] == "[EE211 · 7. hafta: Thevenin ve Norton](#/sheet?id=1)"
    sheet = await session.scalar(select(StudySheet))
    assert sheet is not None
    assert sheet.week_no == 7
    assert "## Kaynaklar" in sheet.content_md
    assert "ee211_hafta7.pdf, s. " in sheet.content_md
    assert sheet.model == "fake/fake"


async def test_no_material_no_sheet(session: AsyncSession) -> None:
    session.add(Course(code="CSE221", name="Veri Yapıları"))
    await session.commit()
    ctx = context(session, "academic")
    ctx.llm = ScriptedLLM()
    result = await run_tool("generate_study_sheet", {"course": "CSE221"}, ctx)
    assert "send the notes" in result["error"]


async def test_sheets_over_http(client: httpx2.AsyncClient, session: AsyncSession) -> None:  # noqa: F811
    course = await notes(session)
    session.add(
        StudySheet(
            course_id=course.id,
            week_no=7,
            title="EE211 · 7. hafta: Thevenin",
            content_md="## Özet\nx [1]\n\n## Kaynaklar\n\n- [1] ee211_hafta7.pdf, s. 2\n",
            sources=[{"n": 1, "title": "ee211_hafta7.pdf", "pages": "s. 2", "material_id": 1}],
            model="fake/fake",
            created_at=dt.datetime(2026, 11, 23, 9, tzinfo=dt.UTC),
        )
    )
    await session.commit()
    listed = (await client.get("/api/study-sheets")).json()["sheets"]
    assert listed[0]["title"] == "EE211 · 7. hafta: Thevenin"
    assert listed[0]["course"] == "EE211"
    full = (await client.get(f"/api/study-sheets/{listed[0]['id']}")).json()
    assert full["content_md"].startswith("## Özet")
    md = await client.get(f"/api/study-sheets/{listed[0]['id']}/download.md")
    assert md.headers["content-type"].startswith("text/markdown")
    assert "filename*=UTF-8''EE211-7-hafta-Thevenin.md" in md.headers["content-disposition"]
    assert md.text.startswith("# EE211 · 7. hafta: Thevenin\n\n## Özet")
    assert (await client.get("/api/study-sheets/99")).status_code == 404
