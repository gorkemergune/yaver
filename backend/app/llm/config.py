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
    max_retries: int = 1  # SDK-level retries before the router fails over


class RoutingConfig(_Strict):
    default: str
    failover_chain: list[str] = Field(default_factory=list)
    purposes: dict[str, str] = Field(default_factory=dict)
    max_tool_steps: int = 6
    max_invalid_tool_calls: int = 2


class BudgetConfig(_Strict):
    provider: str = "anthropic"
    downgrade_at: float = 0.8
    downgrade: dict[str, str] = Field(default_factory=lambda: {"smart": "fallback"})
    limit_at: float = 1.0
    allowed_at_limit: list[str] = Field(default_factory=lambda: ["fast", "local"])


class ProvidersConfig(_Strict):
    tiers: dict[str, TierConfig]
    providers: dict[str, ProviderConfig]
    routing: RoutingConfig
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

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
        ]
        unknown = sorted({tier for tier in referenced if tier not in self.tiers})
        if unknown:
            raise ValueError(f"unknown tier(s) referenced: {', '.join(unknown)}")
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
