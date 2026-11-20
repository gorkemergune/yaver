"""Live: the attendance conversation that exposed the day-based bug, replayed as is.

docker compose exec api pytest -m live -k attendance -s
"""

import datetime as dt
import re
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.team import get_team
from app.config import get_settings
from app.core.time_resolver import normalize
from app.db.models import Course, Term
from app.llm.config import load_providers_config
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore
from app.services.attendance import course_summary
from tests.db.test_agent_tools import context
from tests.db.test_attendance import WEEK

pytestmark = pytest.mark.live

NOW = dt.datetime(2026, 11, 20, 7, 0, tzinfo=dt.UTC)  # Friday 10:00 Istanbul
MESSAGES = [
    "18 kasımda tkl'ye gitmedim",
    "5 12 17 19 kasımda math221'e gitmedim",
    "2 9 12 16 19 kasımda cse221'e gitmedim",
    "12 19 kasımda ee211'e gitmedim",
]
EXPECTED = {"MATH 221": 8, "CSE 221": 7, "TKL 201": 2, "EE 211": 2}
FORMAL = re.compile(r"\b(siz|size|sizin|sizi)\b|m[iı]s[iı]n[iı]z\b|ebilirsiniz|abilirsiniz")


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    config = load_providers_config()
    fast = config.providers[config.tiers["fast"].provider]
    if fast.api_key_env and not env_value(get_settings(), fast.api_key_env):
        pytest.skip(f"{fast.api_key_env} not set")
    router = build_router(config=config, store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


async def hours(session: AsyncSession) -> dict[str, int]:
    courses = (await session.scalars(select(Course).order_by(Course.code))).all()
    return {c.code: (await course_summary(session, c))["absent_hours"] for c in courses}


async def test_reported_attendance_conversation(session: AsyncSession, router: LLMRouter) -> None:
    session.add(
        Term(name="2026-2027 Güz", start_date=dt.date(2026, 9, 28), end_date=dt.date(2026, 12, 25))
    )
    ctx = context(session, "academic")
    from app.agent.tools import run_tool

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
    await session.commit()

    yaver = Coordinator(router, get_team(), get_settings())
    replies: list[ChatReply] = []
    problems: list[str] = []

    async def send(text: str) -> None:
        reply = await yaver.handle(
            session, text, conversation_id=replies[0].conversation_id if replies else None, now=NOW
        )
        replies.append(reply)
        print(f"\n> {text}\n{reply.reply}")
        for entry in reply.trace:
            print(f"  [{entry['agent_id']}] {entry['tool']}({entry['arguments']})")
        if FORMAL.search(normalize(reply.reply)):
            problems.append(f"'{text}': formal address")

    for text in MESSAGES:
        await send(text)
    first = await hours(session)
    print(f"\nhours after the conversation: {first}")

    for text in MESSAGES:  # the same messages again: nothing may be counted twice
        await send(text)
    again = await hours(session)
    print(f"hours after sending it again: {again}")

    calls = [call for reply in replies for call in reply.llm_calls]
    print(f"LLM calls: {len(calls)}, cost ${sum(c.cost_usd for c in calls)}")
    assert {k: first.get(k) for k in EXPECTED} == EXPECTED
    assert again == first
    assert not problems, problems
