"""Calendar subscription (.ics): classes with cancellations / moves / holidays applied,
exams and events; a secret token instead of the login."""

import datetime as dt
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.api.chat import get_session_factory
from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.services.calendar_feed import _fold, feed_items, render
from tests.db.test_agent_tools import IST, context

TODAY = dt.date(2026, 11, 20)

SETUP: list[tuple[str, dict[str, Any]]] = [
    ("add_term", {"name": "Güz", "start_date": "2026-09-28", "end_date": "2027-01-15"}),
    ("add_holiday", {"name": "Yılbaşı", "start_date": "2027-01-01"}),
    (
        "add_recurring_block",
        {
            "kind": "class",
            "title": "Linear Algebra",
            "course": "MATH221",
            "weekdays": ["monday", "friday"],
            "start_time": "09:00",
            "end_time": "11:00",
            "location": "B204",
        },
    ),
    (
        "add_recurring_block",
        {
            "kind": "sport",
            "title": "Spor",
            "weekdays": ["tuesday"],
            "start_time": "19:00",
            "end_time": "20:00",
        },
    ),
    ("cancel_block_on", {"date": "2026-11-23", "block": "Linear Algebra"}),
    (
        "move_block_on",
        {
            "date": "2026-11-30",
            "block": "Linear Algebra",
            "new_date": "2026-12-02",
            "new_start_time": "14:00",
            "new_end_time": "16:00",
        },
    ),
    (
        "add_event",
        {
            "kind": "exam",
            "title": "MATH221 Vize",
            "date": "2026-11-27",
            "start_time": "10:00",
            "end_time": "12:00",
        },
    ),
    (
        "add_event",
        {
            "kind": "hackathon",
            "title": "Hackathon, İstanbul",
            "date": "2026-12-05",
            "all_day": True,
        },
    ),
]


async def setup(session: AsyncSession) -> None:
    ctx = context(session, "academic")
    for name, args in SETUP:
        result = await run_tool(name, args, ctx)
        assert "error" not in result, (name, result)
    await session.commit()


async def test_feed_follows_the_plan(session: AsyncSession) -> None:
    await setup(session)
    items = await feed_items(session, TODAY, IST)
    uids = {f.uid for f in items}
    starts = {f.uid: f.item.start for f in items}
    assert "block-2-20261120@yaver" in uids  # the Friday class (one block per weekday)
    linear_mondays = [
        f for f in items if f.item.title == "Linear Algebra" and f.item.start.weekday() == 0
    ]
    assert dt.date(2026, 11, 23) not in {f.item.start.date() for f in linear_mondays}  # cancelled
    assert dt.date(2026, 11, 16) in {f.item.start.date() for f in linear_mondays}
    moved = next(f for f in items if f.item.moved_from is not None)
    assert moved.uid == "block-1-20261130@yaver"  # same id as the original occurrence
    assert moved.item.start == dt.datetime(2026, 12, 2, 14, tzinfo=IST)
    assert not any(
        f.item.start.date() == dt.date(2027, 1, 1) and f.item.title == "Linear Algebra"
        for f in items
    )
    assert not any(f.item.title == "Spor" for f in items)  # weekly sport stays out
    assert not any(
        f.item.start.date() > dt.date(2027, 1, 15) for f in items if f.item.kind == "class"
    )
    assert "event-1@yaver" in uids
    assert starts["event-1@yaver"] == dt.datetime(2026, 11, 27, 10, tzinfo=IST)

    text = render(items, dt.datetime(2026, 11, 20, 9, tzinfo=dt.UTC), "Yaver · Görkem")
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261127T070000Z\r\nDTEND:20261127T090000Z\r\n" in text  # 10:00 Istanbul
    assert "SUMMARY:Hackathon\\, İstanbul" in text
    assert "DTSTART;VALUE=DATE:20261205\r\nDTEND;VALUE=DATE:20261206" in text
    assert "LOCATION:B204" in text
    assert "DESCRIPTION:Ders · Taşındı (önce 30.11 09:00)" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_long_lines_fold() -> None:
    folded = _fold("DESCRIPTION:" + "ğ" * 60)
    assert len(folded) > 1
    assert all(len(part.encode()) <= 75 for part in folded)
    assert all(part.startswith(" ") for part in folded[1:])


@pytest.fixture
async def http(session: AsyncSession, tmp_path: Path) -> Any:
    app = create_app()
    locked = Settings(
        _env_file=None,
        upload_dir=tmp_path,
        app_password=SecretStr("gizli-parola"),
        app_user_name="Görkem",
    )
    app.dependency_overrides[get_settings] = lambda: locked

    async def _session() -> Any:
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_session_factory] = lambda: None
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_secret_url_without_login(http: httpx2.AsyncClient, session: AsyncSession) -> None:
    await setup(session)
    # the URL itself is behind the login
    assert (await http.get("/api/calendar/subscription")).status_code == 401
    assert (
        await http.post("/api/auth/login", json={"password": "gizli-parola"})
    ).status_code == 200
    path = (await http.get("/api/calendar/subscription")).json()["path"]
    assert path.startswith("/api/calendar.ics?token=")
    assert (await http.get("/api/calendar/subscription")).json()["path"] == path  # stable

    http.cookies.clear()  # the phone has no session
    feed = await http.get(path)
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("text/calendar")
    assert "X-WR-CALNAME:Yaver · Görkem" in feed.text
    assert "SUMMARY:MATH221 Vize" in feed.text
    assert (await http.get("/api/calendar.ics?token=wrong")).status_code == 404

    await http.post("/api/auth/login", json={"password": "gizli-parola"})
    new_path = (await http.post("/api/calendar/subscription/rotate")).json()["path"]
    assert new_path != path
    http.cookies.clear()
    assert (await http.get(path)).status_code == 404  # the old URL is dead
    assert (await http.get(new_path)).status_code == 200
