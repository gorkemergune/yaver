"""O3: web search / Meta ads tools ("entegrasyon bekliyor" without a key) and the new
employees' shift jobs, which end with a line in the notebook."""

import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.team import TeamConfig
from app.config import Settings
from app.db.models import EmployeeNote, EmployeeTask, Event, Followup, JobRun
from app.db.models.enums import Activity, EventKind, FollowupCheckRule, FollowupStatus
from app.db.session import CONNECT_ARGS
from app.integrations import web_search as search
from app.integrations.meta_ads import NO_CREDENTIALS, NOT_BUILT, ads_status
from app.jobs.scheduler import plans
from app.office.shift_jobs import run_shift_job, shift_plans
from app.office.state import BUDGET, Office
from tests.agent_fakes import NOW, REPO_CONFIG, ScriptedLLM, call, say
from tests.db.test_agent_tools import context, tool
from tests.db.test_office import IST, coordinator_with, spend

SETTINGS = Settings(_env_file=None)


def example_config() -> TeamConfig:
    with (REPO_CONFIG / "agents.example.yaml").open(encoding="utf-8") as fh:
        return TeamConfig.model_validate(yaml.safe_load(fh))


@pytest.fixture
async def office(session: AsyncSession, database_url: str) -> AsyncIterator[Office]:
    engine = create_async_engine(database_url, connect_args=CONNECT_ARGS)
    office = Office(async_sessionmaker(engine, expire_on_commit=False), example_config(), IST)
    assert await office.start()
    yield office
    await engine.dispose()


class FakeSearch:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.queries: list[str] = []
        self.fail = fail

    async def search(self, query: str, max_results: int = 5) -> list[search.SearchResult]:
        self.queries.append(query)
        if self.fail:
            raise search.SearchError("web search failed: HTTP 429")
        return [
            search.SearchResult(f"{query} haberi {i}", f"https://www.site{i}.com/a", "özet")
            for i in range(1, max_results + 1)
        ]


async def notes_of(session: AsyncSession, employee_id: str) -> list[str]:
    session.expire_all()
    rows = await session.scalars(
        select(EmployeeNote.content)
        .where(EmployeeNote.employee_id == employee_id)
        .order_by(EmployeeNote.id)
    )
    return list(rows.all())


# --- tools ---------------------------------------------------------------------------------


async def test_web_search_without_a_key_is_pending_and_noted_once_a_day(
    session: AsyncSession, office: Office, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(search, "get_web_search", lambda: None)
    ctx = context(session, agent_id="startup")

    first = await tool(ctx, "web_search", query="Nexa rakipleri")
    again = await tool(ctx, "web_search", query="başka bir şey")
    await session.commit()

    assert first["status"] == "integration_pending"
    assert first["message"] == search.PENDING_NOTE
    assert again["status"] == "integration_pending"
    assert await notes_of(session, "startup") == [search.PENDING_NOTE]  # once, not twice
    assert len(ctx.notes) == 1  # announced to the office once committed
    assert "error" not in first  # not a failure: no red dot, the employee just waits


async def test_web_search_with_a_provider_returns_results(
    session: AsyncSession, office: Office, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSearch()
    monkeypatch.setattr(search, "get_web_search", lambda: fake)
    result = await tool(
        context(session, agent_id="content"), "web_search", query="reels", max_results=2
    )

    assert fake.queries == ["reels"]
    assert [r["title"] for r in result["results"]] == ["reels haberi 1", "reels haberi 2"]

    monkeypatch.setattr(search, "get_web_search", lambda: FakeSearch(fail=True))
    failed = await tool(context(session, agent_id="content"), "web_search", query="reels")
    assert failed["error"] == "web search failed: HTTP 429"


def test_provider_choice_from_settings() -> None:
    from pydantic import SecretStr

    assert search.web_search_from(Settings(_env_file=None)) is None
    brave = Settings(_env_file=None, brave_api_key=SecretStr("b"))
    both = Settings(_env_file=None, brave_api_key=SecretStr("b"), tavily_api_key=SecretStr("t"))
    chosen = Settings(
        _env_file=None,
        brave_api_key=SecretStr("b"),
        tavily_api_key=SecretStr("t"),
        web_search_provider="brave",
    )
    assert getattr(search.web_search_from(brave), "name", None) == "brave"
    assert getattr(search.web_search_from(both), "name", None) == "tavily"  # auto: first
    assert getattr(search.web_search_from(chosen), "name", None) == "brave"


async def test_pending_without_the_employee_row_does_not_fail(session: AsyncSession) -> None:
    """No office yet (employees not synced): the tool still answers, nothing is noted."""
    result = await tool(context(session, agent_id="ads"), "get_ad_report", days=7)
    assert result["status"] == "integration_pending"
    await session.commit()
    assert await notes_of(session, "ads") == []


async def test_ad_report_is_a_pending_skeleton(session: AsyncSession, office: Office) -> None:
    from pydantic import SecretStr

    result = await tool(context(session, agent_id="ads"), "get_ad_report", days=7)
    assert result["status"] == "integration_pending"
    assert result["integration"] == "meta_ads"
    assert ads_status(SETTINGS).note == NO_CREDENTIALS
    keyed = Settings(_env_file=None, meta_access_token=SecretStr("x"), meta_ad_account_id="1")
    assert ads_status(keyed).note == NOT_BUILT


async def test_delegating_to_a_new_employee_runs_its_tool(
    session: AsyncSession, office: Office, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Nexa için post fikri bul" -> Mira; without a key she says so and notes it."""
    monkeypatch.setattr(search, "get_web_search", lambda: None)
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        call("delegate", agent_id="content", instruction="Nexa için post fikri bul"),
        say("Mira: web arama anahtarı olmadığı için trendlere bakamadı, defterine not aldı."),
    )
    llm.add(
        "content",
        call("web_search", query="Nexa post fikirleri"),
        say("Web arama anahtarı yok; defterime not aldım."),
    )
    reply = await coordinator_with(llm, office).handle(session, "Nexa için post fikri bul", now=NOW)

    assert [a["agent_id"] for a in reply.agents] == ["content"]
    assert await notes_of(session, "content") == [search.PENDING_NOTE]
    state = office.state("content")
    assert state is not None
    assert not state.needs_user  # waiting for a key is not the user's open question


# --- shift jobs ----------------------------------------------------------------------------


def run(key: str, office: Office, session: AsyncSession, **kw: Any) -> Any:
    return run_shift_job(
        key,
        now=kw.pop("now", NOW),
        settings=SETTINGS,
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        config=example_config(),
        office=office,
        **kw,
    )


def test_every_new_employee_has_a_scheduled_shift_job() -> None:
    config = example_config()
    keys = [p.key for p in shift_plans(config)]
    assert keys == [
        "shift:career:followup_watch",
        "shift:startup:web_scan",
        "shift:ads:ads_report",
        "shift:research:deadline_watch",
        "shift:content:web_scan",
        "shift:social:social_reminders",
    ]
    scheduled = {p.job_id: p for p in plans(SETTINGS, config)}
    assert set(keys) <= set(scheduled)
    assert scheduled["shift:startup:web_scan"].at == dt.time(8, 30)
    assert "briefing" in scheduled  # the existing jobs stay


async def test_web_scan_notes_the_top_results(session: AsyncSession, office: Office) -> None:
    fake = FakeSearch()
    async with office.hub.subscribe() as queue:
        text = await run("shift:startup:web_scan", office, session, web=fake)
        events = [queue.get_nowait() for _ in range(queue.qsize())]

    assert fake.queries == ["yapay zeka girişim haberleri", "girişim yatırımları Türkiye"]
    assert text is not None
    assert text.startswith(
        "Tarama · yapay zeka girişim haberleri: yapay zeka girişim haberleri haberi 1 (site1.com)"
    )
    assert await notes_of(session, "startup") == [text]
    inbox = (
        await session.scalars(select(EmployeeTask).where(EmployeeTask.employee_id == "startup"))
    ).all()
    assert [(t.source.value, t.instruction, t.status.value, t.result) for t in inbox] == [
        ("shift", "Sabah rakip taraması", "done", text)
    ]
    states = [(e["activity"], e["task"]) for e in events if e["type"] == "state"]
    assert states == [("working", "Sabah rakip taraması"), ("break", None)]
    assert any(e["type"] == "note" for e in events)
    # once a day
    assert await run("shift:startup:web_scan", office, session, web=fake) is None
    assert len(fake.queries) == 2


async def test_web_scan_without_a_key_notes_it_once(session: AsyncSession, office: Office) -> None:
    first = await run("shift:content:web_scan", office, session, web=None)
    forced = await run("shift:content:web_scan", office, session, web=None, force=True)

    assert first == forced == search.PENDING_NOTE
    assert await notes_of(session, "content") == [search.PENDING_NOTE]


async def test_ads_report_job_notes_the_pending_integration(
    session: AsyncSession, office: Office
) -> None:
    assert await run("shift:ads:ads_report", office, session) == NO_CREDENTIALS
    assert await notes_of(session, "ads") == [NO_CREDENTIALS]


async def test_data_jobs_note_what_is_coming_or_stay_quiet(
    session: AsyncSession, office: Office
) -> None:
    # nothing in the database: no note, but the run is recorded
    assert await run("shift:social:social_reminders", office, session) is None
    assert (await session.scalars(select(JobRun.job_id))).all() == ["shift:social:social_reminders"]

    start = dt.datetime(2026, 11, 27, 17, 0, tzinfo=dt.UTC)  # Friday 20:00 Istanbul
    session.add_all(
        [
            Event(kind=EventKind.OTHER, title="Ali'nin doğum günü", start_at=start),
            Event(kind=EventKind.DEADLINE, title="TÜBİTAK ara rapor", start_at=start),
            Event(kind=EventKind.MEETING, title="Iceberg toplantısı", start_at=start),
            Followup(
                title="Medipol staj dönüşü",
                status=FollowupStatus.WAITING,
                check_rule=FollowupCheckRule.DAILY,
                created_at=NOW - dt.timedelta(days=3),
            ),
        ]
    )
    await session.commit()
    later = NOW + dt.timedelta(days=1)

    social = await run("shift:social:social_reminders", office, session, now=later)
    research = await run("shift:research:deadline_watch", office, session)
    career = await run("shift:career:followup_watch", office, session)

    assert social == "Önümüzdeki 7 gün: Ali'nin doğum günü (27 Kasım Cuma)"
    assert research == "Yaklaşan teslimler: TÜBİTAK ara rapor (27 Kasım Cuma)"
    assert career == "Dönüş bekleniyor: Medipol staj dönüşü (3 gündür)"
    assert await notes_of(session, "research") == [research]


async def test_shift_job_over_budget_waits(session: AsyncSession, office: Office) -> None:
    await spend(session, "research", "0.30", dt.datetime.now(dt.UTC))

    assert (
        await run("shift:research:deadline_watch", office, session, now=dt.datetime.now(dt.UTC))
        is None
    )
    assert not (await session.scalars(select(JobRun))).all()  # may run once the day turns
    state = office.state("research")
    assert state is not None
    assert state.needs_user_reason == BUDGET
    assert state.activity is Activity.BREAK


async def test_unknown_shift_job_is_skipped(session: AsyncSession, office: Office) -> None:
    assert await run("shift:nobody:web_scan", office, session) is None
