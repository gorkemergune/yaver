"""The office engine (O1): employees from agents.yaml, set_state + events, the states a chat
message produces (working, meeting on delegation, break, red dot), the inbox, the notebook,
the daily budget and the HTTP endpoints."""

import asyncio
import datetime as dt
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.coordinator import Coordinator
from app.agent.team import TeamConfig
from app.api.chat import get_coordinator, get_session_factory
from app.api.office import office_events
from app.config import Settings, get_settings
from app.core.change_log import undo_change_set
from app.db.models import (
    ChangeLog,
    Conversation,
    Employee,
    EmployeeNote,
    EmployeeState,
    EmployeeTask,
    JobRun,
    LlmUsage,
    Message,
)
from app.db.models.enums import Activity, DeskRow, EmployeeTaskStatus, TaskOrigin
from app.db.session import CONNECT_ARGS, get_session
from app.jobs.runner import run_job
from app.main import create_app
from app.office.shifts import OverBudgetError, run_shift
from app.office.state import BUDGET, QUESTION, Office, get_office
from tests.agent_fakes import NOW, REPO_CONFIG, ScriptedLLM, call, example_team, say
from tests.db.test_agent_scenarios import week_setup_script

IST = ZoneInfo("Europe/Istanbul")


def example_config(open_at: str = "00:00", close_at: str = "00:00") -> TeamConfig:
    """The example team; the office always open unless hours are given (tests run at any
    hour of the day; test_office_hours_* pin the clock)."""
    with (REPO_CONFIG / "agents.example.yaml").open(encoding="utf-8") as fh:
        config = TeamConfig.model_validate(yaml.safe_load(fh))
    hours = config.office.model_copy(update={"open_at": open_at, "close_at": close_at})
    return config.model_copy(update={"office": hours})


@pytest.fixture
async def office(session: AsyncSession, database_url: str) -> AsyncIterator[Office]:
    # Its own pooled engine, like the app's: a state change must not open a connection each.
    engine = create_async_engine(database_url, connect_args=CONNECT_ARGS)
    office = Office(async_sessionmaker(engine, expire_on_commit=False), example_config(), IST)
    assert await office.start()
    yield office
    await engine.dispose()


def coordinator_with(llm: ScriptedLLM, office: Office) -> Coordinator:
    return Coordinator(llm, example_team(), Settings(_env_file=None), office)


def drain(queue: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def activities(events: list[dict[str, Any]], employee_id: str) -> list[str]:
    return [e["activity"] for e in events if e.get("employee_id") == employee_id]


# --- employees from agents.yaml ---------------------------------------------------------


async def test_employees_are_synced_from_the_team_config(
    session: AsyncSession, office: Office
) -> None:
    rows = (await session.scalars(select(Employee).order_by(Employee.sort_order))).all()

    assert [(e.id, e.name, e.desk_row, e.desk_col) for e in rows] == [
        ("yaver", "Yaver", DeskRow.OFFICE, 0),
        ("academic", "Scholar", DeskRow.BACK, 0),
        ("agenda", "Chrono", DeskRow.FRONT, 2),
        ("discipline", "Coach", DeskRow.FRONT, 3),
        ("career", "Mentor", DeskRow.BACK, 1),
        ("startup", "Venture", DeskRow.BACK, 2),
        ("ads", "Metrics", DeskRow.BACK, 3),
        ("content", "Creator", DeskRow.FRONT, 0),
        ("social", "Buddy", DeskRow.FRONT, 1),
    ]
    assert rows[0].is_coordinator
    assert rows[0].role == "Chief of Staff"
    assert rows[1].role == "Akademik"
    assert "log_attendance" in rows[1].tools
    assert {e.daily_budget_usd for e in rows} == {Decimal("0.2")}  # office.daily_budget_usd
    states = (await session.scalars(select(EmployeeState))).all()
    assert {(s.employee_id, s.activity) for s in states} == {(e.id, Activity.BREAK) for e in rows}


async def test_resync_keeps_removed_employees_inactive_and_resets_stale_work(
    session: AsyncSession, office: Office
) -> None:
    await office.set_state("academic", Activity.WORKING, task="eski iş")
    data = example_config().model_dump(mode="json")
    data["agents"] = [a for a in data["agents"] if a["id"] != "discipline"]
    data["agents"][0]["daily_budget_usd"] = 1.25
    data["weekly_plan"]["order"] = ["academic", "agenda"]

    restarted = Office(office.sessionmaker, TeamConfig.model_validate(data), IST)
    assert await restarted.start()  # a new process: nothing can be running

    session.expire_all()
    discipline = await session.get(Employee, "discipline")
    academic = await session.get(Employee, "academic")
    assert discipline is not None
    assert not discipline.active
    assert academic is not None
    assert academic.daily_budget_usd == Decimal("1.25")
    state = await session.get(EmployeeState, "academic")
    assert state is not None
    assert state.activity is Activity.BREAK
    assert state.current_task is None
    assert "discipline" not in restarted.employees


async def test_office_without_tables_does_nothing() -> None:
    def broken() -> Any:
        raise OSError("database down")

    office = Office(broken, example_config(), IST)  # type: ignore[arg-type]

    assert not await office.start()
    assert await office.set_state("academic", Activity.WORKING) is None
    assert (await office.snapshot())["ready"] is False


# --- set_state ----------------------------------------------------------------------------


async def test_set_state_stores_publishes_and_skips_repeats(
    session: AsyncSession, office: Office
) -> None:
    async with office.hub.subscribe() as queue:
        first = await office.set_state(
            "academic", Activity.WORKING, task="Plan", tool="get_day_plan"
        )
        again = await office.set_state(
            "academic", Activity.WORKING, task="Plan", tool="get_day_plan"
        )
        other = await office.set_state("academic", Activity.WORKING, task="Başka")
        events = drain(queue)

    assert first is not None
    assert again is None
    assert other is not None
    assert other.since == first.since  # same activity: still the same stretch of work
    assert [e["task"] for e in events] == ["Plan", "Başka"]
    assert events[0] == {
        "type": "state",
        "employee_id": "academic",
        "activity": "working",
        "task": "Plan",
        "tool": "get_day_plan",
        "meeting_with": None,
        "needs_user": False,
        "needs_user_reason": None,
        "since": first.since.isoformat(),
        "ts": first.updated_at.isoformat(),
    }
    row = await session.get(EmployeeState, "academic")
    assert row is not None
    assert row.activity is Activity.WORKING
    assert row.current_task == "Başka"
    assert await office.set_state("nobody", Activity.WORKING) is None


async def test_break_waits_for_the_last_job_of_an_employee(office: Office) -> None:
    office.acquire("agenda")
    office.acquire("agenda")
    await office.set_state("agenda", Activity.WORKING, task="iki iş")

    await office.release("agenda")
    state = office.state("agenda")
    assert state is not None
    assert state.activity is Activity.WORKING
    await office.release("agenda")
    state = office.state("agenda")
    assert state is not None
    assert state.activity is Activity.BREAK
    assert state.task is None


async def test_question_flag_outranks_budget_flag(office: Office) -> None:
    await office.flag("agenda", QUESTION)
    await office.flag("agenda", BUDGET)
    state = office.state("agenda")
    assert state is not None
    assert state.needs_user_reason == QUESTION

    await office.unflag("agenda", BUDGET)  # not the reason shown: stays
    assert office.state("agenda").needs_user  # type: ignore[union-attr]
    await office.unflag("agenda", QUESTION)
    assert not office.state("agenda").needs_user  # type: ignore[union-attr]


# --- a chat message in the office -------------------------------------------------------


async def test_delegation_shows_a_meeting_then_work_then_break(
    session: AsyncSession, office: Office
) -> None:
    llm = week_setup_script()
    async with office.hub.subscribe() as queue:
        reply = await coordinator_with(llm, office).handle(
            session,
            "Pazartesi 9-11 Linear Algebra, Çarşamba 13-15 EE211 lab, salı perşembe 19-20 spor",
            now=NOW,
        )
        events = drain(queue)
    llm.assert_done()

    # Yaver reads, meets Scholar, waits, merges; meets Coach, waits, merges; done.
    assert activities(events, "yaver") == [
        "working",
        "meeting",
        "working",
        "working",
        "meeting",
        "working",
        "working",
        "break",
    ]
    assert activities(events, "academic") == ["meeting", "working", "break"]
    assert activities(events, "discipline") == ["meeting", "working", "break"]
    assert activities(events, "agenda") == []  # not involved: no event
    meeting = next(e for e in events if e["employee_id"] == "academic")
    assert meeting["meeting_with"] == "yaver"
    assert meeting["task"].startswith("Pazartesi 9-11 Linear Algebra")
    at_desk = [e for e in events if e["employee_id"] == "academic" and e["activity"] == "working"]
    assert at_desk[0]["tool"] == "add_recurring_block"
    assert at_desk[0]["task"] == "Haftalık programa ekliyor"
    assert all(state.activity is Activity.BREAK for state in office._states.values())

    tasks = (await session.scalars(select(EmployeeTask).order_by(EmployeeTask.id))).all()
    assert [(t.employee_id, t.source, t.requested_by, t.status) for t in tasks] == [
        ("yaver", TaskOrigin.USER, None, EmployeeTaskStatus.DONE),
        ("academic", TaskOrigin.YAVER, "yaver", EmployeeTaskStatus.DONE),
        ("discipline", TaskOrigin.YAVER, "yaver", EmployeeTaskStatus.DONE),
    ]
    assert {t.change_set_id for t in tasks} == {reply.change_set_id}
    assert tasks[1].result == "Linear Algebra ve EE211 Lab eklendi."
    assert tasks[1].details == {"tools": ["add_recurring_block", "add_recurring_block"]}
    assert tasks[0].result == reply.reply


async def test_addressed_employee_works_then_breaks(session: AsyncSession, office: Office) -> None:
    llm = ScriptedLLM()
    llm.add(
        "academic",
        call("get_day_plan", date="2026-11-24"),
        say("Yarın dersin yok."),
    )
    async with office.hub.subscribe() as queue:
        await coordinator_with(llm, office).handle(session, "Scholar, yarın ne var?", now=NOW)
        events = drain(queue)

    academic = [e for e in events if e["employee_id"] == "academic"]
    assert [(e["activity"], e["task"]) for e in academic] == [
        ("working", "yarın ne var?"),
        ("working", "Günün planına bakıyor"),
        ("break", None),
    ]
    assert activities(events, "yaver") == []


async def test_open_question_is_a_red_dot_until_the_next_message(
    session: AsyncSession, office: Office
) -> None:
    llm = ScriptedLLM()
    llm.add("agenda", say("Toplantı hangi gün, yarın mı cuma mı?"))
    llm.add("agenda", say("Tamam, vazgeçtim."))
    coordinator = coordinator_with(llm, office)

    first = await coordinator.handle(session, "Chrono, yarın bir toplantım var", now=NOW)
    state = office.state("agenda")
    assert state is not None
    assert (state.activity, state.needs_user, state.needs_user_reason) == (
        Activity.BREAK,
        True,
        QUESTION,
    )
    snapshot = await office.snapshot()
    agenda = next(e for e in snapshot["employees"] if e["id"] == "agenda")
    assert agenda["needs_user"]
    assert agenda["needs_user_reason"] == "question"

    await coordinator.handle(
        session, "Chrono, boşver", conversation_id=first.conversation_id, now=NOW
    )
    assert not office.state("agenda").needs_user  # type: ignore[union-attr]


async def test_failed_message_sends_everyone_back_and_keeps_no_inbox_row(
    session: AsyncSession, office: Office
) -> None:
    llm = ScriptedLLM()
    llm.add("yaver", call("delegate", agent_id="academic", instruction="EE211 ekle"))
    # academic has no script: its LLM call fails mid-delegation

    with pytest.raises(AssertionError, match="unexpected LLM call"):
        await coordinator_with(llm, office).handle(session, "EE211 ekle", now=NOW)

    assert {s.activity for s in office._states.values()} == {Activity.BREAK}
    assert not (await session.scalars(select(EmployeeTask))).all()


# --- notebook -----------------------------------------------------------------------------


async def test_add_note_writes_the_notebook_publishes_it_and_undo_removes_it(
    session: AsyncSession, office: Office
) -> None:
    llm = ScriptedLLM()
    llm.add(
        "academic",
        call("add_note", content="MATH 221 devamsızlık 8/10 saat, sınırda"),
        say("Defterime yazdım."),
    )
    llm.add(
        "yaver",
        call("get_notes", employee="Scholar"),
        lambda request: say(request.messages[-1].content),
    )
    coordinator = coordinator_with(llm, office)

    async with office.hub.subscribe() as queue:
        reply = await coordinator.handle(
            session, "Scholar, defterine not al: MATH 221 sınırda", now=NOW
        )
        events = drain(queue)
    note_events = [e for e in events if e["type"] == "note"]
    assert [(e["employee_id"], e["note"]["content"]) for e in note_events] == [
        ("academic", "MATH 221 devamsızlık 8/10 saat, sınırda")
    ]
    assert reply.changes[0]["entity"] == "employee_notes"

    read = await coordinator.handle(session, "Scholar'ın defterinde ne var?", now=NOW)
    assert "MATH 221 devamsızlık 8/10 saat" in read.reply

    assert reply.change_set_id is not None
    await undo_change_set(session, reply.change_set_id, NOW)
    await session.commit()
    assert not (await session.scalars(select(EmployeeNote))).all()


# --- daily budget -------------------------------------------------------------------------


async def spend(session: AsyncSession, agent_id: str, usd: str, at: dt.datetime) -> None:
    session.add(
        LlmUsage(
            provider="anthropic",
            model="claude-haiku-5-5",
            tier="fast",
            purpose="chat",
            agent_id=agent_id,
            cost_usd=Decimal(usd),
            created_at=at,
        )
    )
    await session.commit()


async def test_over_budget_stops_shifts_with_a_red_dot(
    session: AsyncSession, office: Office
) -> None:
    now = dt.datetime.now(dt.UTC)
    await spend(session, "academic", "0.15", now - dt.timedelta(days=2))  # not today
    await spend(session, "academic", "0.15", now)

    async def job() -> str:
        state = office.state("academic")
        assert state is not None
        assert state.activity is Activity.WORKING
        return "done"

    assert await run_shift(office, "academic", "Sınav planı", job) == "done"
    state = office.state("academic")
    assert state is not None
    assert state.activity is Activity.BREAK
    assert not state.needs_user

    await spend(session, "academic", "0.10", now)  # 0.25 today > 0.20
    with pytest.raises(OverBudgetError):
        await run_shift(office, "academic", "Sınav planı", job)
    state = office.state("academic")
    assert state is not None
    assert state.needs_user
    assert state.needs_user_reason == BUDGET
    # the user asked for it: runs anyway
    assert await run_shift(office, "academic", "Sınav planı", job, check_budget=False) == "done"

    snapshot = await office.snapshot()
    academic = next(e for e in snapshot["employees"] if e["id"] == "academic")
    assert academic["spent_today_usd"] == pytest.approx(0.25)
    assert academic["daily_budget_usd"] == pytest.approx(0.2)


async def test_scheduled_job_over_budget_is_not_recorded(
    session: AsyncSession, office: Office
) -> None:
    await spend(session, "agenda", "0.60", dt.datetime.now(dt.UTC))
    sessionmaker = async_sessionmaker(session.bind, expire_on_commit=False)

    message_id = await run_job(
        "followups",
        settings=Settings(_env_file=None),
        sessionmaker=sessionmaker,
        team=example_team(),
        office=office,
    )

    assert message_id is None
    assert not (await session.scalars(select(JobRun))).all()  # may run once the day turns
    assert office.state("agenda").needs_user_reason == BUDGET  # type: ignore[union-attr]


async def test_scheduled_messages_skip_direct_employee_chats(
    session: AsyncSession, office: Office
) -> None:
    main = Conversation(title="ana sohbet")
    session.add(main)
    await session.flush()
    session.add(Conversation(title="Scholar", employee_id="academic"))  # newer, but direct
    await session.commit()

    from app.jobs.runner import _post

    message_id = await _post(session, "Günaydın", "briefing", example_team(), NOW)
    await session.commit()

    message = await session.get(Message, message_id)
    assert message is not None
    assert message.conversation_id == main.id


async def test_scheduled_job_shows_its_employee_working(
    session: AsyncSession, office: Office
) -> None:
    sessionmaker = async_sessionmaker(session.bind, expire_on_commit=False)
    async with office.hub.subscribe() as queue:
        await run_job(
            "followups",
            settings=Settings(_env_file=None),
            sessionmaker=sessionmaker,
            team=example_team(),
            office=office,
        )
        events = drain(queue)

    assert [(e["activity"], e["task"]) for e in events if e["employee_id"] == "agenda"] == [
        ("working", "Bekleyen takipleri soruyor"),
        ("break", None),
    ]


# --- HTTP ---------------------------------------------------------------------------------


@pytest.fixture
async def client(
    session: AsyncSession, office: Office, tmp_path: Path
) -> AsyncIterator[tuple[httpx2.AsyncClient, ScriptedLLM]]:
    llm = ScriptedLLM()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path, app_password=None
    )

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: async_sessionmaker(
        session.bind, expire_on_commit=False
    )
    app.dependency_overrides[get_coordinator] = lambda: Coordinator(
        llm, example_team(), Settings(_env_file=None, upload_dir=tmp_path), office
    )
    app.dependency_overrides[get_office] = lambda: office
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, llm


async def test_snapshot_endpoint(client: tuple[httpx2.AsyncClient, ScriptedLLM]) -> None:
    http, _ = client
    snapshot = (await http.get("/api/office/snapshot")).json()

    assert snapshot["ready"] is True
    assert [(e["id"], e["desk"], e["activity"]) for e in snapshot["employees"]] == [
        ("yaver", {"row": "office", "col": 0}, "break"),
        ("academic", {"row": "back", "col": 0}, "break"),
        ("agenda", {"row": "front", "col": 2}, "break"),
        ("discipline", {"row": "front", "col": 3}, "break"),
        ("career", {"row": "back", "col": 1}, "break"),
        ("startup", {"row": "back", "col": 2}, "break"),
        ("ads", {"row": "back", "col": 3}, "break"),
        ("content", {"row": "front", "col": 0}, "break"),
        ("social", {"row": "front", "col": 1}, "break"),
    ]
    first = snapshot["employees"][1]
    assert (first["name"], first["role"], first["color"]) == ("Scholar", "Akademik", "#4cbcff")
    assert first["spent_today_usd"] == 0
    assert first["daily_budget_usd"] == 0.2


async def test_stream_sends_snapshot_then_changes_and_pings(office: Office) -> None:
    events = office_events(office, ping_seconds=0.05)
    assert await anext(events) == "retry: 3000\n\n"
    snapshot = await anext(events)
    assert snapshot.startswith('data: {"type": "snapshot", "ready": true')

    await office.set_state("academic", Activity.WORKING, task="Günün planına bakıyor")
    change = await anext(events)
    assert change.startswith('data: {"type": "state", "employee_id": "academic"')
    assert '"task": "Günün planına bakıyor"' in change
    # a data event, not a comment: the browser's EventSource only sees data
    assert (await anext(events)).startswith('data: {"type": "ping", "ts": ')
    await events.aclose()
    assert office.hub.subscribers == 0


async def test_employee_chat_notes_and_tasks_endpoints(
    session: AsyncSession, client: tuple[httpx2.AsyncClient, ScriptedLLM]
) -> None:
    http, llm = client
    llm.add("academic", call("add_note", content="EE211 quiz salı"), say("Not aldım."))
    llm.add("academic", say("Defterimde EE211 quiz var."))

    first = await http.post("/api/employees/academic/chat", json={"message": "not al: EE211 quiz"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["speaker"] == "academic"
    assert body["reply"] == "Not aldım."
    conversation = await session.get(Conversation, body["conversation_id"])
    assert conversation is not None
    assert conversation.employee_id == "academic"

    # no conversation_id: the employee's latest direct chat goes on
    second = (await http.post("/api/employees/academic/chat", json={"message": "ne var?"})).json()
    assert second["conversation_id"] == body["conversation_id"]

    # the direct chat is found from the panel, and never taken for the main chat
    found = (await http.get("/api/employees/academic/chat")).json()
    assert found == {"employee_id": "academic", "conversation_id": body["conversation_id"]}
    assert (await http.get("/api/employees/agenda/chat")).json()["conversation_id"] is None
    assert (await http.get("/api/conversations/latest")).json()["conversation_id"] is None

    notes = (await http.get("/api/employees/academic/notes")).json()
    assert [n["content"] for n in notes["notes"]] == ["EE211 quiz salı"]
    tasks = (await http.get("/api/employees/academic/tasks")).json()["tasks"]
    assert [(t["source"], t["instruction"], t["status"]) for t in tasks] == [
        ("user", "ne var?", "done"),
        ("user", "not al: EE211 quiz", "done"),
    ]
    assert tasks[1]["change_set_id"] == body["change_set_id"]
    assert tasks[1]["tools"] == ["add_note"]

    # undo goes through the same endpoint as the main chat
    undone = await http.post(f"/api/changes/{body['change_set_id']}/undo")
    assert undone.status_code == 200
    assert (await http.get("/api/employees/academic/notes")).json()["notes"] == []

    assert (await http.get("/api/employees/nobody/notes")).status_code == 404
    assert (
        await http.post("/api/employees/nobody/chat", json={"message": "selam"})
    ).status_code == 404
    other = await http.post(
        "/api/employees/agenda/chat",
        json={"message": "selam", "conversation_id": body["conversation_id"]},
    )
    assert other.status_code == 422


async def test_employee_chat_stream(
    session: AsyncSession, client: tuple[httpx2.AsyncClient, ScriptedLLM]
) -> None:
    http, llm = client
    llm.add("discipline", call("get_day_plan", date="2026-11-23"), say("Bugün spor yok."))

    response = await http.post("/api/employees/discipline/chat/stream", json={"message": "bugün?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"type": "done"' in response.text
    assert "Bugün spor yok." in response.text
    llm.assert_done()


async def test_changes_mentioning_a_note_are_undoable_via_change_log(
    session: AsyncSession, office: Office
) -> None:
    llm = ScriptedLLM()
    llm.add("discipline", call("add_note", content="Valorant 90 dk"), say("Yazdım."))
    reply = await coordinator_with(llm, office).handle(
        session, "Coach, not al: Valorant 90 dk", now=NOW
    )

    entries = (await session.scalars(select(ChangeLog))).all()
    assert [(e.entity, e.op.value, e.agent_id) for e in entries] == [
        ("employee_notes", "create", "discipline")
    ]
    assert reply.change_set_id == entries[0].change_set_id
    assert isinstance(reply.change_set_id, uuid.UUID)


# --- office hours (O5) --------------------------------------------------------------------


class Clock:
    def __init__(self, at: dt.datetime) -> None:
        self.at = at

    def __call__(self) -> dt.datetime:
        return self.at


def local(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, 23, hour, minute, tzinfo=IST)  # a Monday


@pytest.fixture
async def office_with_hours(session: AsyncSession, database_url: str) -> AsyncIterator[Office]:
    engine = create_async_engine(database_url, connect_args=CONNECT_ARGS)
    config = example_config("08:00", "23:00")
    clock = Clock(local(22, 0))
    office = Office(async_sessionmaker(engine, expire_on_commit=False), config, IST, clock=clock)
    assert await office.start()
    yield office
    await engine.dispose()


async def test_office_hours_send_idle_employees_home_and_bring_them_back(
    office_with_hours: Office,
) -> None:
    office = office_with_hours
    clock = office.clock
    assert isinstance(clock, Clock)
    async with office.hub.subscribe() as queue:
        assert await office.refresh_hours() is False  # 22:00: still open
        clock.at = local(23, 5)
        assert await office.refresh_hours() is True
        closed = drain(queue)
        clock.at = local(8, 0) + dt.timedelta(days=1)
        assert await office.refresh_hours() is False
        opened = drain(queue)

    hours = [e for e in closed if e["type"] == "hours"]
    assert [e["off_hours"] for e in hours] == [True]  # the first look is no event
    assert hours[-1]["open_at"] == "08:00"
    assert hours[-1]["close_at"] == "23:00"
    assert set(activities(closed, "academic")) == {"off"}
    assert {e["employee_id"] for e in closed if e.get("activity") == "off"} == set(office.employees)
    assert activities(opened, "academic") == ["break"]
    assert [e["off_hours"] for e in opened if e["type"] == "hours"] == [False]


async def test_a_request_at_night_is_a_night_shift_then_home_again(
    office_with_hours: Office,
) -> None:
    office = office_with_hours
    clock = office.clock
    assert isinstance(clock, Clock)
    clock.at = local(1, 30)
    await office.refresh_hours()
    office.acquire("agenda")

    working = await office.set_state("agenda", Activity.WORKING, task="Toplantı ekliyor")
    await office.release("agenda")

    assert working is not None
    assert working.activity is Activity.WORKING  # came in for it
    after = office.state("agenda")
    assert after is not None
    assert after.activity is Activity.OFF  # and went home, not to the kitchen
    snapshot = await office.snapshot()
    assert snapshot["hours"] == {"open_at": "08:00", "close_at": "23:00", "off_hours": True}
    assert {e["activity"] for e in snapshot["employees"]} == {"off"}


def test_office_hours_across_midnight_and_always_open(office: Office) -> None:
    late = office.config.model_copy(
        update={
            "office": office.config.office.model_copy(
                update={"open_at": "18:00", "close_at": "02:00"}
            )
        }
    )
    night_office = Office(office.sessionmaker, late, IST)

    assert night_office.off_hours(local(1, 0)) is False
    assert night_office.off_hours(local(2, 0)) is True
    assert night_office.off_hours(local(17, 59)) is True
    assert office.off_hours(local(3, 0)) is False  # open_at == close_at: never closed
