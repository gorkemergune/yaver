"""👎 "Hatalı": a report of a wrong answer keeps the message, the answer, who answered,
the tools with their errors, the routing and the log lines of those seconds."""

import logging

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import github as github_tools
from app.core import recent_logs
from app.db.models import BugReport, Message
from app.db.models.enums import MessageRole
from tests.agent.test_github_tools import settings as github_settings
from tests.agent_fakes import ScriptedLLM, call, route_as, say
from tests.db.test_api_web import client, llm, stream  # noqa: F401 (fixtures)
from tests.github_fake import FakeGitHub

TEXT = "nexa toplantısı için week3 taslağı hazırla"


async def test_the_answer_keeps_its_meta(
    client: httpx2.AsyncClient,  # noqa: F811
    llm: ScriptedLLM,  # noqa: F811
    session: AsyncSession,
) -> None:
    llm.add("intent", route_as(("content", "instagram postu yaz")))
    llm.add("content", say("Bu benim alanımın dışında."))
    llm.add("yaver", say("Kimse yapamadı."))

    events = await stream(client, "instagram postu yaz")

    done = events[-1]
    assert done["type"] == "done"
    answer = await session.get(Message, done["message_id"])
    assert answer is not None
    assert answer.role is MessageRole.ASSISTANT
    meta = answer.meta or {}
    assert meta["intents"] == [["content", "content"]]
    assert meta["speaker"] == "yaver"
    [handoff] = meta["handoffs"]
    assert handoff == {
        "agent_id": "content",
        "tool": "handoff",
        "area": "",
        "reason": "Bu benim alanımın dışında.",
        "in_words": True,
    }
    assert any(s["tool"] == "delegate" and s.get("routed") for s in meta["trace"])


async def test_a_report_takes_everything_from_the_stored_answer(
    client: httpx2.AsyncClient,  # noqa: F811
    llm: ScriptedLLM,  # noqa: F811
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github_tools, "client_factory", FakeGitHub().factory())
    monkeypatch.setattr(github_tools, "get_settings", github_settings)
    recent_logs.clear()
    recent_logs.install()
    llm.add("intent", route_as(("startup", TEXT)))
    llm.add("startup", call("github_week_summary", week=99, repo="nope"), say("Yapamadım."))
    llm.add("yaver", say("Venture yapamadı."))
    done = (await stream(client, TEXT))[-1]
    logging.getLogger("app.agent.test").warning("something odd while answering")

    response = await client.post(
        "/api/bug-reports",
        json={"message_id": done["message_id"], "note": "repo'ya bakmadı", "source": "desktop"},
    )

    assert response.status_code == 201, response.text
    report = response.json()
    assert report["user_text"] == TEXT
    assert report["reply_text"] == "Venture yapamadı."
    assert report["agent_id"] == "yaver"
    assert report["note"] == "repo'ya bakmadı"
    assert report["source"] == "desktop"
    assert report["intents"] == [["startup", "startup"]]
    # a delegated employee's tools come before the delegate step that returned them
    assert [t["tool"] for t in report["tools"]] == ["github_week_summary", "delegate"]
    assert "something odd while answering" in report["log_summary"]

    listed = (await client.get("/api/bug-reports")).json()
    assert listed["open"] == 1
    assert listed["reports"][0]["id"] == report["id"]


async def test_a_failed_answer_is_reported_with_what_the_client_has(
    client: httpx2.AsyncClient,  # noqa: F811
    session: AsyncSession,
) -> None:
    response = await client.post(
        "/api/bug-reports",
        json={"note": "cevap gelmedi", "user_text": "yarın ne var", "error": "timeout"},
    )

    assert response.status_code == 201
    [row] = (await session.scalars(select(BugReport))).all()
    assert (row.user_text, row.errors, row.message_id) == ("yarın ne var", ["timeout"], None)


async def test_only_an_answer_can_be_reported(
    client: httpx2.AsyncClient,  # noqa: F811
) -> None:
    response = await client.post("/api/bug-reports", json={"message_id": 999999, "note": "x"})
    assert response.status_code == 404
