"""Screen time from the desktop app: POST /api/screen-time, Karen's tool, the check-in line."""

from typing import Any

import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.config import Settings
from app.db.models import ScreenTimeDay
from app.services.screen_time import checkin_line, fmt_minutes
from tests.db.test_agent_tools import context
from tests.db.test_api_web import client, llm  # noqa: F401 - fixtures
from tests.db.test_jobs import at, job, settings, week  # noqa: F401 - fixtures


def day(date: str, valorant: int, code: int = 1200) -> dict[str, Any]:
    return {
        "date": date,
        "apps": [
            {"exe": "Code.exe", "name": "Visual Studio Code", "seconds": code},
            {"exe": "VALORANT-Win64-Shipping.exe", "name": "VALORANT", "seconds": valorant},
        ],
        "limits": [{"name": "VALORANT", "used_seconds": valorant, "limit_seconds": 5400}],
    }


def test_formats() -> None:
    assert fmt_minutes(59) == "0 dk"
    assert fmt_minutes(300) == "5 dk"
    assert fmt_minutes(3600) == "1 saat"
    assert fmt_minutes(4320) == "1 saat 12 dk"
    summary = {
        "total_seconds": 18720,
        "apps": [{"name": "VALORANT", "seconds": 4200}],
        "limits": [{"name": "VALORANT", "used_seconds": 4200, "limit_seconds": 5400}],
    }
    assert checkin_line(summary) == (
        "bugün 5 saat 12 dk ekran, 1 saat 10 dk VALORANT (sınır 1 saat 30 dk)"
    )
    summary["limits"] = []
    assert checkin_line(summary) == "bugün 5 saat 12 dk ekran, en çok VALORANT (1 saat 10 dk)"
    summary["limits"] = [{"name": "VALORANT", "used_seconds": 6000, "limit_seconds": 5400}]
    assert "(sınır 1 saat 30 dk, aşıldı)" in str(checkin_line(summary))
    assert checkin_line({"total_seconds": 20, "apps": [], "limits": []}) is None


async def test_post_is_idempotent_per_device_and_day(
    client: httpx2.AsyncClient,  # noqa: F811
    session: AsyncSession,
) -> None:
    body = {"device": "GORKEM-PC", "days": [day("2026-11-22", 600), day("2026-11-23", 1800)]}
    for _ in range(2):  # a resend after a lost response
        response = await client.post("/api/screen-time", json=body)
        assert response.status_code == 200
        assert response.json() == {"saved": ["2026-11-22", "2026-11-23"]}
    assert await session.scalar(select(func.count()).select_from(ScreenTimeDay)) == 2

    # later in the day: the whole day is sent again, the row is replaced
    later = {"device": "GORKEM-PC", "days": [day("2026-11-23", 4200)]}
    assert (await client.post("/api/screen-time", json=later)).status_code == 200
    # a second computer adds up
    laptop = {"device": "LAPTOP", "days": [day("2026-11-23", 0, code=600)]}
    assert (await client.post("/api/screen-time", json=laptop)).status_code == 200

    summary = (await client.get("/api/screen-time/2026-11-23")).json()
    assert summary["total_seconds"] == 4200 + 1200 + 600
    assert summary["apps"][0] == {
        "exe": "VALORANT-Win64-Shipping.exe",
        "name": "VALORANT",
        "seconds": 4200,
    }
    assert summary["apps"][1]["seconds"] == 1800  # Code.exe on both
    assert summary["limits"] == [{"name": "VALORANT", "used_seconds": 4200, "limit_seconds": 5400}]
    assert summary["devices"] == ["GORKEM-PC", "LAPTOP"]
    empty = (await client.get("/api/screen-time/2026-11-01")).json()
    assert empty["total_seconds"] == 0


async def test_bad_payloads_are_rejected(client: httpx2.AsyncClient) -> None:  # noqa: F811
    bad = [
        {"days": []},
        {"days": [{"date": "2026-11-23", "apps": [{"exe": "a", "name": "a", "seconds": -1}]}]},
        {"days": [{"date": "23.11.2026"}]},
        {"days": [{"date": "2026-11-23", "total_seconds": 10**7}]},
    ]
    for body in bad:
        assert (await client.post("/api/screen-time", json=body)).status_code == 422, body


async def test_karens_tool(session: AsyncSession) -> None:
    session.add(
        ScreenTimeDay(
            device="pc",
            date=at(23, 0).date(),
            total_seconds=5400,
            apps=day("2026-11-23", 4200)["apps"][::-1],
            limits=day("2026-11-23", 4200)["limits"],
        )
    )
    await session.commit()
    result = await run_tool(
        "get_screen_time", {"date": "2026-11-23", "days": 2}, context(session, "discipline")
    )
    first, second = result["screen_time"]
    assert first == {"date": "2026-11-22", "data": "none (desktop app not running?)"}
    assert second["total"] == "1 saat 30 dk"
    assert second["apps"] == ["VALORANT: 1 saat 10 dk", "Visual Studio Code: 20 dk"]
    assert second["limits"] == ["VALORANT: 1 saat 10 dk / 1 saat 30 dk"]


async def test_checkin_mentions_screen_time(
    week: AsyncSession,  # noqa: F811
    settings: Settings,  # noqa: F811
) -> None:
    week.add(
        ScreenTimeDay(
            device="pc",
            date=at(23, 0).date(),
            total_seconds=18720,
            apps=day("2026-11-23", 4200)["apps"],
            limits=day("2026-11-23", 4200)["limits"],
        )
    )
    await week.commit()
    checkin = await job(week, settings, "checkin", at(23, 21))
    assert checkin is not None
    assert (
        "· Ekran: bugün 5 saat 12 dk ekran, 1 saat 10 dk VALORANT (sınır 1 saat 30 dk)."
        in checkin.content
    )
