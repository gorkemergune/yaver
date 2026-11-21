"""Creator's weekly content calendar: a draft from the team's own notes (+ trends when a web
search key exists), weekdays turned into dates in code, written to the notebook. Never posted."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import team
from app.agent.tools import REGISTRY, run_tool
from app.config import Settings
from app.content.calendar import week_after
from app.core.change_log import undo_change_set
from app.db.models import EmployeeNote, Event, Memory
from app.db.models.enums import EventKind
from app.llm.types import LLMRequest, LLMResponse
from app.office.shift_jobs import run_shift_job
from app.office.state import Office
from tests.agent_fakes import NOW, ScriptedLLM, call
from tests.db.test_agent_tools import context
from tests.db.test_shift_jobs import FakeSearch, example_config, notes_of, office  # noqa: F401

PLAN: dict[str, Any] = {
    "posts": [
        {
            "weekday": "Çarşamba",
            "platform": "LinkedIn",
            "format": "post",
            "topic": "Demo videosu hazır",
            "draft": "Bu hafta demo videomuzu tamamladık.",
            "basis": "Venture notu: demo videosu PR #9",
        },
        {
            "weekday": "Pazartesi",
            "platform": "Instagram",
            "format": "carousel",
            "topic": "Ekip tanıtımı",
            "draft": "Ekibimizle tanışın | 3 kişi, 1 hedef",
            "basis": "kalıcı bilgi",
        },
        {
            "weekday": "Cuma",
            "platform": "Instagram",
            "format": "reel",
            "topic": "Jüri provası",
            "draft": "Cumartesi jüri karşısındayız!",
            "basis": "etkinlik: jüri sunumu provası",
        },
    ],
    "needs": ["Ekip fotoğrafı"],
}


class Seen:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def __call__(self, request: LLMRequest) -> LLMResponse:
        self.texts.append(request.messages[-1].content)
        return call("content_plan", **PLAN)


async def seed(session: AsyncSession) -> None:
    session.add_all(
        [
            Memory(category="work", content="Örnek Girişim kampüs etkinlik asistanı yapıyor"),
            Memory(category="personal", content="Cuma günleri spor"),
            EmployeeNote(
                employee_id="startup",
                content="Sabah depo kontrolü: Hazır: demo videosu teslim (PR #9)",
                created_at=NOW - dt.timedelta(days=1),
            ),
            EmployeeNote(
                employee_id="startup",
                content="GitHub entegrasyonu bekliyor: ...",
                created_at=NOW - dt.timedelta(hours=2),
            ),
            Event(
                kind=EventKind.DEADLINE,
                title="Örnek Girişim jüri sunumu provası",
                start_at=NOW + dt.timedelta(days=5),
                end_at=NOW + dt.timedelta(days=6),
                all_day=True,
            ),
            Event(
                kind=EventKind.EXAM, title="EE211 Ara Sınav", start_at=NOW + dt.timedelta(days=2)
            ),
        ]
    )
    await session.commit()  # the shift job reads with its own session


def run(session: AsyncSession, office: Office, llm: ScriptedLLM, **kw: Any) -> Any:  # noqa: F811
    return run_shift_job(
        "shift:content:content_calendar",
        now=NOW,  # Monday 23 November
        settings=Settings(_env_file=None),
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        config=example_config(),
        office=office,
        llm=llm,
        **kw,
    )


async def test_without_a_search_key_the_draft_builds_on_the_teams_notes(
    session: AsyncSession,
    office: Office,  # noqa: F811
) -> None:
    await seed(session)
    llm, seen = ScriptedLLM(), Seen()
    llm.add("content", seen)

    note = await run(session, office, llm, web=None)

    assert llm.purposes == ["content_calendar"]
    asked = seen.texts[0]
    assert asked.startswith(
        "Planlanacak hafta: 23 Kas - 29 Kas (23 Kas Pazartesi, 24 Kas Salı, 25 Kas Çarşamba,"
    )
    assert "29 Kas Pazar)" in asked
    assert "Marka / konular: Örnek Girişim" in asked
    assert "- Örnek Girişim kampüs etkinlik asistanı yapıyor" in asked
    assert "Cuma günleri spor" not in asked  # not about the brand
    assert "Hazır: demo videosu teslim (PR #9)" in asked
    assert "entegrasyonu bekliyor" not in asked
    assert "- 28 Kas Cumartesi: Örnek Girişim jüri sunumu provası" in asked
    assert "EE211" not in asked
    assert "Trend verisi yok" in asked

    lines = note.splitlines()
    assert lines[0] == "İçerik takvimi taslağı (23 Kas - 29 Kas), paylaşılmadı, onayını bekliyor:"
    assert lines[3].startswith("| 23 Kas Pazartesi | Instagram | carousel | Ekip tanıtımı |")
    assert "Ekibimizle tanışın / 3 kişi" in lines[3]  # a "|" in the text can't break the table
    assert lines[4].startswith("| 25 Kas Çarşamba | LinkedIn |")
    assert lines[5].startswith("| 27 Kas Cuma | Instagram | reel |")
    assert "Ekipten gerekenler: Ekip fotoğrafı" in note
    assert note.endswith("Trend yok: web arama anahtarı gelince trendleri de eklerim.")
    assert note in await notes_of(session, "content")


async def test_with_a_search_key_trends_are_added(
    session: AsyncSession,
    office: Office,  # noqa: F811
) -> None:
    llm, seen = ScriptedLLM(), Seen()
    llm.add("content", seen)
    search = FakeSearch()

    note = await run(session, office, llm, web=search)

    assert search.queries == ["Örnek Girişim sosyal medya içerik trendleri"]
    assert "Bu haftanın trendleri (web):" in seen.texts[0]
    assert note.endswith("Trendler eklendi (web).")


async def test_no_model_is_a_note_not_a_crash(
    session: AsyncSession,
    office: Office,  # noqa: F811
) -> None:
    llm = ScriptedLLM()
    llm.add("content", call("something_else"))

    note = await run(session, office, llm, web=None)

    assert note == "İçerik takvimi bu hafta çıkarılamadı (model yok)."


async def test_in_the_chat_the_draft_is_undoable_and_never_posted(
    session: AsyncSession,
    office: Office,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(team, "load_team_config", example_config)  # not the local agents.yaml
    llm, seen = ScriptedLLM(), Seen()
    llm.add("content", seen)
    ctx = context(session, agent_id="content")
    ctx.llm = llm

    result = await run_tool("draft_content_calendar", {}, ctx)

    assert result["posted"] is False
    assert result["posts"] == 3
    assert "Marka / konular: Örnek Girişim" in seen.texts[0]  # from the shift plan
    assert len(ctx.notes) == 1
    await undo_change_set(session, ctx.change_set_id, NOW)
    assert (await session.scalars(select(EmployeeNote))).all() == []


def test_no_tool_can_post() -> None:
    words = ("post", "publish", "share", "paylas", "tweet", "upload")
    assert [name for name in REGISTRY if any(w in name for w in words)] == []


def test_the_planned_week() -> None:
    assert week_after(dt.date(2026, 11, 23)) == (dt.date(2026, 11, 23), dt.date(2026, 11, 29))
    assert week_after(dt.date(2026, 11, 25)) == (dt.date(2026, 11, 30), dt.date(2026, 12, 6))
