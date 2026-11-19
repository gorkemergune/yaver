"""Check that every configured model exists at its provider (/models endpoint).

    docker compose exec api python -m app.llm.check_models

Exit code 1 if a model is missing or a provider can't be reached. Providers without an API
key are reported as SKIPPED; problems with `optional: true` providers (Ollama) only warn.
"""

import asyncio
import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.config import get_settings
from app.llm.config import ProvidersConfig, load_providers_config
from app.llm.providers.base import Provider
from app.llm.router import build_providers
from app.llm.types import ProviderError

logger = logging.getLogger(__name__)


class CheckStatus(StrEnum):
    OK = "OK"
    MISSING = "MISSING"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ModelCheck:
    target: str  # tier name, or "<provider> default_model"
    provider: str
    model: str
    status: CheckStatus
    detail: str = ""
    optional: bool = False

    @property
    def failed(self) -> bool:
        return self.status in (CheckStatus.MISSING, CheckStatus.ERROR) and not self.optional


def _targets(config: ProvidersConfig) -> list[tuple[str, str, str]]:
    targets = [(name, tier.provider, tier.model) for name, tier in config.tiers.items()]
    used = {(provider, model) for _, provider, model in targets}
    for name, provider in config.providers.items():
        if provider.default_model and (name, provider.default_model) not in used:
            targets.append((f"{name} default_model", name, provider.default_model))
    return targets


async def check_models(
    config: ProvidersConfig, providers: Mapping[str, Provider]
) -> list[ModelCheck]:
    results: list[ModelCheck] = []
    for target, provider_name, model in _targets(config):
        provider = providers[provider_name]
        optional = config.providers[provider_name].optional
        if not provider.configured:
            key = config.providers[provider_name].api_key_env or "base URL"
            results.append(
                ModelCheck(target, provider_name, model, CheckStatus.SKIPPED, f"{key} not set")
            )
            continue
        try:
            found = await provider.has_model(model)
        except ProviderError as exc:
            results.append(
                ModelCheck(target, provider_name, model, CheckStatus.ERROR, str(exc), optional)
            )
            continue
        if found:
            results.append(ModelCheck(target, provider_name, model, CheckStatus.OK))
        else:
            detail = (
                f"model {model!r} not found at {provider_name}; "
                "update config/providers.yaml with an id from the provider's model list"
            )
            results.append(
                ModelCheck(target, provider_name, model, CheckStatus.MISSING, detail, optional)
            )
    return results


def format_report(results: list[ModelCheck]) -> str:
    width = max((len(r.target) for r in results), default=10)
    lines = []
    for r in results:
        note = f"  ({r.detail})" if r.detail else ""
        flag = " [optional]" if r.optional and r.status is not CheckStatus.OK else ""
        lines.append(f"{r.status.value:<8} {r.target:<{width}}  {r.provider}/{r.model}{flag}{note}")
    return "\n".join(lines)


async def run() -> int:
    config = load_providers_config()
    providers = build_providers(config, get_settings())
    try:
        results = await check_models(config, providers)
    finally:
        for provider in providers.values():
            await provider.aclose()
    print(format_report(results))
    failed = [r for r in results if r.failed]
    if failed:
        print(f"\n{len(failed)} problem(s): fix config/providers.yaml or the API keys in .env.")
        return 1
    return 0


async def log_startup_check() -> None:
    """Non-blocking startup variant: logs instead of exiting."""
    try:
        config = load_providers_config()
        providers = build_providers(config, get_settings())
        try:
            results = await check_models(config, providers)
        finally:
            for provider in providers.values():
                await provider.aclose()
    except Exception:
        logger.exception("LLM model check failed to run")
        return
    for result in results:
        if result.failed:
            logger.error(
                "LLM model check: %s %s/%s - %s",
                result.status,
                result.provider,
                result.model,
                result.detail,
            )
        elif result.status is not CheckStatus.OK:
            logger.warning(
                "LLM model check: %s %s/%s - %s",
                result.status,
                result.provider,
                result.model,
                result.detail,
            )
        else:
            logger.info("LLM model check: OK %s/%s", result.provider, result.model)


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
