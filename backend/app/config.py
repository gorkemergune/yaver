"""Application settings, loaded from environment variables / `.env` (pydantic-settings)."""

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    database_url: str = "postgresql+asyncpg://yaver:yaver@localhost:5432/yaver"

    # --- LLM providers (BYOK) ---
    groq_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"

    # --- Budget guard ---
    claude_monthly_budget_usd: float = 4.0

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
