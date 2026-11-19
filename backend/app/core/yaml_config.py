"""Loader for YAML files in `config/`.

Rule: read `config/<name>.yaml` (personal, gitignored) if it exists, otherwise fall back to
`config/<name>.example.yaml` (committed). When a new config field is added, update the
example file too.
"""

from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


class ConfigFileNotFoundError(FileNotFoundError):
    pass


def resolve_config_path(name: str, config_dir: Path | None = None) -> Path:
    directory = config_dir if config_dir is not None else get_settings().config_dir
    for candidate in (directory / f"{name}.yaml", directory / f"{name}.example.yaml"):
        if candidate.is_file():
            return candidate
    raise ConfigFileNotFoundError(
        f"Neither {name}.yaml nor {name}.example.yaml found in {directory}"
    )


def load_yaml_config(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    path = resolve_config_path(name, config_dir)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data
