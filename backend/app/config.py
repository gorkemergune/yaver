"""Application settings, loaded from environment variables / `.env` (pydantic-settings)."""

import datetime as dt
import logging
import re
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
    # Login for the web and desktop apps; empty = no login (fine on localhost only).
    app_password: SecretStr | None = None
    session_days: int = 30  # a login lasts this long after its last use

    # --- Paths ---
    config_dir: Path = REPO_DIR / "config"
    upload_dir: Path = REPO_DIR / "uploads"  # gitignored; /uploads volume in Docker

    # --- Backups (pg_dump .sql.gz; scripts/backup.sh restores them) ---
    backup_dir: Path = REPO_DIR / "backups"  # gitignored; /backups volume in Docker
    backup_keep: int = 14  # newest N kept
    backup_max_age_hours: float = 24  # on startup: back up when the newest is older
    backup_on_startup: bool = True

    # --- Course materials (Phase 3): local embeddings, downloaded once (~220 MB) ---
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    model_cache_dir: Path = REPO_DIR / "models"  # gitignored; /models volume in Docker

    # --- Images sent in the chat ---
    upload_max_mb: float = 20  # per file, before processing
    image_max_edge: int = 1600  # longer side after automatic downscaling (px)

    # --- Database ---
    database_url: str = "postgresql+asyncpg://yaver:yaver@127.0.0.1:5432/yaver"

    # --- LLM providers (BYOK) ---
    groq_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"

    # --- Budget guard ---
    claude_monthly_budget_usd: float = 4.0
    # Own limit of the deep tier (Opus, marked weekly jobs); counts toward the Claude budget too.
    deep_monthly_budget_usd: float = 2.0

    # --- Clock convention for bare hours ("9'da" -> 09:00, "3'te" -> 15:00) ---
    clock_morning_hours: str = "8-11"
    clock_afternoon_hours: str = "1-7"

    # --- LLM ---
    # Groq 429: sit out waits up to this many seconds, longer ones fail over to Haiku.
    groq_max_retry_wait_sec: float | None = None
    # Check on startup that the configured models exist (logs only, never blocks startup).
    llm_check_models_on_startup: bool = True

    # --- Scheduler: briefing, evening check-in, follow-ups (local times, APP_TIMEZONE) ---
    scheduler_enabled: bool = True
    # A chat message that takes longer ends with error "timeout" (rolled back). The stream
    # sends a ping every CHAT_PING_SECONDS meanwhile, so proxies don't cut a slow answer.
    chat_timeout_seconds: float = 240.0
    chat_ping_seconds: float = 15.0
    briefing_time: str = "09:00"  # with the office: the standup, then the briefing
    checkin_time: str = "21:00"
    followup_time: str = "12:00"
    weekly_plan_time: str = "20:00"  # Sundays: the coming week's draft (smart tier)
    exam_prep_time: str = "18:00"  # daily: review plan for exams a week away
    day_report_time: str = "21:15"  # Yaver's day report from the notebooks (after check-in)

    # --- Integrations (O3): missing keys = the employee shows "entegrasyon bekliyor" ---
    web_search_provider: str = "auto"  # auto (the first with a key) | tavily | brave
    tavily_api_key: SecretStr | None = None
    brave_api_key: SecretStr | None = None
    meta_access_token: SecretStr | None = None  # Metrics: Meta Marketing API (skeleton)
    meta_ad_account_id: str | None = None
    # Venture: the startup's GitHub repository, read only ("owner/name"). A fine-grained
    # token with read access to contents, issues, pull requests and metadata is enough.
    github_token: SecretStr | None = None
    github_startup_repo: str | None = None

    # --- Web Push (Phase 1) ---
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str | None = None

    @field_validator("github_startup_repo", mode="before")
    @classmethod
    def _validate_repo(cls, value: object) -> object:
        """'owner/name' (a pasted URL works too); empty or invalid = not set."""
        if not isinstance(value, str) or not value.strip():
            return None
        repo = value.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            # a placeholder left in .env must not stop the app: the integration stays pending
            logging.getLogger(__name__).warning(
                "GITHUB_STARTUP_REPO=%r is not owner/name: GitHub integration off", value
            )
            return None
        return repo

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

    @field_validator(
        "briefing_time",
        "checkin_time",
        "followup_time",
        "weekly_plan_time",
        "exam_prep_time",
        "day_report_time",
    )
    @classmethod
    def _hhmm(cls, value: str) -> str:
        try:
            dt.time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"expected HH:MM, got {value!r}") from exc
        return value

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
