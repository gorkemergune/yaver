"""Fake providers, config and prices for router / budget tests (no network)."""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.llm.budget import BudgetGuard
from app.llm.config import ModelPrice, PriceTable, ProvidersConfig
from app.llm.router import LLMRouter
from app.llm.types import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    ProviderError,
    TextCallback,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from app.llm.usage import InMemoryUsageStore

IST = ZoneInfo("Europe/Istanbul")
NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.UTC)

Step = LLMResponse | ProviderError | Callable[[LLMRequest, str], LLMResponse]


class FakeProvider:
    def __init__(
        self,
        name: str,
        steps: list[Step] | None = None,
        *,
        configured: bool = True,
        reports_cost: bool = False,
        models: list[str] | None = None,
    ) -> None:
        self.name = name
        self.reports_cost = reports_cost
        self._configured = configured
        self.steps = list(steps or [])
        self.calls: list[tuple[LLMRequest, str, dict[str, Any]]] = []
        self.models = models or []
        self.list_error: ProviderError | None = None

    @property
    def configured(self) -> bool:
        return self._configured

    async def complete(
        self,
        request: LLMRequest,
        model: str,
        options: dict[str, Any],
        on_text: TextCallback | None = None,
    ) -> LLMResponse:
        self.calls.append((request, model, options))
        step = self.steps.pop(0) if self.steps else text_reply("ok")
        if isinstance(step, ProviderError):
            raise step
        response = step if isinstance(step, LLMResponse) else step(request, model)
        response.provider, response.model = self.name, model
        if on_text is not None and response.text:
            for word in response.text.split(" "):
                await on_text(word + " ")
        return response

    async def list_models(self) -> list[str]:
        if self.list_error:
            raise self.list_error
        return self.models

    async def has_model(self, model: str) -> bool:
        return model in await self.list_models()

    async def aclose(self) -> None:
        return None


def usage(input_tokens: int = 0, output_tokens: int = 0, **extra: Any) -> TokenUsage:
    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, **extra)


def text_reply(text: str = "ok", tokens: TokenUsage | None = None) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=[],
        stop_reason="end",
        usage=tokens or usage(100, 10),
        provider="",
        model="",
    )


def tool_reply(
    name: str = "get_day_plan",
    arguments: dict[str, Any] | None = None,
    *,
    parse_error: str | None = None,
    tokens: TokenUsage | None = None,
) -> LLMResponse:
    call = ToolCall(
        "call_1",
        name,
        None if parse_error else (arguments if arguments is not None else {"date": "2026-11-20"}),
        parse_error=parse_error,
    )
    return LLMResponse(
        text="",
        tool_calls=[call],
        stop_reason="tool_use",
        usage=tokens or usage(100, 10),
        provider="",
        model="",
    )


def rate_limited(provider: str) -> ProviderError:
    return ProviderError(provider, "rate limited", retryable=True, status_code=429)


def bad_request(provider: str) -> ProviderError:
    return ProviderError(provider, "invalid request", retryable=False, status_code=400)


GET_DAY_PLAN = ToolSpec(
    name="get_day_plan",
    description="Plan for one day",
    parameters={
        "type": "object",
        "properties": {"date": {"type": "string"}, "include_tasks": {"type": "boolean"}},
        "required": ["date"],
    },
)


def request(
    text: str = "Yarın ne var?", *, tools: bool = True, required: bool = False
) -> LLMRequest:
    return LLMRequest(
        system="Sen Yaver'sin.",
        messages=[ChatMessage("user", text)],
        tools=[GET_DAY_PLAN] if tools else [],
        tool_choice="required" if required else "auto",
    )


def make_config(**overrides: Any) -> ProvidersConfig:
    data: dict[str, Any] = {
        "tiers": {
            "fast": {"provider": "groq", "model": "fast-model"},
            "fallback": {"provider": "claude", "model": "haiku"},
            "smart": {"provider": "claude", "model": "sonnet"},
            "local": {"provider": "ollama", "model": "local-model"},
        },
        "providers": {
            "groq": {"type": "openai_compat", "base_url": "http://groq", "api_key_env": "X"},
            "claude": {"type": "anthropic", "api_key_env": "Y"},
            "ollama": {"type": "openai_compat", "base_url": "http://ollama", "optional": True},
        },
        "routing": {
            "default": "fast",
            "failover_chain": ["fast", "fallback"],
            "purposes": {"weekly_plan": "smart"},
            "max_invalid_tool_calls": 2,
        },
        "budget": {
            "provider": "claude",
            "downgrade_at": 0.8,
            "downgrade": {"smart": "fallback"},
            "limit_at": 1.0,
            "allowed_at_limit": ["fast", "local"],
        },
    }
    data.update(overrides)
    return ProvidersConfig.model_validate(data)


# Fake prices, USD per 1M tokens: easy arithmetic in budget tests.
FAKE_PRICES = PriceTable(
    prices={
        "groq": {"fast-model": ModelPrice(input=Decimal("0.1"), output=Decimal("0.1"))},
        "claude": {
            "haiku": ModelPrice(input=Decimal(1), output=Decimal(1)),
            "sonnet": ModelPrice(input=Decimal(10), output=Decimal(10)),
        },
        "ollama": {"*": ModelPrice(input=Decimal(0), output=Decimal(0))},
    }
)


def make_router(
    providers: dict[str, FakeProvider],
    *,
    config: ProvidersConfig | None = None,
    limit_usd: str = "1.00",
    store: InMemoryUsageStore | None = None,
) -> tuple[LLMRouter, InMemoryUsageStore]:
    config = config or make_config()
    store = store or InMemoryUsageStore()
    for name in config.providers:
        providers.setdefault(name, FakeProvider(name))
    budget = BudgetGuard(config.budget, Decimal(limit_usd), store, IST, clock=lambda: NOW)
    return LLMRouter(config, providers, FAKE_PRICES, store, budget), store
