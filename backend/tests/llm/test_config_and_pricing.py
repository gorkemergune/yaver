from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.core.yaml_config import load_yaml_config
from app.llm.config import ProvidersConfig, load_price_table
from app.llm.types import TokenUsage
from app.llm.usage import compute_cost
from tests.llm.fakes import make_config

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"


def test_example_providers_config_is_valid() -> None:
    config = ProvidersConfig.model_validate(_example())

    assert config.routing.default == "fast"
    assert config.tiers["fallback"].max_prompt_tokens == 90000
    assert config.tiers["smart"].options == {"effort": "medium"}
    assert config.providers["openrouter"].reports_cost


def _example() -> dict[str, object]:
    if not (REPO_CONFIG / "providers.example.yaml").is_file():
        pytest.skip("config/ not mounted")
    with (REPO_CONFIG / "providers.example.yaml").open(encoding="utf-8") as fh:
        data: dict[str, object] = yaml.safe_load(fh)
    return data


def test_local_providers_config_is_valid_too() -> None:
    """config/providers.yaml (personal) if present, else the example."""
    if not REPO_CONFIG.is_dir():
        pytest.skip("config/ not mounted")
    ProvidersConfig.model_validate(load_yaml_config("providers", REPO_CONFIG))


def test_unknown_tier_reference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown tier"):
        make_config(routing={"default": "turbo"})


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown provider"):
        make_config(tiers={"fast": {"provider": "nowhere", "model": "m"}})


def test_typos_in_config_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_config(routing={"default": "fast", "failover_chian": ["fast"]})


# --- pricing ---------------------------------------------------------------------------

PRICES = load_price_table()


def test_every_configured_tier_has_a_price_or_reported_cost() -> None:
    config = ProvidersConfig.model_validate(_example())
    for name, tier in config.tiers.items():
        provider = config.providers[tier.provider]
        assert provider.reports_cost or PRICES.lookup(tier.provider, tier.model), name


def test_haiku_cost_with_cache() -> None:
    # 40k-token prompt in total: normal (<= 100K) rates
    usage = TokenUsage(
        input_tokens=10_000,
        output_tokens=10_000,
        cached_input_tokens=20_000,
        cache_write_tokens=10_000,
    )

    cost = compute_cost(PRICES, "anthropic", "claude-haiku-5-5", usage, reports_cost=False)

    # 10k*0.10 + 10k*0.50 + 20k*0.01 + 10k*0.125, per 1M
    assert cost == Decimal("0.007450")


def test_haiku_long_context_rates_above_100k_prompt_tokens() -> None:
    short = TokenUsage(input_tokens=100_000, output_tokens=0)
    long = TokenUsage(input_tokens=120_000, output_tokens=0)

    assert compute_cost(
        PRICES, "anthropic", "claude-haiku-5-5", short, reports_cost=False
    ) == Decimal("0.010000")
    assert compute_cost(
        PRICES, "anthropic", "claude-haiku-5-5", long, reports_cost=False
    ) == Decimal("0.060000")  # whole prompt billed at $0.50/M


def test_cached_tokens_count_toward_the_long_context_threshold() -> None:
    usage = TokenUsage(input_tokens=1_000, cached_input_tokens=150_000)

    cost = compute_cost(PRICES, "anthropic", "claude-haiku-5-5", usage, reports_cost=False)

    assert cost == Decimal("0.008000")  # 1k at $0.50/M + 150k at $0.05/M


def test_groq_and_free_ollama() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)

    assert compute_cost(
        PRICES, "groq", "openai/gpt-oss-120b", usage, reports_cost=False
    ) == Decimal("0.75")
    assert compute_cost(PRICES, "ollama", "qwen3:8b", usage, reports_cost=False) == 0


def test_unknown_model_has_no_price() -> None:
    assert compute_cost(PRICES, "groq", "nope", TokenUsage(1, 1), reports_cost=False) is None


def test_reported_cost_used_only_when_provider_reports() -> None:
    usage = TokenUsage(10, 10, reported_cost_usd=Decimal("0.123"))

    assert compute_cost(PRICES, "openrouter", "x", usage, reports_cost=True) == Decimal("0.123000")
    assert compute_cost(PRICES, "openrouter", "x", usage, reports_cost=False) is None
