"""Application settings, loaded from environment variables / `.env` (pydantic-settings)."""

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.time_resolver import ClockConvention

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env when running locally from backend/; in Docker, compose injects env vars.
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Yaver"
    app_user_name: str = ""
    app_timezone: str = "Europe/Istanbul"
    app_language: str = "tr"
    app_password: SecretStr = SecretStr("change-me")
    secret_key: SecretStr = SecretStr("change-me-long-random-string")

    # --- Paths ---
    config_dir: Path = REPO_DIR / "config"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://yaver:yaver@127.0.0.1:5432/yaver"

    # --- LLM providers (BYOK) ---
    groq_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"

    # --- Budget guard ---
    claude_monthly_budget_usd: float = 4.0

    # --- Clock convention for bare hours ("9'da" -> 09:00, "3'te" -> 15:00) ---
    clock_morning_hours: str = "8-11"
    clock_afternoon_hours: str = "1-7"

    # --- LLM ---
    # Check on startup that the configured models exist (logs only, never blocks startup).
    llm_check_models_on_startup: bool = True

    # --- Web Push (Phase 1) ---
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str | None = None

    @field_validator("app_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone: {value!r}") from exc
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def clock(self) -> ClockConvention:
        return ClockConvention(
            morning=_hour_range(self.clock_morning_hours),
            afternoon=_hour_range(self.clock_afternoon_hours),
        )

    @field_validator("clock_morning_hours", "clock_afternoon_hours")
    @classmethod
    def _validate_hour_range(cls, value: str) -> str:
        _hour_range(value)
        return value

    @model_validator(mode="after")
    def _validate_clock(self) -> "Settings":
        _ = self.clock  # ranges within 1-11 and not overlapping
        return self


def _hour_range(value: str) -> tuple[int, int]:
    """'8-11' -> (8, 11)"""
    try:
        low, high = (int(part) for part in value.split("-"))
    except ValueError as exc:
        raise ValueError(f"hour range must look like '8-11', got {value!r}") from exc
    return low, high


@lru_cache
def get_settings() -> Settings:
    return Settings()
