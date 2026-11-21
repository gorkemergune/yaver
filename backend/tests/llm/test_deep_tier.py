"""The deep tier (Opus): only purposes mapped to it, own monthly limit inside the Claude one.

Fake prices: haiku $1/M, sonnet $10/M, opus $20/M; Claude limit $4, deep limit $2."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.llm.config import ProvidersConfig
from app.llm.router import tier_limits
from app.llm.usage import InMemoryUsageStore, UsageRecord
from tests.llm.fakes import NOW, make_config, make_router, request
from tests.llm.test_config_and_pricing import _example


def deep_config() -> ProvidersConfig:
    return make_config(
        tiers={
            "fast": {"provider": "groq", "model": "fast-model"},
            "fallback": {"provider": "claude", "model": "haiku"},
            "smart": {"provider": "claude", "model": "sonnet"},
            "deep": {"provider": "claude", "model": "opus"},
            "local": {"provider": "ollama", "model": "local-model"},
        },
        routing={
            "default": "fast",
            "failover_chain": ["fast", "fallback"],
            "purposes": {"weekly_plan": "smart", "ads_weekly_report": "deep"},
            "explicit_only": ["deep"],
        },
        budget={
            "provider": "claude",
            "downgrade": {"smart": "fallback", "deep": "fallback"},
            "allowed_at_limit": ["fast", "local"],
            "tier_limits": {
                "deep": {"limit_env": "DEEP_MONTHLY_BUDGET_USD", "over_limit": "smart"}
            },
        },
    )


def router_with(*rows: tuple[str, str, str], deep_limit: str = "2.00") -> Any:
    """rows: (tier, model, usd) already spent on Claude this month."""
    store = InMemoryUsageStore()
    for tier, model, usd in rows:
        store.records.append(
            UsageRecord("claude", model, tier, "x", cost_usd=Decimal(usd), created_at=NOW)
        )
    router, _ = make_router(
        {}, config=deep_config(), limit_usd="4.00", store=store, tier_limits={"deep": deep_limit}
    )
    return router, store


async def test_a_marked_weekly_job_runs_on_opus() -> None:
    router, store = router_with()

    response = await router.complete(request(), purpose="ads_weekly_report")

    assert (response.tier, response.model) == ("deep", "opus")
    assert store.records[-1].tier == "deep"  # its spend is counted per tier


async def test_nothing_else_may_ask_for_the_deep_tier() -> None:
    router, store = router_with()

    with pytest.raises(ValueError, match="only for purposes mapped"):
        await router.complete(request(), purpose="chat", tier="deep")
    with pytest.raises(ValueError, match="only for purposes mapped"):
        await router.complete(request(), purpose="weekly_plan", tier="deep")
    assert store.records == []  # refused before any call


async def test_over_its_own_limit_the_job_runs_on_sonnet() -> None:
    router, _ = router_with(("deep", "opus", "2.00"))  # Claude total 2.00 / 4.00: still OK

    response = await router.complete(request(), purpose="ads_weekly_report")

    assert (response.tier, response.model) == ("smart", "sonnet")


async def test_other_claude_spend_does_not_use_up_the_deep_limit() -> None:
    router, _ = router_with(("smart", "sonnet", "1.90"), ("fallback", "haiku", "0.50"))

    response = await router.complete(request(), purpose="ads_weekly_report")

    assert response.tier == "deep"


async def test_deep_spend_counts_toward_the_claude_budget() -> None:
    # Opus spent 1.00 (under its 2.00), but Claude as a whole is at 85%: the downgrade applies
    router, _ = router_with(("deep", "opus", "1.00"), ("smart", "sonnet", "2.40"))

    status = await router.budget.status()
    response = await router.complete(request(), purpose="ads_weekly_report")

    assert status.spent_usd == Decimal("3.40")
    assert (response.tier, response.model) == ("fallback", "haiku")


async def test_at_the_claude_limit_no_claude_tier_runs() -> None:
    router, _ = router_with(("smart", "sonnet", "4.00"))

    response = await router.complete(request(), purpose="ads_weekly_report")

    assert response.tier == "fast"


async def test_a_zero_limit_means_never_opus() -> None:
    router, _ = router_with(deep_limit="0")

    response = await router.complete(request(), purpose="ads_weekly_report")

    assert response.tier == "smart"


async def test_tier_budgets_report_spend_and_limit() -> None:
    router, _ = router_with(("deep", "opus", "0.75"), ("smart", "sonnet", "1.00"))

    (deep,) = await router.budget.tier_budgets()

    assert (deep.tier, deep.spent_usd, deep.limit_usd, deep.reached, deep.over_limit) == (
        "deep",
        Decimal("0.75"),
        Decimal("2.00"),
        False,
        "smart",
    )


@pytest.mark.parametrize(
    "routing",
    [
        {"default": "deep", "explicit_only": ["deep"]},
        {"default": "fast", "failover_chain": ["fast", "deep"], "explicit_only": ["deep"]},
    ],
)
def test_an_explicit_only_tier_cannot_be_reached_by_default_or_failover(
    routing: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="explicit-only"):
        make_config(
            tiers={
                "fast": {"provider": "groq", "model": "fast-model"},
                "deep": {"provider": "claude", "model": "opus"},
            },
            routing=routing,
            budget={"provider": "claude", "downgrade": {}, "allowed_at_limit": ["fast"]},
        )


def test_the_limit_comes_from_the_env() -> None:
    config = deep_config()

    assert tier_limits(config, Settings(deep_monthly_budget_usd=2.0)) == {"deep": Decimal("2.0")}
    assert tier_limits(config, Settings(deep_monthly_budget_usd=0)) == {"deep": Decimal("0")}


def test_the_example_config_marks_only_the_weekly_jobs_deep() -> None:
    config = ProvidersConfig.model_validate(_example())
    deep = sorted(p for p, tier in config.routing.purposes.items() if tier == "deep")

    assert deep == ["ads_weekly_report", "startup_weekly_review"]
    assert config.tiers["deep"].model == "claude-opus-5-5"
    assert "thinking" not in config.tiers["deep"].options  # Opus 5.5 can't disable it
    assert config.routing.explicit_only == ["deep"]
    assert config.budget.tier_limits["deep"].over_limit == "smart"
