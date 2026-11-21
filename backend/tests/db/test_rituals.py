"""O4 rituals: the standup inside the morning briefing, the day report, the Sunday meeting
around the weekly plan, and the task board."""

import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import EmployeeNote, EmployeeTask, Message
from app.db.models.enums import Activity, EmployeeTaskStatus, TaskOrigin
from app.db.session import CONNECT_ARGS
from app.jobs import runner
from app.jobs.runner import run_job
from app.jobs.scheduler import plans
from app.llm.types import LLMRequest
from app.office.board import board
from app.office.rituals import QUIET, meeting
from app.office.state import QUESTION, Office
from tests.agent_fakes import NOW, ScriptedLLM, example_team, say
from tests.db.test_office import IST
from tests.db.test_shift_jobs import example_config

SETTINGS = Settings(_env_file=None)


@pytest.fixture
async def office(session: AsyncSession, database_url: str) -> AsyncIterator[Office]:
    engine = create_async_engine(database_url, connect_args=CONNECT_ARGS)
    office = Office(async_sessionmaker(engine, expire_on_commit=False), example_config(), IST)
    assert await office.start()
    yield office
    await engine.dispose()


@pytest.fixture(autouse=True)
def example_team_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """The jobs read agents.yaml: use the example, not the developer's own file."""
    monkeypatch.setattr(runner, "load_team_config", example_config)


def drain(queue: Any) -> list[dict[str, Any]]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def lines_from(request: LLMRequest) -> str:
    return request.messages[-1].content


async def test_standup_meets_everyone_and_joins_the_briefing(
    session: AsyncSession, office: Office
) -> None:
    session.add(
        EmployeeNote(employee_id="academic", content="MATH 221 devamsızlık sınırda", created_at=NOW)
    )
    await session.commit()
    llm = ScriptedLLM()
    # employees with something to say: Scholar (a note) and the six with shift jobs today;
    # Coach has nothing to say: its line is written by code (no LLM call)
    seen: dict[str, str] = {}

    def report(agent_id: str, line: str) -> Any:
        def step(request: LLMRequest) -> Any:
            seen[agent_id] = lines_from(request)
            return say(f"- {line}")

        return step

    llm.add("academic", report("academic", "MATH 221 sınırda; bugün tekrar planına bakacağım."))
    for agent_id in ("agenda", "career", "startup", "ads", "content", "social"):
        llm.add(agent_id, report(agent_id, f"{agent_id} bugünkü mesaisini yapacak."))

    async with office.hub.subscribe() as queue:
        message_id = await run_job(
            "briefing",
            now=NOW,
            settings=SETTINGS,
            sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
            team=example_team(),
            llm=llm,
            office=office,
        )
        events = drain(queue)
    llm.assert_done()

    message = await session.get(Message, message_id)
    assert message is not None
    assert message.kind == "briefing"
    assert message.content.startswith("Günaydın")
    standup = message.content.split("**Standup**\n", 1)[1].splitlines()
    assert standup[0] == "- **Scholar**: MATH 221 sınırda; bugün tekrar planına bakacağım."
    assert f"- **Coach**: {QUIET}" in standup
    assert len(standup) == 8  # every employee, Yaver hosts
    assert "Defterimdeki son notlar: MATH 221 devamsızlık sınırda" in seen["academic"]
    assert "Bugünkü mesai işlerim: 08:30 Sabah rakip taraması" in seen["startup"]

    meetings = {
        e["employee_id"]: e for e in events if e["type"] == "state" and e["activity"] == "meeting"
    }
    assert set(meetings) == {"yaver", *(a.id for a in example_team().agents)}
    assert meetings["academic"]["meeting_with"] == "yaver"
    assert meetings["academic"]["task"] == "Sabah standup'ı"
    assert all(state.activity is Activity.BREAK for state in office._states.values())
    inbox = (await session.scalars(select(EmployeeTask))).all()
    assert [(t.employee_id, t.source.value, t.instruction) for t in inbox] == [
        ("yaver", "shift", "Sabah standup'ı ve brifing")
    ]


async def test_briefing_without_the_office_has_no_standup(session: AsyncSession) -> None:
    message_id = await run_job(
        "briefing",
        now=NOW,
        settings=SETTINGS,
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        team=example_team(),
    )
    message = await session.get(Message, message_id)
    assert message is not None
    assert "**Standup**" not in message.content


async def test_day_report_sums_up_the_notebooks(session: AsyncSession, office: Office) -> None:
    sessionmaker = async_sessionmaker(session.bind, expire_on_commit=False)
    # nothing happened today: no message
    assert (
        await run_job(
            "day_report",
            now=NOW,
            settings=SETTINGS,
            sessionmaker=sessionmaker,
            team=example_team(),
            llm=ScriptedLLM(),
        )
        is None
    )

    session.add_all(
        [
            EmployeeNote(
                employee_id="startup", content="Tarama · rakip X yeni tur aldı", created_at=NOW
            ),
            EmployeeTask(
                employee_id="agenda",
                source=TaskOrigin.YAVER,
                instruction="Cuma 15:00 toplantı ekle",
                status=EmployeeTaskStatus.DONE,
                result="Ekledim.",
                created_at=NOW,
            ),
        ]
    )
    await session.commit()
    received: list[str] = []

    def summary(request: LLMRequest) -> Any:
        received.append(lines_from(request))
        return say(
            "- **Venture**: rakip X yeni yatırım turu aldı.\n"
            "- **Chrono**: Cuma toplantısını ekledi."
        )

    llm = ScriptedLLM({"yaver": [summary]})
    later = NOW + dt.timedelta(hours=11)  # 21:00 Istanbul, same day
    message_id = await run_job(
        "day_report",
        now=later,
        settings=SETTINGS,
        sessionmaker=sessionmaker,
        team=example_team(),
        llm=llm,
        force=True,
    )
    message = await session.get(Message, message_id)
    assert message is not None
    assert message.kind == "day_report"
    assert message.content.startswith("**Gün sonu raporu** · 23.11\n- **Venture**")
    assert "Venture: not: Tarama · rakip X yeni tur aldı" in received[0]
    assert "Chrono: iş: Cuma 15:00 toplantı ekle -> Ekledim." in received[0]


async def test_weekly_meeting_puts_the_planners_in_the_room(office: Office) -> None:
    async with office.hub.subscribe() as queue:
        async with meeting(
            office, "yaver", ["academic", "agenda", "discipline"], "Haftalık toplantı"
        ):
            inside = {e: office.state(e) for e in ("yaver", "academic", "content")}
        events = drain(queue)
    assert inside["yaver"].activity is Activity.MEETING  # type: ignore[union-attr]
    assert inside["academic"].meeting_with == "yaver"  # type: ignore[union-attr]
    assert inside["content"].activity is Activity.BREAK  # type: ignore[union-attr]
    assert [e["activity"] for e in events if e["employee_id"] == "academic"] == ["meeting", "break"]


def test_rituals_are_scheduled() -> None:
    scheduled = {p.job_id: p for p in plans(SETTINGS)}
    assert scheduled["day_report"].at == dt.time(21, 15)  # after the 21:00 check-in
    assert scheduled["briefing"].at == dt.time(9, 0)  # the standup


async def test_board_columns(session: AsyncSession, office: Office) -> None:
    session.add_all(
        [
            EmployeeTask(
                employee_id="academic",
                source=TaskOrigin.YAVER,
                instruction="EE211 notlarına bak",
                status=EmployeeTaskStatus.RUNNING,
                created_at=NOW,
            ),
            EmployeeTask(
                employee_id="agenda",
                source=TaskOrigin.USER,
                instruction="toplantı ekle",
                status=EmployeeTaskStatus.DONE,
                result="Hangi gün?",
                created_at=NOW,
            ),
            EmployeeTask(
                employee_id="social",
                source=TaskOrigin.USER,
                instruction="doğum günü ekle",
                status=EmployeeTaskStatus.DONE,
                result="Ekledim.",
                created_at=NOW,
            ),
            EmployeeTask(
                employee_id="ads",
                source=TaskOrigin.USER,
                instruction="rapor",
                status=EmployeeTaskStatus.FAILED,
                created_at=NOW,
            ),
            # a shift job after the question: the question still waits on the chat task
            EmployeeTask(
                employee_id="agenda",
                source=TaskOrigin.SHIFT,
                instruction="Yaklaşan teslimlere bakıyor",
                status=EmployeeTaskStatus.DONE,
                created_at=NOW + dt.timedelta(minutes=1),
            ),
        ]
    )
    await session.commit()
    await office.flag("agenda", QUESTION)

    result = await board(session, example_config(), SETTINGS, office, NOW)  # Monday 10:00
    by_column: dict[str, list[tuple[str, str]]] = {}
    for card in result["cards"]:
        by_column.setdefault(card["column"], []).append((card["employee_id"], card["title"]))

    assert by_column["running"] == [("academic", "EE211 notlarına bak")]
    assert by_column["approval"] == [("agenda", "toplantı ekle")]
    assert set(by_column["done"]) == {
        ("social", "doğum günü ekle"),
        ("ads", "rapor"),
        ("agenda", "Yaklaşan teslimlere bakıyor"),
    }
    waiting = by_column["waiting"]
    # 10:00 now: the 08:30 scan and the 09:00 standup are past; later jobs wait
    assert ("career", "Bekleyen başvuru dönüşlerine bakıyor") in waiting  # 10:00: due now
    assert ("social", "Bu haftanın hatırlatmaları") in waiting  # 10:30
    assert ("content", "Trend taraması") in waiting  # 11:00
    assert ("yaver", "Gün sonu raporu") in waiting
    assert ("startup", "Sabah rakip taraması") not in waiting
    assert ("yaver", "Sabah standup'ı ve brifing") not in waiting
    assert ("yaver", "Haftalık toplantı ve plan") not in waiting  # Sundays only
    assert result["columns"] == ["waiting", "running", "approval", "done"]
