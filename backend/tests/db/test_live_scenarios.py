"""Live end-to-end scenarios through the real router (Groq "fast" tier, failover to Haiku).

    docker compose exec api pytest -m live -k scenarios -v -s

Runs on the TEST database (domain data is wiped per run). "Today" is pinned to Monday
23 Nov 2026 10:00 Istanbul so the five messages have a well-defined meaning.
Prints, per message: reply, yavers, tool actions, tier/provider/cost per LLM call, and at
the end the failover rate and invalid tool calls, so prompt changes can be compared.
"""

import datetime as dt
import os
from collections import Counter
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.team import get_team
from app.config import get_settings
from app.core.time_resolver import normalize
from app.db.models import Attendance, BlockOverride, Course, Event, LlmUsage, RecurringBlock
from app.db.models.enums import BlockKind, OverrideAction
from app.llm.config import load_providers_config
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore

pytestmark = pytest.mark.live

NOW = dt.datetime(2026, 11, 23, 7, 0, tzinfo=dt.UTC)  # Monday 10:00 Istanbul
IST_OFFSET = dt.timedelta(hours=3)


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    if not env_value(get_settings(), "GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not set")
    config = load_providers_config()
    # Measurement mode: LIVE_RATE_LIMIT_WAIT=30 waits out Groq's per-minute limits instead
    # of failing over, so tool-call accuracy of the Groq models is measured on its own.
    wait = os.environ.get("LIVE_RATE_LIMIT_WAIT")
    if wait:
        routing = config.routing.model_copy(
            update={"rate_limit_max_wait_seconds": float(wait), "rate_limit_max_waits": 20}
        )
        config = config.model_copy(update={"routing": routing})
    router = build_router(config=config, store=DbUsageStore(async_sessionmaker(session.bind)))
    if wait:
        router.wait_limits = dict.fromkeys(config.providers, float(wait))
    yield router
    await router.aclose()


def _report(step: str, reply: ChatReply) -> None:
    print(f"\n=== {step}")
    print(f"reply ({reply.speaker}): {reply.reply}")
    for agent in reply.agents:
        print(f"  {agent['name']}: {agent['reply']}")
    for entry in reply.trace:
        error = f"  -> ERROR {entry['error']}" if entry["error"] else ""
        print(f"  call [{entry['agent_id']}] {entry['tool']}({entry['arguments']}){error}")
    for action in reply.actions:
        print(f"  action [{action['agent_id']}] {action['tool']}: {action['result']}")
    for call in reply.llm_calls:
        print(
            f"  llm {call.agent_id:<10} tier={call.tier:<8} {call.provider}/{call.model} "
            f"tool_calls={call.tool_calls} ${call.cost_usd}"
        )
    print(f"  cost: ${reply.cost_usd}  change_set: {reply.change_set_id}")


async def _count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_live_scenarios(session: AsyncSession, router: LLMRouter) -> None:
    coordinator = Coordinator(router, get_team(), get_settings())
    replies: list[ChatReply] = []

    async def send(step: str, text: str) -> ChatReply:
        reply = await coordinator.handle(
            session, text, conversation_id=replies[0].conversation_id if replies else None, now=NOW
        )
        replies.append(reply)
        _report(step, reply)
        return reply

    try:
        # 1) weekly schedule
        await send(
            "1", "Pazartesi 9-11 Linear Algebra, Çarşamba 13-15 EE211 lab, salı perşembe 19-20 spor"
        )
        blocks = (await session.scalars(select(RecurringBlock))).all()
        found = sorted((b.weekday, b.start_time, b.end_time, b.kind) for b in blocks)
        print(f"  DB blocks: {found}")
        assert (0, dt.time(9), dt.time(11), BlockKind.CLASS) in found
        assert (2, dt.time(13), dt.time(15), BlockKind.LAB) in found
        assert (1, dt.time(19), dt.time(20), BlockKind.SPORT) in found
        assert (3, dt.time(19), dt.time(20), BlockKind.SPORT) in found
        assert len(blocks) == 4
        codes = [normalize(c) for c in (await session.scalars(select(Course.code))).all()]
        assert any("ee211" in c.replace(" ", "") for c in codes), codes

        # 2) mixed message for three yavers
        second = await send(
            "2", "Bugün linear iptal, yarın 14'te Iceberg toplantısı var, akşam spora gidemem"
        )
        overrides = (await session.scalars(select(BlockOverride))).all()
        print(f"  DB overrides: {[(o.date, o.action.value, o.block_id) for o in overrides]}")
        linear = next(b for b in blocks if b.weekday == 0)
        tuesday_sport = next(b for b in blocks if b.weekday == 1)
        found_overrides = {(o.block_id, o.date, o.action) for o in overrides}
        assert (linear.id, dt.date(2026, 11, 23), OverrideAction.CANCEL) in found_overrides
        # "akşam spora gidemem" after "yarın 14'te ...": there is no sport today (Monday);
        # acceptable: ask back (no change) or read it as tomorrow evening (Tuesday sport).
        # Anything else (another day, another block) is a guess.
        others = found_overrides - {(linear.id, dt.date(2026, 11, 23), OverrideAction.CANCEL)}
        assert others in (
            set(),
            {(tuesday_sport.id, dt.date(2026, 11, 24), OverrideAction.CANCEL)},
        ), others
        print(f"  sport reading: {'asked back' if not others else 'tomorrow evening (Tuesday)'}")
        sport_cancelled_tomorrow = bool(others)
        events = (await session.scalars(select(Event))).all()
        print(f"  DB events: {[(e.title, e.start_at + IST_OFFSET) for e in events]}")
        assert len(events) == 1
        assert "iceberg" in normalize(events[0].title)
        assert events[0].start_at == dt.datetime(2026, 11, 24, 11, 0, tzinfo=dt.UTC)
        assert second.change_set_id is not None

        # 3) attendance in the past
        third = await send("3", "Geçen salı EE211'e gitmedim")
        attendance = (await session.scalars(select(Attendance))).all()
        print(f"  DB attendance: {[(a.date, a.status.value) for a in attendance]}")
        assert [(a.date, a.status.value) for a in attendance] == [(dt.date(2026, 11, 17), "absent")]
        assert third.change_set_id is not None

        # 4) read-only question
        fourth = await send("4", "Yarın ne var?")
        answer = normalize(fourth.reply)
        assert "iceberg" in answer, fourth.reply
        if not sport_cancelled_tomorrow:
            assert "spor" in answer, fourth.reply
        assert fourth.change_set_id is None

        # 5) undo the last change (the attendance)
        await send("5", "Son değişikliği geri al")
        assert await _count(session, Attendance) == 0
        assert await _count(session, Event) == 1
        assert await _count(session, BlockOverride) == len(found_overrides)
    finally:
        await _summary(session, replies)


async def _summary(session: AsyncSession, replies: list[ChatReply]) -> None:
    calls = [call for reply in replies for call in reply.llm_calls]
    rows = (await session.scalars(select(LlmUsage).order_by(LlmUsage.id))).all()
    errors = [row for row in rows if row.error]
    by_tier = Counter(call.tier for call in calls)
    failovers = sum(1 for call in calls if call.tier != "fast")
    invalid = [row for row in errors if row.error and row.error.startswith("invalid tool calls")]
    provider_errors = [row for row in errors if row not in invalid]
    total = sum((row.cost_usd for row in rows), Decimal(0))
    print("\n=== summary")
    print(f"LLM calls answered: {len(calls)} by tier {dict(by_tier)}")
    print(f"by model: {dict(Counter(call.model for call in calls))}")
    rate_limited = [row for row in errors if row.error and "429" in row.error]
    print(f"429s: {len(rate_limited)} (short ones waited out on the same tier)")
    rate = failovers / len(calls) if calls else 0
    print(f"failover rate: {failovers}/{len(calls)} = {rate:.0%}")
    print(f"invalid tool-call attempts: {len(invalid)}; provider errors: {len(provider_errors)}")
    for row in errors:
        print(f"  [{row.tier}/{row.provider}] {row.error}")
    print(f"total cost: ${total} over {len(rows)} attempts")
