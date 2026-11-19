from decimal import Decimal

import pytest

from app.llm.router import LLMUnavailableError, estimate_tokens, fit_prompt, tool_call_problems
from app.llm.types import ChatMessage, LLMRequest, ProviderError, ToolCall
from tests.llm.fakes import (
    GET_DAY_PLAN,
    FakeProvider,
    bad_request,
    make_config,
    make_router,
    rate_limited,
    request,
    text_reply,
    tool_reply,
    usage,
)

# --- tier selection --------------------------------------------------------------------


async def test_default_tier_is_fast() -> None:
    router, store = make_router({})

    response = await router.complete(request())

    assert (response.tier, response.provider, response.model) == ("fast", "groq", "fast-model")
    assert [r.tier for r in store.records] == ["fast"]


async def test_purpose_picks_the_tier() -> None:
    router, _ = make_router({})

    response = await router.complete(request(), purpose="weekly_plan")

    assert (response.tier, response.model) == ("smart", "sonnet")


async def test_explicit_tier_wins_over_purpose() -> None:
    router, _ = make_router({})

    response = await router.complete(request(), purpose="weekly_plan", tier="local")

    assert response.provider == "ollama"


async def test_unknown_tier_is_an_error() -> None:
    router, _ = make_router({})

    with pytest.raises(ValueError, match="unknown tier"):
        await router.complete(request(), tier="turbo")


def test_failover_chain_goes_one_tier_up() -> None:
    router, _ = make_router({})

    assert router.chain_for("fast") == ["fast", "fallback"]
    assert router.chain_for("fallback") == ["fallback"]
    assert router.chain_for("smart") == ["smart"]


async def test_tier_options_reach_the_provider() -> None:
    config = make_config()
    tiers = {**config.tiers}
    tiers["fallback"] = tiers["fallback"].model_copy(update={"options": {"effort": "low"}})
    claude = FakeProvider("claude")
    router, _ = make_router({"claude": claude}, config=config.model_copy(update={"tiers": tiers}))

    await router.complete(request(), tier="fallback")

    assert claude.calls[0][2] == {"effort": "low"}


# --- failover --------------------------------------------------------------------------


async def test_rate_limit_fails_over_to_next_tier() -> None:
    groq = FakeProvider("groq", [rate_limited("groq")])
    router, store = make_router({"groq": groq})

    response = await router.complete(request())

    assert response.tier == "fallback"
    assert [(r.tier, r.error is not None) for r in store.records] == [
        ("fast", True),
        ("fallback", False),
    ]
    assert store.records[0].cost_usd == 0


async def test_server_error_fails_over() -> None:
    error = ProviderError("groq", "overloaded", retryable=True, status_code=503)
    router, _ = make_router({"groq": FakeProvider("groq", [error])})

    assert (await router.complete(request())).tier == "fallback"


async def test_unconfigured_provider_is_skipped_without_a_usage_row() -> None:
    router, store = make_router({"groq": FakeProvider("groq", configured=False)})

    response = await router.complete(request())

    assert response.tier == "fallback"
    assert [r.tier for r in store.records] == ["fallback"]


async def test_non_retryable_error_is_raised_not_failed_over() -> None:
    claude = FakeProvider("claude")
    router, store = make_router(
        {"groq": FakeProvider("groq", [bad_request("groq")]), "claude": claude}
    )

    with pytest.raises(ProviderError, match="invalid request"):
        await router.complete(request())

    assert claude.calls == []
    assert len(store.records) == 1


async def test_all_tiers_failing_raises_with_every_attempt() -> None:
    router, _ = make_router(
        {
            "groq": FakeProvider("groq", [rate_limited("groq")]),
            "claude": FakeProvider("claude", [rate_limited("claude")]),
        }
    )

    with pytest.raises(LLMUnavailableError) as info:
        await router.complete(request())

    assert len(info.value.attempts) == 2
    assert info.value.attempts[0].startswith("fast:")


# --- invalid tool calls ----------------------------------------------------------------


async def test_one_invalid_tool_call_is_retried_on_the_same_tier() -> None:
    groq = FakeProvider("groq", [tool_reply("delete_everything"), tool_reply()])
    router, store = make_router({"groq": groq})

    response = await router.complete(request())

    assert response.tier == "fast"
    assert response.tool_calls[0].name == "get_day_plan"
    assert len(groq.calls) == 2
    assert store.records[0].error is not None
    assert "unknown tool" in (store.records[0].error or "")


async def test_two_invalid_tool_calls_escalate_to_the_next_tier() -> None:
    groq = FakeProvider("groq", [tool_reply(parse_error="invalid JSON"), tool_reply("nope")])
    router, store = make_router({"groq": groq})

    response = await router.complete(request())

    assert response.tier == "fallback"
    assert [r.tier for r in store.records] == ["fast", "fast", "fallback"]


async def test_provider_rejected_tool_call_is_retried_then_fails_over() -> None:
    rejected = ProviderError(
        "groq",
        "Tool call validation failed",
        retryable=False,
        status_code=400,
        invalid_tool_call=True,
    )
    groq = FakeProvider("groq", [rejected, rejected])
    router, store = make_router({"groq": groq})

    response = await router.complete(request())

    assert response.tier == "fallback"
    assert len(groq.calls) == 2
    assert [
        r.error is not None and r.error.startswith("invalid tool calls") for r in store.records
    ] == [
        True,
        True,
        False,
    ]


async def test_provider_rejected_tool_call_then_success_stays_on_tier() -> None:
    rejected = ProviderError("groq", "x", retryable=False, status_code=400, invalid_tool_call=True)
    router, _ = make_router({"groq": FakeProvider("groq", [rejected, tool_reply()])})

    assert (await router.complete(request())).tier == "fast"


async def test_required_tool_call_missing_counts_as_invalid() -> None:
    groq = FakeProvider("groq", [text_reply("Bilmiyorum"), text_reply("Hâlâ bilmiyorum")])
    router, _ = make_router({"groq": groq, "claude": FakeProvider("claude", [tool_reply()])})

    response = await router.complete(request(required=True))

    assert response.tier == "fallback"


@pytest.mark.parametrize(
    ("call", "problem"),
    [
        (ToolCall("1", "get_day_plan", {"date": "2026-11-20"}), None),
        (ToolCall("1", "get_week_plan", {"date": "x"}), "unknown tool"),
        (ToolCall("1", "get_day_plan", None, "{oops", "invalid JSON"), "invalid JSON"),
        (ToolCall("1", "get_day_plan", {}), "missing date"),
        (ToolCall("1", "get_day_plan", {"date": 20261120}), "date should be string"),
        (
            ToolCall("1", "get_day_plan", {"date": "x", "include_tasks": "yes"}),
            "include_tasks should be boolean",
        ),
    ],
)
def test_tool_call_validation(call: ToolCall, problem: str | None) -> None:
    problems = tool_call_problems([call], [GET_DAY_PLAN], required=False)

    if problem is None:
        assert problems == []
    else:
        assert len(problems) == 1
        assert problem in problems[0]


def test_bool_is_not_an_integer() -> None:
    spec = GET_DAY_PLAN.__class__(
        "t", "", {"type": "object", "properties": {"n": {"type": "integer"}}}
    )

    assert tool_call_problems([ToolCall("1", "t", {"n": True})], [spec], required=False)
    assert not tool_call_problems([ToolCall("1", "t", {"n": 3})], [spec], required=False)


# --- cost accounting -------------------------------------------------------------------


async def test_cost_comes_from_the_price_table() -> None:
    groq = FakeProvider("groq", [text_reply(tokens=usage(1_000_000, 500_000))])
    router, store = make_router({"groq": groq})

    response = await router.complete(request())

    assert response.cost_usd == Decimal("0.15")  # 1M in + 0.5M out at $0.1/M
    assert store.records[0].cost_usd == Decimal("0.15")
    assert response.usage_id == 1
    assert response.latency_ms >= 0


async def test_provider_reported_cost_wins() -> None:
    groq = FakeProvider(
        "groq",
        [text_reply(tokens=usage(1_000_000, 0, reported_cost_usd=Decimal("0.0421")))],
        reports_cost=True,
    )
    router, store = make_router({"groq": groq})

    await router.complete(request())

    assert store.records[0].cost_usd == Decimal("0.042100")


async def test_unknown_model_price_records_zero_cost(caplog: pytest.LogCaptureFixture) -> None:
    config = make_config()
    tiers = {**config.tiers, "fast": config.tiers["fast"].model_copy(update={"model": "new"})}
    router, store = make_router({}, config=config.model_copy(update={"tiers": tiers}))

    await router.complete(request())

    assert store.records[0].cost_usd == 0
    assert "No price for groq/new" in caplog.text


async def test_usage_row_carries_purpose_and_agent() -> None:
    router, store = make_router({})

    await router.complete(request(), purpose="briefing", agent_id="academic")

    record = store.records[0]
    assert (record.purpose, record.agent_id, record.provider, record.model) == (
        "briefing",
        "academic",
        "groq",
        "fast-model",
    )


async def test_failing_usage_store_does_not_break_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, store = make_router({})

    async def broken(record: object) -> int | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "record", broken)

    response = await router.complete(request())

    assert response.text == "ok"
    assert response.usage_id is None


# --- prompt size guard -----------------------------------------------------------------


def _conversation(turns: int, size: int = 3000) -> LLMRequest:
    messages: list[ChatMessage] = []
    for i in range(turns):
        messages.append(ChatMessage("user", f"soru {i} " + "x" * size))
        messages.append(
            ChatMessage(
                "assistant", "", tool_calls=[ToolCall(f"c{i}", "get_day_plan", {"date": "d"})]
            )
        )
        messages.append(ChatMessage("tool", "y" * size, tool_call_id=f"c{i}"))
        messages.append(ChatMessage("assistant", f"cevap {i}"))
    messages.append(ChatMessage("user", "son soru"))
    return LLMRequest(messages=messages, system="s", tools=[GET_DAY_PLAN])


def test_fit_prompt_drops_oldest_whole_turns() -> None:
    long_request = _conversation(10)

    fitted = fit_prompt(long_request, max_tokens=5000)

    assert estimate_tokens(fitted) <= 5000
    assert fitted.messages[0].role == "user"  # never starts with an orphaned tool result
    assert fitted.messages[-1].content == "son soru"
    assert len(fitted.messages) < len(long_request.messages)


def test_fit_prompt_leaves_small_prompts_alone() -> None:
    small = _conversation(1, size=10)

    assert fit_prompt(small, max_tokens=5000) is small
    assert fit_prompt(small, max_tokens=None) is small


async def test_router_trims_for_tiers_with_a_prompt_limit() -> None:
    config = make_config()
    tiers = {**config.tiers}
    tiers["fallback"] = tiers["fallback"].model_copy(update={"max_prompt_tokens": 5000})
    claude = FakeProvider("claude")
    router, _ = make_router({"claude": claude}, config=config.model_copy(update={"tiers": tiers}))

    await router.complete(_conversation(10), tier="fallback")

    sent = claude.calls[0][0]
    assert estimate_tokens(sent) <= 5000
    assert sent.messages[-1].content == "son soru"


async def test_model_override_applies_to_the_requested_tier_only() -> None:
    groq = FakeProvider("groq", [rate_limited("groq")])
    claude = FakeProvider("claude")
    router, store = make_router({"groq": groq, "claude": claude})

    response = await router.complete(request(), model="small-model")

    assert groq.calls[0][1] == "small-model"
    assert claude.calls[0][1] == "haiku"  # failover keeps the fallback tier's own model
    assert [r.model for r in store.records] == ["small-model", "haiku"]
    assert response.model == "haiku"


async def test_model_override_is_dropped_when_the_budget_changes_the_tier() -> None:
    from tests.llm.test_budget import store_with

    claude = FakeProvider("claude")
    router, _ = make_router({"claude": claude}, store=store_with("0.85"))

    await router.complete(request(), tier="smart", model="sonnet-special")

    assert claude.calls[0][1] == "haiku"
