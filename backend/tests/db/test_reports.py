"""The reports tab: per employee requests / cost / failures / handoffs, the routing of each
answer (message -> intents -> employee), handed-back requests with why, open bug reports."""

import datetime as dt
from decimal import Decimal

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.reports import window
from app.db.models import EmployeeTask, LlmUsage
from app.db.models.enums import EmployeeTaskStatus, TaskOrigin
from tests.agent_fakes import ScriptedLLM, route_as, say
from tests.db.test_ads import team_in_office
from tests.db.test_api_web import client, llm, stream  # noqa: F401 (fixtures)

POST = "instagram postu yaz"


def test_the_window_is_a_local_day_or_its_week() -> None:
    sunday = dt.date(2026, 11, 22)
    assert window("day", sunday) == (sunday, sunday)
    assert window("week", sunday) == (dt.date(2026, 11, 16), sunday)


async def test_a_day_of_the_office(
    client: httpx2.AsyncClient,  # noqa: F811
    llm: ScriptedLLM,  # noqa: F811
    session: AsyncSession,
) -> None:
    await team_in_office(session)  # inbox rows need the employees
    llm.add("intent", route_as(("content", POST)))
    llm.add("content", say("Bu benim alanımın dışında."))  # handed back in words
    llm.add("yaver", say("Creator yapamadı."))
    done = (await stream(client, POST))[-1]
    session.add(
        LlmUsage(
            provider="groq", model="m", tier="fast", purpose="chat", agent_id="content",
            cost_usd=Decimal("0.0123"),
        )
    )  # fmt: skip
    now = dt.datetime.now(dt.UTC)
    for status, result in (
        (EmployeeTaskStatus.DONE, "tamam"),
        (EmployeeTaskStatus.FAILED, "model yok"),
    ):
        session.add(
            EmployeeTask(
                employee_id="content", source=TaskOrigin.YAVER, requested_by="yaver",
                instruction=POST, status=status, result=result, started_at=now, created_at=now,
            )
        )  # fmt: skip
    await session.flush()
    await client.post(
        "/api/bug-reports", json={"message_id": done["message_id"], "note": "pes etti"}
    )

    report = (await client.get("/api/reports", params={"period": "day"})).json()

    assert report["period"] == "day"
    creator = next(e for e in report["employees"] if e["id"] == "content")
    assert creator["name"] == "Creator"
    assert (creator["delegated"], creator["failed"]) == (2, 1)
    assert creator["handoffs"] == 1
    assert Decimal(creator["cost_usd"]) >= Decimal("0.0123")
    [row] = report["routing"]
    assert row["text"] == POST
    assert row["intents"] == [["content", "content"]]
    assert row["speaker"] == "yaver"
    assert row["handoffs"] == 1
    failed, problem = sorted(report["problems"], key=lambda p: p["kind"])
    assert (failed["kind"], failed["reason"]) == ("failed", "model yok")
    assert problem["kind"] == "handoff"
    assert problem["agent_id"] == "content"
    assert problem["reason"] == "Bu benim alanımın dışında."
    assert problem["in_words"] is True
    assert report["bugs"]["open"] == 1
    assert report["bugs"]["latest"][0]["note"] == "pes etti"
    assert report["totals"]["handoffs"] == 1

    week = (await client.get("/api/reports", params={"period": "week"})).json()
    assert len(week["routing"]) == 1
    yesterday = (dt.date.fromisoformat(report["from"]) - dt.timedelta(days=1)).isoformat()
    empty = (await client.get("/api/reports", params={"date": yesterday})).json()
    assert empty["routing"] == []
