"""Typed views of config/providers(.example).yaml and app/llm/pricing.yaml."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.yaml_config import load_yaml_config

PRICING_FILE = Path(__file__).with_name("pricing.yaml")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TierConfig(_Strict):
    provider: str
    model: str
    max_prompt_tokens: int | None = None
    # Passed to the provider as-is (anthropic: thinking, effort, forced_tool_choice;
    # openai_compat: extra request body fields such as reasoning_effort).
    options: dict[str, Any] = Field(default_factory=dict)


class ProviderConfig(_Strict):
    type: Literal["openai_compat", "anthropic"]
    base_url: str | None = None
    base_url_env: str | None = None
    base_url_suffix: str = ""
    api_key_env: str | None = None
    default_model: str | None = None
    reports_cost: bool = False
    optional: bool = False
    timeout_seconds: float = 60.0
    # Longest 429 wait to sit out on this provider before failing over (overrides
    # routing.rate_limit_max_wait_seconds); *_env names a .env variable that wins over both.
    rate_limit_max_wait_seconds: float | None = None
    rate_limit_max_wait_env: str | None = None
    # SDK-level retries. 0: the router decides (short 429 waits, then failover); SDK retries
    # would wait as long as the provider says.
    max_retries: int = 0


class RoutingConfig(_Strict):
    default: str
    failover_chain: list[str] = Field(default_factory=list)
    purposes: dict[str, str] = Field(default_factory=dict)
    # Tiers only a purpose mapped to them may use (deep: Opus for marked weekly jobs); a
    # call asking for one under any other purpose is refused in code.
    explicit_only: list[str] = Field(default_factory=list)
    max_tool_steps: int = 6
    max_invalid_tool_calls: int = 2
    rate_limit_max_wait_seconds: float = 3.0  # 429 asking for a longer wait -> fail over
    rate_limit_max_waits: int = 2


class TierLimit(_Strict):
    """A tier with its own monthly limit on top of the provider budget."""

    limit_env: str  # USD per month, from .env (e.g. DEEP_MONTHLY_BUDGET_USD)
    over_limit: str  # the tier used instead once this month's spend reaches the limit


class BudgetConfig(_Strict):
    provider: str = "anthropic"
    downgrade_at: float = 0.8
    downgrade: dict[str, str] = Field(default_factory=lambda: {"smart": "fallback"})
    limit_at: float = 1.0
    allowed_at_limit: list[str] = Field(default_factory=lambda: ["fast", "local"])
    tier_limits: dict[str, TierLimit] = Field(default_factory=dict)


class SttConfig(_Strict):
    """Speech to text for voice messages (not a tier: no failover, no tool calls)."""

    provider: str = "groq"
    model: str = "whisper-large-v3"
    language: str | None = "tr"  # null: let the model detect it
    usd_per_hour: float = 0.111
    min_billed_seconds: float = 10  # Groq bills at least 10 s per request


class ProvidersConfig(_Strict):
    tiers: dict[str, TierConfig]
    providers: dict[str, ProviderConfig]
    routing: RoutingConfig
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    stt: SttConfig = Field(default_factory=SttConfig)

    @model_validator(mode="after")
    def _check_references(self) -> "ProvidersConfig":
        for name, tier in self.tiers.items():
            if tier.provider not in self.providers:
                raise ValueError(f"tier {name!r} uses unknown provider {tier.provider!r}")
        referenced = [
            self.routing.default,
            *self.routing.failover_chain,
            *self.routing.purposes.values(),
            *self.budget.downgrade.keys(),
            *self.budget.downgrade.values(),
            *self.budget.allowed_at_limit,
            *self.routing.explicit_only,
            *self.budget.tier_limits.keys(),
            *(limit.over_limit for limit in self.budget.tier_limits.values()),
        ]
        unknown = sorted({tier for tier in referenced if tier not in self.tiers})
        if unknown:
            raise ValueError(f"unknown tier(s) referenced: {', '.join(unknown)}")
        # An explicit-only tier must never be reached by default, by failing over or by a
        # budget step: only a purpose mapped to it.
        reachable = {
            self.routing.default,
            *self.routing.failover_chain,
            *self.budget.downgrade.values(),
            *self.budget.allowed_at_limit,
            *(limit.over_limit for limit in self.budget.tier_limits.values()),
        }
        leaked = sorted(set(self.routing.explicit_only) & reachable)
        if leaked:
            raise ValueError(f"explicit-only tier(s) reachable without a purpose: {leaked}")
        return self

    def tier_for_purpose(self, purpose: str) -> str:
        return self.routing.purposes.get(purpose, self.routing.default)


@lru_cache
def load_providers_config() -> ProvidersConfig:
    return ProvidersConfig.model_validate(load_yaml_config("providers"))


# --- pricing ---------------------------------------------------------------------------

PER_MILLION = Decimal(1_000_000)


class Rates(_Strict):
    input: Decimal
    output: Decimal
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None


class LongContextRates(Rates):
    threshold_tokens: int


class ModelPrice(Rates):
    long_context: LongContextRates | None = None

    def rates_for(self, prompt_tokens: int) -> Rates:
        if self.long_context and prompt_tokens > self.long_context.threshold_tokens:
            return self.long_context
        return self


class PriceTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    prices: dict[str, dict[str, ModelPrice]]

    def lookup(self, provider: str, model: str) -> ModelPrice | None:
        models = self.prices.get(provider, {})
        return models.get(model) or models.get("*")


def load_price_table(path: Path = PRICING_FILE) -> PriceTable:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return PriceTable(prices={provider: models or {} for provider, models in raw.items()})
