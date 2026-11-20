"""Speech to text for voice messages: Groq Whisper (whisper-large-v3) by default.

Not a chat completion, so it does not go through the router; provider, model, language
and price come from the `stt` section of providers.yaml, and every call is written to
llm_usage (tier "stt", purpose "voice") like the router's calls.
"""

import datetime as dt
import time
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any

import openai

from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.llm.config import ProvidersConfig, load_providers_config
from app.llm.router import env_value
from app.llm.usage import DbUsageStore, UsageRecord, UsageStore

USE_CONFIG = "config"


class SttUnavailableError(RuntimeError):
    """No key / provider for speech to text, or the provider failed."""


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    seconds: float
    cost_usd: Decimal
    model: str


class SpeechToText:
    def __init__(
        self,
        config: ProvidersConfig,
        settings: Settings,
        store: UsageStore,
        client: Any = None,
    ) -> None:
        self.config = config.stt
        self.provider = config.providers.get(self.config.provider)
        self.settings = settings
        self.store = store
        self._client = client

    @property
    def configured(self) -> bool:
        return self._client is not None or bool(
            self.provider and env_value(self.settings, self.provider.api_key_env)
        )

    def _api(self) -> Any:
        if self._client is None:
            if self.provider is None or not self.configured:
                raise SttUnavailableError(f"no API key for {self.config.provider}")
            self._client = openai.AsyncOpenAI(
                base_url=self.provider.base_url,
                api_key=env_value(self.settings, self.provider.api_key_env),
                timeout=60.0,
                max_retries=1,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        self._client = None

    def cost(self, seconds: float) -> Decimal:
        billed = max(seconds, self.config.min_billed_seconds)
        return (Decimal(str(billed)) / 3600 * Decimal(str(self.config.usd_per_hour))).quantize(
            Decimal("0.000001")
        )

    async def transcribe(
        self, audio: bytes, filename: str, language: str | None = USE_CONFIG
    ) -> Transcript:
        api = self._api()
        lang = self.config.language if language == USE_CONFIG else language
        started = time.monotonic()
        try:
            response = await api.audio.transcriptions.create(
                model=self.config.model,
                file=(filename, audio),
                response_format="verbose_json",
                temperature=0,
                **({"language": lang} if lang else {}),
            )
        except openai.APIError as exc:
            await self._record(Decimal(0), started, error=f"{type(exc).__name__}: {exc}")
            raise SttUnavailableError(str(exc)) from exc
        seconds = float(getattr(response, "duration", 0) or 0)
        cost = self.cost(seconds)
        await self._record(cost, started)
        return Transcript(str(response.text).strip(), seconds, cost, self.config.model)

    async def _record(self, cost: Decimal, started: float, error: str | None = None) -> None:
        await self.store.record(
            UsageRecord(
                provider=self.config.provider,
                model=self.config.model,
                tier="stt",
                purpose="voice",
                cost_usd=cost,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=error,
                created_at=dt.datetime.now(dt.UTC),
            )
        )


@lru_cache
def get_stt() -> SpeechToText:
    return SpeechToText(load_providers_config(), get_settings(), DbUsageStore(get_sessionmaker()))
