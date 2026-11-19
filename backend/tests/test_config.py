from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.yaml_config import (
    ConfigFileNotFoundError,
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


def test_invalid_timezone_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(app_timezone="Mars/Olympus")


def test_empty_api_key_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")

    assert Settings(_env_file=None).groq_api_key is None
