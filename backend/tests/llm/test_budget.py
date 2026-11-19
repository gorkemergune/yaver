"""Budget guard with fake prices: claude haiku $1/M, sonnet $10/M, monthly limit $1."""

import datetime as dt
from decimal import Decimal

import pytest

from app.llm.budget import BudgetLevel
from app.llm.router import LLMUnavailableError
from app.llm.usage import InMemoryUsageStore, UsageRecord
from tests.llm.fakes import (
    NOW,
    FakeProvider,
    make_router,
    rate_limited,
    request,
    text_reply,
    usage,
)


def spent(
    store: InMemoryUsageStore, usd: str, *, provider: str = "claude", when: dt.datetime = NOW
) -> None:
    store.records.append(
        UsageRecord(provider, "haiku", "fallback", "chat", cost_usd=Decimal(usd), created_at=when)
    )


def store_with(usd: str, **kwargs: object) -> InMemoryUsageStore:
    store = InMemoryUsageStore()
    spent(store, usd, **kwargs)  # type: ignore[arg-type]
    return store


@pytest.mark.parametrize(
    ("usd", "level"),
    [
        ("0", BudgetLevel.OK),
        ("0.79", BudgetLevel.OK),
        ("0.80", BudgetLevel.DOWNGRADE),
        ("0.99", BudgetLevel.DOWNGRADE),
        ("1.00", BudgetLevel.LIMIT),
        ("3.50", BudgetLevel.LIMIT),
    ],
)
async def test_levels(usd: str, level: BudgetLevel) -> None:
    router, _ = make_router({}, store=store_with(usd))

    status = await router.budget.status()

    assert status.level is level
    assert status.spent_usd == Decimal(usd)


async def test_below_80_percent_smart_stays_smart() -> None:
    router, _ = make_router({}, store=store_with("0.79"))

    response = await router.complete(request(), purpose="weekly_plan")

    assert (response.tier, response.model) == ("smart", "sonnet")


async def test_at_80_percent_smart_falls_back_to_haiku() -> None:
    router, _ = make_router({}, store=store_with("0.80"))

    response = await router.complete(request(), purpose="weekly_plan")

    assert (response.tier, response.model) == ("fallback", "haiku")


async def test_at_80_percent_fast_and_fallback_are_untouched() -> None:
    router, _ = make_router(
        {"groq": FakeProvider("groq", [rate_limited("groq")])}, store=store_with("0.85")
    )

    response = await router.complete(request())

    assert response.tier == "fallback"  # failover to Haiku still allowed below 100%


@pytest.mark.parametrize("tier", ["smart", "fallback", "fast"])
async def test_at_100_percent_only_fast_runs(tier: str) -> None:
    claude = FakeProvider("claude")
    router, _ = make_router({"claude": claude}, store=store_with("1.00"))

    response = await router.complete(request(), tier=tier)

    assert response.tier == "fast"
    assert claude.calls == []


async def test_at_100_percent_local_is_still_allowed() -> None:
    router, _ = make_router({}, store=store_with("1.20"))

    assert (await router.complete(request(), tier="local")).tier == "local"


async def test_at_100_percent_no_failover_to_claude() -> None:
    claude = FakeProvider("claude")
    router, _ = make_router(
        {"groq": FakeProvider("groq", [rate_limited("groq")]), "claude": claude},
        store=store_with("1.00"),
    )

    with pytest.raises(LLMUnavailableError):
        await router.complete(request())

    assert claude.calls == []


async def test_spend_from_the_router_itself_triggers_the_downgrade() -> None:
    # Each smart call: 30k in + 10k out at $10/M = $0.40. Limit $1.
    sonnet_call = text_reply(tokens=usage(30_000, 10_000))
    claude = FakeProvider("claude", [sonnet_call, text_reply(tokens=usage(30_000, 10_000))])
    router, store = make_router({"claude": claude})

    first = await router.complete(request(), purpose="weekly_plan")
    second = await router.complete(request(), purpose="weekly_plan")
    third = await router.complete(request(), purpose="weekly_plan")

    assert first.cost_usd == Decimal("0.4")
    assert [first.model, second.model] == ["sonnet", "sonnet"]  # $0.40, then $0.80 spent
    assert third.model == "haiku"  # 80% reached
    assert sum(r.cost_usd for r in store.records) >= Decimal("0.8")


async def test_only_the_budget_provider_counts() -> None:
    router, _ = make_router({}, store=store_with("5.00", provider="groq"))

    assert (await router.budget.status()).level is BudgetLevel.OK


async def test_last_month_does_not_count_but_month_starts_in_local_time() -> None:
    store = InMemoryUsageStore()
    # 31 Oct 20:59 UTC = 31 Oct 23:59 Istanbul -> October, ignored
    spent(store, "0.90", when=dt.datetime(2026, 10, 31, 20, 59, tzinfo=dt.UTC))
    # 31 Oct 21:30 UTC = 1 Nov 00:30 Istanbul -> November, counted
    spent(store, "0.30", when=dt.datetime(2026, 10, 31, 21, 30, tzinfo=dt.UTC))
    router, _ = make_router({}, store=store)

    status = await router.budget.status()

    assert status.spent_usd == Decimal("0.30")
    assert status.level is BudgetLevel.OK


async def test_zero_budget_means_no_claude() -> None:
    router, _ = make_router({}, limit_usd="0")

    assert (await router.budget.status()).level is BudgetLevel.LIMIT
    assert (await router.complete(request(), tier="smart")).tier == "fast"


async def test_ignore_budget_for_diagnostics() -> None:
    router, _ = make_router({}, store=store_with("2.00"))

    response = await router.complete(request(), tier="smart", ignore_budget=True)

    assert response.tier == "smart"


def test_ratio() -> None:
    from app.llm.budget import BudgetStatus

    assert BudgetStatus("claude", Decimal(4), Decimal(1), BudgetLevel.OK).ratio == 0.25
    assert BudgetStatus("claude", Decimal(0), Decimal(1), BudgetLevel.LIMIT).ratio is None
