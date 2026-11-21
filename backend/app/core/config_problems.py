"""Configuration mistakes the app survived: a bad .env value (the default is used instead)
or a broken config/agents.yaml / providers.yaml (the example file is used instead).

Each is logged once as an error and listed in GET /api/team (`config_problems`), so the
web app can show a warning instead of the API not starting at all.
"""

import logging
from dataclasses import asdict, dataclass

logger = logging.getLogger("app.config")


@dataclass(frozen=True, slots=True)
class ConfigProblem:
    source: str  # ".env", "agents.yaml", "providers.yaml"
    field: str | None  # the .env variable; None for a whole file
    message: str  # English, for the log and the UI's details line
    fallback: str  # what is used instead ("09:00", "agents.example.yaml")


_problems: dict[tuple[str, str | None], ConfigProblem] = {}


def report(problem: ConfigProblem) -> None:
    key = (problem.source, problem.field)
    if _problems.get(key) != problem:
        what = f"{problem.source} {problem.field}" if problem.field else problem.source
        logger.error("Config problem: %s: %s (using %s)", what, problem.message, problem.fallback)
    _problems[key] = problem


def resolved(source: str, field: str | None = None) -> None:
    """The file / value is fine again (e.g. agents.yaml fixed): the warning goes away."""
    _problems.pop((source, field), None)


def clear_source(source: str) -> None:
    for key in [k for k in _problems if k[0] == source]:
        del _problems[key]


def problems() -> list[dict[str, str | None]]:
    return [asdict(p) for p in _problems.values()]


def clear() -> None:
    """Tests only."""
    _problems.clear()
