"""HTTP API used by the web app: streaming chat, plans, attendance, team, history, undo."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.team import get_team
from app.api.chat import get_coordinator, get_session_factory
from app.db.models import Message, RecurringBlock
from app.db.session import get_session
from app.main import create_app
from tests.agent_fakes import ScriptedLLM, call, coordinator, example_team, say
from tests.db.test_agent_scenarios import week_setup_script


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
async def client(session: AsyncSession, llm: ScriptedLLM) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: async_sessionmaker(
        session.bind, expire_on_commit=False
    )
    app.dependency_overrides[get_coordinator] = lambda: coordinator(llm)
    app.dependency_overrides[get_team] = example_team
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def stream(client: httpx2.AsyncClient, message: str, **extra: Any) -> list[dict[str, Any]]:
    response = await client.post("/api/chat/stream", json={"message": message, **extra})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def test_stream_reports_progress_then_done(
    client: httpx2.AsyncClient, llm: ScriptedLLM, session: AsyncSession
) -> None:
    llm.scripts = week_setup_script().scripts

    events = await stream(client, "Pazartesi 9-11 Linear Algebra ... salı perşembe 19-20 spor")

    kinds = [event["type"] for event in events]
    assert kinds[0] == "turn"
    assert kinds[-1] == "done"
    assert [e["agent_id"] for e in events if e["type"] == "delegate"] == ["academic", "discipline"]
    tools = [e for e in events if e["type"] == "tool" and e["agent_id"] == "academic"]
    assert [t["tool"] for t in tools] == ["add_recurring_block", "add_recurring_block"]
    assert all(t["mutates"] and t["error"] is None for t in tools)
    replies = [e for e in events if e["type"] == "agent_reply"]
    assert [r["name"] for r in replies] == ["Atlas", "Coach"]
    # only the speaker (coordinator) streams text
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert {e["agent_id"] for e in events if e["type"] == "text"} == {"yaver"}
    assert text.strip() == "Atlas derslerini, Coach sporu ekledi."
    done = events[-1]
    assert done["change_set_id"]
    assert {c["entity"] for c in done["changes"]} == {"courses", "recurring_blocks"}
    blocks = [c["data"] for c in done["changes"] if c["entity"] == "recurring_blocks"]
    assert blocks[0] == {
        "title": "Linear Algebra",
        "kind": "class",
        "weekday": 0,
        "start_time": "09:00:00",
        "end_time": "11:00:00",
    }
    assert await session.scalar(select(func.count()).select_from(RecurringBlock)) == 4


async def test_stream_error_saves_nothing(
    client: httpx2.AsyncClient, llm: ScriptedLLM, session: AsyncSession
) -> None:
    llm.add("yaver", call("delegate", agent_id="academic", instruction="x"))  # academic unscripted

    events = await stream(client, "x")

    assert events[-1] == {"type": "error", "code": "internal"}
    assert await session.scalar(select(func.count()).select_from(Message)) == 0


async def test_history_and_undo(client: httpx2.AsyncClient, llm: ScriptedLLM) -> None:
    llm.scripts = week_setup_script().scripts
    done = (await stream(client, "kurulum"))[-1]
    conversation_id = done["conversation_id"]

    history = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    latest = (await client.get("/api/conversations/latest")).json()

    assert latest == {"conversation_id": conversation_id}
    assert [(m["role"], m["agent_id"]) for m in history["messages"]] == [
        ("user", None),
        ("assistant", "academic"),
        ("assistant", "discipline"),
        ("assistant", "yaver"),
    ]
    change_set = history["change_sets"][done["change_set_id"]]
    assert change_set["undone"] is False
    assert len(change_set["changes"]) == 6  # 2 courses + 4 blocks

    undo = await client.post(f"/api/changes/{done['change_set_id']}/undo")
    again = await client.post(f"/api/changes/{done['change_set_id']}/undo")
    after = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()

    assert undo.json()["reverted"] == 6
    assert again.status_code == 404
    assert after["change_sets"][done["change_set_id"]]["undone"] is True
    assert (await client.get("/api/conversations/999/messages")).status_code == 404


async def test_plan_attendance_and_team(client: httpx2.AsyncClient, llm: ScriptedLLM) -> None:
    llm.scripts = week_setup_script().scripts
    await stream(client, "kurulum")

    day = (await client.get("/api/plan/day", params={"date": "2026-11-23"})).json()
    week = (await client.get("/api/plan/week", params={"date": "2026-11-25"})).json()
    default_day = (await client.get("/api/plan/day")).json()
    courses = (await client.get("/api/attendance")).json()["courses"]
    team = (await client.get("/api/team")).json()

    assert [item["title"] for item in day["items"]] == ["Linear Algebra"]
    assert day["weekday"] == "Pazartesi"
    assert week["week_start"] == "2026-11-23"
    assert [len(d["items"]) for d in week["days"]] == [1, 1, 1, 1, 0, 0, 0]
    assert default_day["date"] == default_day["today"]
    assert {c["course"] for c in courses} == {"EE211", "Linear Algebra"}
    assert team["coordinator"]["name"] == "Yaver"
    assert [(a["name"], a["color"]) for a in team["agents"]] == [
        ("Atlas", "#0ea5e9"),
        ("Nova", "#f59e0b"),
        ("Coach", "#10b981"),
    ]


async def test_plain_chat_endpoint_still_works(
    client: httpx2.AsyncClient, llm: ScriptedLLM
) -> None:
    llm.add("yaver", say("Merhaba!"))

    body = (await client.post("/api/chat", json={"message": "selam"})).json()

    assert body["reply"] == "Merhaba!"
    assert body["changes"] == []
