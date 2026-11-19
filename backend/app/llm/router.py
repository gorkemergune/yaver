"""The only entry point for LLM calls (CLAUDE.md: no direct SDK calls elsewhere).

complete() picks a tier (explicit, or from the purpose), applies the budget guard, then walks
the failover chain:
- 429 with a retry-after <= rate_limit_max_wait_seconds -> wait and retry the same tier
  (at most rate_limit_max_waits times); longer waits fail over
- retryable provider errors (429, 5xx, network, provider not configured) -> next tier
- invalid tool calls `max_invalid_tool_calls` times on one tier -> next tier
- other errors (400, 401, ...) are raised
Every attempt, failed or not, is written to llm_usage with its cost.
"""

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from functools import lru_cache
from typing import Any

from pydantic import SecretStr

from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.llm.budget import BudgetGuard, BudgetLevel, BudgetStatus
from app.llm.config import (
    PriceTable,
    ProviderConfig,
    ProvidersConfig,
    TierConfig,
    load_price_table,
    load_providers_config,
)
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.base import Provider
from app.llm.providers.openai_compat import OpenAICompatProvider
from app.llm.types import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ProviderNotConfiguredError,
    ToolCall,
    ToolSpec,
)
from app.llm.usage import DbUsageStore, UsageRecord, UsageStore, compute_cost

logger = logging.getLogger(__name__)

# Rough token estimate for trimming (Turkish text averages ~3 characters per token).
CHARS_PER_TOKEN = 3


class LLMUnavailableError(Exception):
    def __init__(self, attempts: list[str]) -> None:
        super().__init__("no tier could answer: " + "; ".join(attempts))
        self.attempts = attempts


def _matches_json_type(value: Any, type_name: str | list[str]) -> bool:
    if isinstance(type_name, list):  # ["string", "null"]
        return any(_matches_json_type(value, t) for t in type_name)
    if type_name == "null":
        return value is None
    if type_name in ("integer", "number") and isinstance(value, bool):
        return False  # bool is an int subclass in Python, not in JSON
    expected: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list,),
        "object": (dict,),
    }
    return isinstance(value, expected[type_name]) if type_name in expected else True


def tool_call_problems(
    calls: list[ToolCall], tools: list[ToolSpec], *, required: bool
) -> list[str]:
    """Light validation: known tool, JSON object, required keys, top-level types."""
    if required and not calls:
        return ["a tool call was required but none was made"]
    specs = {tool.name: tool for tool in tools}
    problems: list[str] = []
    for call in calls:
        spec = specs.get(call.name)
        if spec is None:
            problems.append(f"unknown tool {call.name!r}")
            continue
        if call.arguments is None:
            problems.append(f"{call.name}: {call.parse_error or 'unparseable arguments'}")
            continue
        missing = [key for key in spec.parameters.get("required", []) if key not in call.arguments]
        if missing:
            problems.append(f"{call.name}: missing {', '.join(missing)}")
        properties: dict[str, Any] = spec.parameters.get("properties", {})
        for key, value in call.arguments.items():
            type_name = properties.get(key, {}).get("type", "")
            if not _matches_json_type(value, type_name):
                problems.append(f"{call.name}: {key} should be {type_name}")
    return problems


def estimate_tokens(request: LLMRequest) -> int:
    chars = len(request.system or "") + len(request.system_suffix or "")
    chars += sum(len(json.dumps(tool.parameters)) + len(tool.description) for tool in request.tools)
    for message in request.messages:
        chars += len(message.content)
        chars += sum(len(call.arguments_json()) for call in message.tool_calls)
    return chars // CHARS_PER_TOKEN


def fit_prompt(request: LLMRequest, max_tokens: int | None) -> LLMRequest:
    """Drop the oldest whole turns until the estimate fits; the last user turn is kept."""
    if max_tokens is None or estimate_tokens(request) <= max_tokens:
        return request
    starts = [i for i, m in enumerate(request.messages) if m.role == "user"]
    trimmed = request
    for start in starts[1:]:
        trimmed = replace(request, messages=request.messages[start:])
        if estimate_tokens(trimmed) <= max_tokens:
            break
    logger.warning(
        "Prompt ~%d tokens > %d: dropped %d old messages (now ~%d tokens)",
        estimate_tokens(request),
        max_tokens,
        len(request.messages) - len(trimmed.messages),
        estimate_tokens(trimmed),
    )
    return trimmed


class LLMRouter:
    def __init__(
        self,
        config: ProvidersConfig,
        providers: Mapping[str, Provider],
        prices: PriceTable,
        store: UsageStore,
        budget: BudgetGuard,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self.providers = providers
        self.prices = prices
        self.store = store
        self.budget = budget
        self._sleep = sleep

    async def aclose(self) -> None:
        for provider in self.providers.values():
            await provider.aclose()

    def chain_for(self, tier: str) -> list[str]:
        """The tier, then the tiers after it in the failover chain ("one tier up")."""
        chain = self.config.routing.failover_chain
        return [tier, *chain[chain.index(tier) + 1 :]] if tier in chain else [tier]

    async def complete(
        self,
        request: LLMRequest,
        *,
        purpose: str = "chat",
        tier: str | None = None,
        agent_id: str | None = None,
        ignore_budget: bool = False,
        model: str | None = None,
    ) -> LLMResponse:
        """`model` overrides the requested tier's model (same provider, e.g. a smaller model
        for one yaver). Failover / budget tiers keep their own models."""
        requested = tier or self.config.tier_for_purpose(purpose)
        if requested not in self.config.tiers:
            raise ValueError(f"unknown tier {requested!r}")
        chain = self.chain_for(requested)
        if not ignore_budget:
            status = await self.budget.status()
            chain = self.budget.apply(chain, status.level)
            if status.level is not BudgetLevel.OK:
                logger.info("Budget %s (%s): tiers %s", status.level, _spent(status), chain)

        attempts: list[str] = []
        for tier_name in chain:
            override = model if tier_name == requested else None
            response = await self._try_tier(
                tier_name, request, purpose, agent_id, attempts, override
            )
            if response is not None:
                return response
        raise LLMUnavailableError(attempts)

    async def _try_tier(
        self,
        tier_name: str,
        request: LLMRequest,
        purpose: str,
        agent_id: str | None,
        attempts: list[str],
        model_override: str | None = None,
    ) -> LLMResponse | None:
        tier = self.config.tiers[tier_name]
        if model_override:
            tier = tier.model_copy(update={"model": model_override})
        provider = self.providers.get(tier.provider)
        if provider is None or not provider.configured:
            attempts.append(f"{tier_name}: provider {tier.provider} not configured")
            return None
        fitted = fit_prompt(request, tier.max_prompt_tokens)

        routing = self.config.routing
        invalid, waits = 0, 0
        while True:
            started = time.monotonic()
            try:
                response = await provider.complete(fitted, tier.model, dict(tier.options))
            except ProviderError as exc:
                latency = _elapsed_ms(started)
                if not isinstance(exc, ProviderNotConfiguredError):
                    prefix = "invalid tool calls: " if exc.invalid_tool_call else ""
                    await self._record(
                        UsageRecord(
                            provider.name,
                            tier.model,
                            tier_name,
                            purpose,
                            agent_id=agent_id,
                            latency_ms=latency,
                            error=(prefix + str(exc))[:500],
                        )
                    )
                if exc.invalid_tool_call:
                    logger.warning("Tier %s: provider rejected the tool call (%s)", tier_name, exc)
                    invalid += 1  # same as an invalid tool call: retry, then fail over
                    if invalid >= max(routing.max_invalid_tool_calls, 1):
                        break
                    continue
                if (
                    exc.status_code == 429
                    and exc.retry_after is not None
                    and exc.retry_after <= routing.rate_limit_max_wait_seconds
                    and waits < routing.rate_limit_max_waits
                ):
                    waits += 1  # a short wait is cheaper than paying the next tier
                    logger.info("Tier %s rate limited; waiting %.2fs", tier_name, exc.retry_after)
                    await self._sleep(exc.retry_after)
                    continue
                if not exc.retryable:
                    raise
                attempts.append(f"{tier_name}: {exc}")
                logger.warning("Tier %s failed (%s); failing over", tier_name, exc)
                return None

            response.tier = tier_name
            response.latency_ms = _elapsed_ms(started)
            response.cost_usd = self._cost(provider, tier, response)
            problems = tool_call_problems(
                response.tool_calls, fitted.tools, required=fitted.tool_choice == "required"
            )
            response.usage_id = await self._record(
                UsageRecord(
                    response.provider,
                    response.model,
                    tier_name,
                    purpose,
                    usage=response.usage,
                    cost_usd=response.cost_usd,
                    agent_id=agent_id,
                    latency_ms=response.latency_ms,
                    error=("invalid tool calls: " + "; ".join(problems))[:500]
                    if problems
                    else None,
                )
            )
            if not problems:
                return response
            logger.warning("Tier %s returned invalid tool calls: %s", tier_name, problems)
            invalid += 1
            if invalid >= max(routing.max_invalid_tool_calls, 1):
                break

        attempts.append(f"{tier_name}: invalid tool calls")
        return None

    def _cost(self, provider: Provider, tier: TierConfig, response: LLMResponse) -> Decimal:
        cost = compute_cost(
            self.prices,
            provider.name,
            tier.model,
            response.usage,
            reports_cost=provider.reports_cost,
        )
        if cost is None:
            logger.warning("No price for %s/%s; recording cost 0", provider.name, tier.model)
            return Decimal(0)
        return cost

    async def _record(self, record: UsageRecord) -> int | None:
        try:
            return await self.store.record(record)
        except Exception:  # accounting must never break a chat reply
            logger.exception("Could not record LLM usage")
            return None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _spent(status: BudgetStatus) -> str:
    return f"${status.spent_usd:.4f} of ${status.limit_usd}"


# --------------------------------------------------------------------------------------
# Construction from config + .env
# --------------------------------------------------------------------------------------


def env_value(settings: Settings, name: str | None) -> str | None:
    """Value of an env var named in providers.yaml: Settings (.env) first, then os.environ."""
    if not name:
        return None
    value = getattr(settings, name.lower(), None)
    if isinstance(value, SecretStr):
        return value.get_secret_value() or None
    if isinstance(value, str):
        return value or None
    return os.environ.get(name) or None


def build_provider(name: str, config: ProviderConfig, settings: Settings) -> Provider:
    api_key = env_value(settings, config.api_key_env)
    if config.type == "anthropic":
        return AnthropicProvider(
            name,
            api_key=api_key,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )
    base_url = config.base_url or env_value(settings, config.base_url_env)
    return OpenAICompatProvider(
        name,
        base_url=(base_url.rstrip("/") + config.base_url_suffix) if base_url else None,
        api_key=api_key,
        api_key_required=config.api_key_env is not None,
        reports_cost=config.reports_cost,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
    )


def build_providers(config: ProvidersConfig, settings: Settings) -> dict[str, Provider]:
    return {
        name: build_provider(name, provider, settings)
        for name, provider in config.providers.items()
    }


def build_router(
    settings: Settings | None = None,
    *,
    config: ProvidersConfig | None = None,
    store: UsageStore | None = None,
) -> LLMRouter:
    settings = settings or get_settings()
    config = config or load_providers_config()
    store = store or DbUsageStore(get_sessionmaker())
    budget = BudgetGuard(
        config.budget, Decimal(str(settings.claude_monthly_budget_usd)), store, settings.tz
    )
    return LLMRouter(config, build_providers(config, settings), load_price_table(), store, budget)


@lru_cache
def get_router() -> LLMRouter:
    return build_router()


__all__ = [
    "ChatMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMRouter",
    "LLMUnavailableError",
    "ToolSpec",
    "build_router",
    "get_router",
]
