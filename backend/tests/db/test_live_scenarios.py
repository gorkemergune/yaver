"""Live end-to-end scenarios through the real router (Groq "fast" tier, failover to Haiku).

    docker compose exec api pytest -m live -k scenarios -v -s

Runs on the TEST database (domain data is wiped per run). "Today" is pinned to Monday
23 Nov 2026 10:00 Istanbul so the five messages have a well-defined meaning.
Prints, per message: reply, yavers, tool actions, tier/provider/cost per LLM call, and at
the end the failover rate and invalid tool calls, so prompt changes can be compared.
"""

import datetime as dt
import logging
import os
import re
import time
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.reply import dedupe_questions
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
    config = load_providers_config()
    fast = config.providers[config.tiers["fast"].provider]  # Groq or, with own key, Claude
    if fast.api_key_env and not env_value(get_settings(), fast.api_key_env):
        pytest.skip(f"{fast.api_key_env} not set")
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


async def test_live_scenarios(
    session: AsyncSession, router: LLMRouter, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.agent.coordinator")
    coordinator = Coordinator(router, get_team(), get_settings())
    replies: list[ChatReply] = []

    durations: list[float] = []
    all_problems: list[str] = []

    async def send(step: str, text: str) -> ChatReply:
        started = time.monotonic()
        reply = await coordinator.handle(
            session, text, conversation_id=replies[0].conversation_id if replies else None, now=NOW
        )
        durations.append(time.monotonic() - started)
        replies.append(reply)
        _report(step, reply)
        problems = _reply_problems(reply)
        print(f"  reply checks: {problems or 'ok'}")
        all_problems.extend(f"{step}: {p}" for p in problems)
        print(f"  took {durations[-1]:.1f}s")
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
        out_of_area = [
            (a["agent_id"], a["tool"])
            for a in second.actions
            if a["tool"] == "add_event" and a["agent_id"] != "agenda"
        ]
        all_problems.extend(f"2: {agent} did {tool} (not its part)" for agent, tool in out_of_area)

        # 3) attendance on a day without that class: nothing written, the nearest past
        #    class day is suggested (EE211 lab is on Wednesdays)
        third = await send("3", "Geçen salı EE211'e gitmedim")
        assert await _count(session, Attendance) == 0
        assert third.change_set_id is None
        assert "18 kasim" in normalize(third.reply), third.reply

        # 3b) the user confirms the suggested day: recorded in class hours, not asked again
        confirmed = await send("3b", "Evet, çarşamba")
        attendance = (await session.scalars(select(Attendance))).all()
        print(f"  DB attendance: {[(a.date, a.status.value, a.hours) for a in attendance]}")
        assert [(a.date, a.status.value, a.hours) for a in attendance] == [
            (dt.date(2026, 11, 18), "absent", 2)
        ]
        assert confirmed.change_set_id is not None

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
        await _summary(session, replies, durations)
        repeats = [r for r in caplog.records if "repeated question" in r.getMessage()]
        print(f"repeated questions removed by code (prompt missed them): {len(repeats)}")
        for record in repeats:
            print(f"  {record.getMessage()}")
    assert not all_problems, all_problems


# Tools whose result tells what is on a day (log_attendance warns when nothing is).
PLAN_TOOLS = {"get_day_plan", "get_week_plan", "cancel_block_on", "move_block_on", "log_attendance"}


def _reply_problems(reply: ChatReply) -> list[str]:
    """The quality rules of the prompts, checked on real model output."""
    problems = []
    team = get_team()
    names = {member.name for member in [team.coordinator, *team.agents]}
    checked = {entry["agent_id"] for entry in reply.trace if entry["tool"] in PLAN_TOOLS}
    for agent in reply.agents:
        # "spor yok", "ders görünmüyor" - not idioms like "kaçmak yok"
        says_none = re.search(
            r"\b(ders|spor|blok|etkinlik|toplanti|plan|program)\w*\b[^.!?]{0,40}"
            r"\b(yok|bulunmuyor|gorunmuyor)\b",
            normalize(agent["reply"]),
        )
        if says_none and agent["agent_id"] not in checked:
            problems.append(f"{agent['name']} said 'yok' without checking the plan")
    final = normalize(reply.reply)
    if dedupe_questions(reply.reply) != reply.reply:
        problems.append("a question is repeated")
    for name in names:
        n = re.escape(normalize(name))
        mixed = re.search(rf"\b{n} icin [^.?]*\b(bana|soylersen)\b", final) or re.search(
            rf"\b{n}\b[^.?!]*(memi|mami)\b[^.?!]*\bsordu", final
        )
        if re.search(rf"\b{n} olarak\b", final) or mixed:
            problems.append(f"broken voice around {name}")
    english = {"the", "you", "your", "and", "was", "has", "have", "added", "cancelled", "would"}
    if len(english & set(re.findall(r"[a-z]+", reply.reply.lower()))) >= 3:
        problems.append("answer is in English")
    if not reply.agents and reply.actions and any(f"{name}:" in reply.reply for name in names):
        problems.append("own (fast path) work credited to a yaver")
    return problems


async def _summary(session: AsyncSession, replies: list[ChatReply], durations: list[float]) -> None:
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
    for (tier, provider), group in _group(rows).items():
        cost = sum((r.cost_usd for r in group), Decimal(0))
        print(
            f"  {tier}/{provider}: {len(group)} attempts, ${cost},"
            f" input {sum(r.input_tokens for r in group)}"
            f" + cache read {sum(r.cached_input_tokens for r in group)}"
            f" + cache write {sum(r.cache_write_tokens for r in group)},"
            f" output {sum(r.output_tokens for r in group)}"
        )
    latencies = sorted(r.latency_ms for r in rows if r.latency_ms is not None and not r.error)
    if latencies:
        print(
            f"LLM call latency: median {latencies[len(latencies) // 2]} ms, max {latencies[-1]} ms"
        )
    steps = ", ".join(f"{d:.1f}s" for d in durations)
    print(f"message wall time: {sum(durations):.1f}s total ({steps})")


def _group(rows: Sequence[LlmUsage]) -> dict[tuple[str, str], list[LlmUsage]]:
    groups: dict[tuple[str, str], list[LlmUsage]] = {}
    for row in rows:
        groups.setdefault((row.tier, row.provider), []).append(row)
    return groups
