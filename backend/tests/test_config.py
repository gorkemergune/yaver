from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.core import config_problems
from app.core.yaml_config import (
    ConfigFileNotFoundError,
    load_validated,
    load_yaml_config,
    resolve_config_path,
)


def test_personal_config_wins_over_example(tmp_path: Path) -> None:
    (tmp_path / "agents.example.yaml").write_text("name: example\n", encoding="utf-8")
    (tmp_path / "agents.yaml").write_text("name: personal\n", encoding="utf-8")

    assert resolve_config_path("agents", tmp_path) == tmp_path / "agents.yaml"
    assert load_yaml_config("agents", tmp_path) == {"name": "personal"}


def test_falls_back_to_example(tmp_path: Path) -> None:
    (tmp_path / "agents.example.yaml").write_text("name: example\n", encoding="utf-8")

    assert load_yaml_config("agents", tmp_path) == {"name": "example"}


def test_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileNotFoundError):
        resolve_config_path("agents", tmp_path)


def test_non_mapping_config_rejected(tmp_path: Path) -> None:
    (tmp_path / "agents.yaml").write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mapping"):
        load_yaml_config("agents", tmp_path)


def test_repo_example_configs_are_loadable() -> None:
    repo_config_dir = Path(__file__).resolve().parents[2] / "config"
    if not repo_config_dir.is_dir():  # e.g. inside a container without the config mount
        pytest.skip("config/ directory not available")

    for name in ("agents", "providers"):
        assert load_yaml_config(name, repo_config_dir)


@pytest.fixture
def no_problems(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # the dev container's own .env values are process env here: only the test's count
    monkeypatch.delenv("GITHUB_STARTUP_REPO", raising=False)
    config_problems.clear()
    yield
    config_problems.clear()


def test_bad_env_values_fall_back_to_defaults(no_problems: None) -> None:
    """O1: one wrong value in .env must not stop the app."""
    settings = Settings(
        _env_file=None,
        app_timezone="Mars/Olympus",
        checkin_time="21h",
        claude_monthly_budget_usd="4$",  # type: ignore[arg-type]
        anthropic_api_key=12,  # type: ignore[arg-type]  # a secret: its value never shows up
        clock_morning_hours="morning",
    )

    assert settings.app_timezone == "Europe/Istanbul"
    assert settings.checkin_time == "21:00"
    assert settings.claude_monthly_budget_usd == 4.0
    assert settings.clock_morning_hours == "8-11"
    found = {p["field"]: p for p in config_problems.problems()}
    assert set(found) == {
        "APP_TIMEZONE",
        "CHECKIN_TIME",
        "CLAUDE_MONTHLY_BUDGET_USD",
        "ANTHROPIC_API_KEY",
        "CLOCK_MORNING_HOURS",
    }
    assert found["APP_TIMEZONE"] == {
        "source": ".env",
        "field": "APP_TIMEZONE",
        "message": "Unknown timezone: 'Mars/Olympus'",
        "fallback": "Europe/Istanbul",
    }
    assert found["ANTHROPIC_API_KEY"]["fallback"] == "boş"
    assert "12" not in str(found["ANTHROPIC_API_KEY"]["message"])


def test_a_bad_env_file_value_too(tmp_path: Path, no_problems: None) -> None:
    env = tmp_path / ".env"
    env.write_text("BRIEFING_TIME=9:00\nFOLLOWUP_TIME=12h\nSESSION_DAYS=otuz\n", encoding="utf-8")

    settings = Settings(_env_file=env)

    assert settings.briefing_time == "09:00"  # H:MM is fine
    assert settings.followup_time == "12:00"
    assert settings.session_days == 30
    assert {p["field"] for p in config_problems.problems()} == {"FOLLOWUP_TIME", "SESSION_DAYS"}
    Settings(_env_file=None)  # a good load clears the .env warnings
    assert config_problems.problems() == []


class Small(BaseModel):
    name: str
    size: int


def test_a_broken_personal_yaml_falls_back_to_the_example(
    tmp_path: Path, no_problems: None
) -> None:
    (tmp_path / "agents.example.yaml").write_text("name: example\nsize: 1\n", encoding="utf-8")
    personal = tmp_path / "agents.yaml"
    for broken in ('name: "unclosed\nsize: 2\n', "name: x\nsize: big\n"):
        personal.write_text(broken, encoding="utf-8")
        assert load_validated("agents", Small, tmp_path) == Small(name="example", size=1)
        [problem] = config_problems.problems()
        assert problem["source"] == "agents.yaml"
        assert problem["fallback"] == "agents.example.yaml"
    assert "size" in str(problem["message"])

    personal.write_text("name: mine\nsize: 3\n", encoding="utf-8")  # fixed
    assert load_validated("agents", Small, tmp_path) == Small(name="mine", size=3)
    assert config_problems.problems() == []


def test_a_broken_example_yaml_still_raises(tmp_path: Path) -> None:
    (tmp_path / "agents.example.yaml").write_text("name: x\nsize: big\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_validated("agents", Small, tmp_path)


def test_empty_api_key_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")

    assert Settings(_env_file=None).groq_api_key is None
