"""Loader for YAML files in `config/`.

Rule: read `config/<name>.yaml` (personal, gitignored) if it exists, otherwise fall back to
`config/<name>.example.yaml` (committed). When a new config field is added, update the
example file too.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.core import config_problems
from app.core.config_problems import ConfigProblem


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


def load_validated[M: BaseModel](name: str, model: type[M], config_dir: Path | None = None) -> M:
    """`config/<name>.yaml` validated as `model`. A broken personal file (YAML syntax, an
    unknown tool, a wrong type) does not stop the app: the error is logged and shown in the
    UI, and the committed example file is used until it is fixed. A broken example file is a
    bug in the repo and raises."""
    path = resolve_config_path(name, config_dir)
    try:
        loaded = model.model_validate(load_yaml_config(name, config_dir))
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        example = path.with_name(f"{name}.example.yaml")
        if path == example or not example.is_file():
            raise
        config_problems.report(ConfigProblem(path.name, None, _first_line(exc), example.name))
        with example.open(encoding="utf-8") as fh:
            return model.model_validate(yaml.safe_load(fh) or {})
    config_problems.resolved(path.name)
    return loaded


def _first_line(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        return f"{where}: {error['msg']}" + (
            f" (+{exc.error_count() - 1})" if exc.error_count() > 1 else ""
        )
    return " ".join(str(exc).split())[:300]
