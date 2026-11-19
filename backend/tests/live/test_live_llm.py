"""Real API calls. Excluded from normal runs; run on purpose:

    docker compose exec api pytest -m live -v -s

Each test makes one tool call through the router and checks the spend landed in llm_usage
(the real database from DATABASE_URL, not the test database: this is real money).
Tests whose API key is missing are skipped.
"""

import datetime as dt
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import pool, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.time_resolver import build_calendar_context, format_calendar_context
from app.db.models import LlmUsage
from app.db.session import CONNECT_ARGS
from app.llm.check_models import check_models
from app.llm.config import TierConfig, load_providers_config
from app.llm.router import LLMRouter, build_providers, build_router, env_value
from app.llm.types import ChatMessage, LLMRequest, LLMResponse, ToolSpec
from app.llm.usage import DbUsageStore

pytestmark = pytest.mark.live

GET_DAY_PLAN = ToolSpec(
    name="get_day_plan",
    description="Returns the user's plan for one day. Always call it to answer schedule questions.",
    parameters={
        "type": "object",
        "properties": {"date": {"type": "string", "description": "ISO date, YYYY-MM-DD"}},
        "required": ["date"],
        "additionalProperties": False,
    },
)

SHORT_SYSTEM = (
    "Sen Yaver'sin, kullanıcının program asistanı. Program sorularında her zaman "
    "get_day_plan aracını çağır; tarihi YYYY-MM-DD olarak ver."
)

# Long and byte-identical across calls: big enough for prompt caching (min 512 tokens on
# Claude Haiku 5.5). No dates of "today" in here, or every request would miss the cache.
LONG_SYSTEM = (
    SHORT_SYSTEM
    + "\n\nReferans takvim (sabit, sadece biçim örneği):\n"
    + format_calendar_context(build_calendar_context(dt.date(2026, 1, 5), days=400))
)


def _ask(day: str, system: str = SHORT_SYSTEM) -> LLMRequest:
    return LLMRequest(
        system=system,
        messages=[ChatMessage("user", f"{day} tarihli günümün planını getir.")],
        tools=[GET_DAY_PLAN],
        tool_choice="required",
        max_tokens=512,
    )


def _require_key(env_name: str) -> None:
    if not env_value(get_settings(), env_name):
        pytest.skip(f"{env_name} not set")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        get_settings().database_url, poolclass=pool.NullPool, connect_args=CONNECT_ARGS
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def router(engine: AsyncEngine) -> AsyncIterator[LLMRouter]:
    router = build_router(store=DbUsageStore(async_sessionmaker(engine)))
    yield router
    await router.aclose()


async def _usage_row(engine: AsyncEngine, response: LLMResponse) -> LlmUsage:
    assert response.usage_id is not None, "usage was not recorded"
    async with async_sessionmaker(engine)() as session:
        row = await session.scalar(select(LlmUsage).where(LlmUsage.id == response.usage_id))
    assert row is not None
    return row


def _report(label: str, response: LLMResponse) -> None:
    u = response.usage
    print(
        f"\n{label}: {response.provider}/{response.model} tier={response.tier} "
        f"in={u.input_tokens} cached={u.cached_input_tokens} written={u.cache_write_tokens} "
        f"out={u.output_tokens} cost=${response.cost_usd} {response.latency_ms}ms"
    )


def _assert_day_plan_call(response: LLMResponse, day: str) -> None:
    assert response.tool_calls, f"no tool call; text was: {response.text!r}"
    call = response.tool_calls[0]
    assert call.name == "get_day_plan"
    assert call.arguments == {"date": day}


async def test_groq_tool_call(router: LLMRouter, engine: AsyncEngine) -> None:
    _require_key("GROQ_API_KEY")

    response = await router.complete(
        _ask("2026-11-20"), tier="fast", purpose="live_test", ignore_budget=True
    )

    _report("groq", response)
    assert response.provider == "groq", "fell over to another tier - see llm_usage errors"
    _assert_day_plan_call(response, "2026-11-20")
    row = await _usage_row(engine, response)
    assert (row.provider, row.tier, row.purpose) == ("groq", "fast", "live_test")
    assert row.cost_usd > 0
    assert row.error is None


async def test_claude_haiku_tool_call(router: LLMRouter, engine: AsyncEngine) -> None:
    _require_key("ANTHROPIC_API_KEY")

    response = await router.complete(
        _ask("2026-11-21"), tier="fallback", purpose="live_test", ignore_budget=True
    )

    _report("haiku", response)
    assert response.provider == "anthropic"
    _assert_day_plan_call(response, "2026-11-21")
    row = await _usage_row(engine, response)
    assert row.model == response.model
    assert row.cost_usd > 0


async def test_claude_prompt_cache_hit(router: LLMRouter, engine: AsyncEngine) -> None:
    _require_key("ANTHROPIC_API_KEY")

    first = await router.complete(
        _ask("2026-11-22", LONG_SYSTEM), tier="fallback", purpose="live_test", ignore_budget=True
    )
    second = await router.complete(
        _ask("2026-11-23", LONG_SYSTEM), tier="fallback", purpose="live_test", ignore_budget=True
    )

    _report("haiku #1 (writes cache)", first)
    _report("haiku #2 (reads cache)", second)
    # The first call either wrote the cache or (re-run within 5 min) already read it.
    assert first.usage.cache_write_tokens > 0 or first.usage.cached_input_tokens > 0
    assert second.usage.cached_input_tokens > 0, "no cache hit: something in the prefix changed"
    assert second.usage.cached_input_tokens >= 1000
    row = await _usage_row(engine, second)
    assert row.cached_input_tokens == second.usage.cached_input_tokens


async def test_openrouter_tool_call(engine: AsyncEngine) -> None:
    _require_key("OPENROUTER_API_KEY")
    config = load_providers_config()
    model = config.providers["openrouter"].default_model
    assert model, "set providers.openrouter.default_model in config/providers.yaml"
    tiers = {**config.tiers, "openrouter_live": TierConfig(provider="openrouter", model=model)}
    router = build_router(
        config=config.model_copy(update={"tiers": tiers}),
        store=DbUsageStore(async_sessionmaker(engine)),
    )
    try:
        response = await router.complete(
            _ask("2026-11-24"), tier="openrouter_live", purpose="live_test", ignore_budget=True
        )
    finally:
        await router.aclose()

    _report("openrouter", response)
    assert response.provider == "openrouter"
    _assert_day_plan_call(response, "2026-11-24")
    assert response.usage.reported_cost_usd is not None, "OpenRouter did not report usage.cost"
    row = await _usage_row(engine, response)
    assert row.cost_usd == response.usage.reported_cost_usd.quantize(Decimal("0.000001"))


async def test_configured_models_exist() -> None:
    config = load_providers_config()
    providers = build_providers(config, get_settings())
    try:
        results = await check_models(config, providers)
    finally:
        for provider in providers.values():
            await provider.aclose()

    for result in results:
        print(
            f"\n{result.status} {result.target}: {result.provider}/{result.model} {result.detail}"
        )
    assert not [r for r in results if r.failed]
