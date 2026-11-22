"""Loader for YAML files in `config/`.

Rule: read `config/<name>.yaml` (personal, gitignored) if it exists, otherwise fall back to
`config/<name>.example.yaml` (committed). When a new config field is added, update the
example file too.

agents.yaml and providers.yaml are OVERLAYS (`load_validated(..., overlay=...)`): the
committed example is the base - tools, shift jobs, routing purposes come from it - and the
personal file only changes what it may change (names, colours, personas, office hours,
which model a tier uses). A personal copy made months ago therefore still gets every new
tool (live: Venture had no GitHub tools, Scholar no get_exam_scope). What the personal
file has that is unknown, ignored or missing is logged once as a warning.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.core import config_problems
from app.core.config_problems import ConfigProblem

logger = logging.getLogger("app.config")

# (base example, personal file, notes) -> the merged mapping; notes collect the warnings
Overlay = Callable[[dict[str, Any], dict[str, Any], list[str]], dict[str, Any]]
_warned: set[tuple[str, str]] = set()


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
    return _read(resolve_config_path(name, config_dir))


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def load_validated[M: BaseModel](
    name: str, model: type[M], config_dir: Path | None = None, *, overlay: Overlay | None = None
) -> M:
    """`config/<name>.yaml` validated as `model`. A broken personal file (YAML syntax, an
    unknown tool, a wrong type) does not stop the app: the error is logged and shown in the
    UI, and the committed example file is used until it is fixed. A broken example file is a
    bug in the repo and raises.

    With `overlay`, the personal file is laid over the example (see the module docstring)
    instead of replacing it."""
    path = resolve_config_path(name, config_dir)
    example = path.with_name(f"{name}.example.yaml")
    try:
        data = _read(path)
        if overlay is not None and path != example and example.is_file():
            notes: list[str] = []
            data = overlay(_read(example), data, notes)
            _warn(path.name, example.name, notes)
        loaded = model.model_validate(data)
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        if path == example or not example.is_file():
            raise
        config_problems.report(ConfigProblem(path.name, None, _first_line(exc), example.name))
        return model.model_validate(_read(example))
    config_problems.resolved(path.name)
    return loaded


def _warn(source: str, example: str, notes: list[str]) -> None:
    for note in notes:
        if (source, note) not in _warned:  # once per process (loaders run more than once)
            _warned.add((source, note))
            logger.warning("%s: %s (base: %s)", source, note, example)


def merge_tree(
    base: Any,
    local: Any,
    notes: list[str],
    where: str = "",
    *,
    atomic: Callable[[str], bool] = lambda _where: False,
) -> Any:
    """`local` laid over `base`, key by key: a mapping is merged (keys only in base stay,
    noted as missing; keys only in local are kept, noted as not in the example), anything
    else - a list, a scalar, or a mapping `atomic(where)` names - is replaced whole."""
    if not isinstance(base, dict) or not isinstance(local, dict) or (where and atomic(where)):
        return local
    merged = dict(base)
    missing = [key for key in base if key not in local]
    if missing:
        notes.append(
            f"{where or 'top level'}: {', '.join(map(str, missing))} not set, from the example"
        )
    for key, value in local.items():
        path = f"{where}.{key}" if where else str(key)
        if key not in base:
            notes.append(f"{path} is not in the example (kept)")
            merged[key] = value
        else:
            merged[key] = merge_tree(base[key], value, notes, path, atomic=atomic)
    return merged


def _first_line(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        return f"{where}: {error['msg']}" + (
            f" (+{exc.error_count() - 1})" if exc.error_count() > 1 else ""
        )
    return " ".join(str(exc).split())[:300]
