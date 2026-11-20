"""Live: the Sunday weekly plan draft from the smart tier (Sonnet), on a real-like week.

docker compose exec api pytest -m live -k weekly -s
"""

import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.tools import run_tool
from app.config import get_settings
from app.db.models import Proposal
from app.jobs.weekly_plan import draft_week
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore
from tests.db.test_agent_tools import context
from tests.db.test_attendance import WEEK

pytestmark = pytest.mark.live


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    if not env_value(get_settings(), "ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    router = build_router(store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


async def test_weekly_draft(session: AsyncSession, router: LLMRouter) -> None:
    ctx = context(session, "academic")
    for kind, title, course, weekday, start, end in WEEK:
        await run_tool(
            "add_recurring_block",
            {
                "kind": kind,
                "title": title,
                "course": course,
                "weekdays": [weekday],
                "start_time": start,
                "end_time": end,
            },
            ctx,
        )
    setup: list[tuple[str, dict[str, Any]]] = [
        (
            "add_event",
            {
                "kind": "exam",
                "title": "EE 211 Ara Sınav",
                "date": "2026-11-27",
                "start_time": "10:00",
                "course": "EE 211",
            },
        ),
        ("set_absence_limit", {"course": "MATH 221", "hours": 10}),
        (
            "log_attendance",
            {
                "course": "MATH 221",
                "dates": ["2026-11-05", "2026-11-12", "2026-11-17", "2026-11-19"],
            },
        ),
        ("add_followup", {"title": "Hackathon başvuru sonucu"}),
    ]
    for name, args in setup:
        result = await run_tool(name, args, ctx)
        assert "error" not in result, result
    await session.commit()

    drafted = await draft_week(session, router, dt.date(2026, 11, 22), get_settings().tz)

    assert drafted is not None
    message, context_note = drafted
    print(f"\n{message}\n{context_note}")
    proposal = await session.get(Proposal, 1)
    assert proposal is not None
    print(f"parsed by {proposal.parsed_by}")
    assert proposal.parsed_by.startswith("anthropic/claude-sonnet")
    dates = [e["date"] for e in proposal.entries if e["date"]]
    assert all("2026-11-23" <= d <= "2026-11-29" for d in dates), dates
    assert any(
        "ee" in e["title"].lower() or "sınav" in e["title"].lower() for e in proposal.entries
    )
