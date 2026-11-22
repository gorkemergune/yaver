"""Every module under app/ imports on its own, as the first thing a fresh interpreter loads
(scripts/import_each.py). test_smoke imports them all in one process, in one order, so a
circular import that breaks only when another module comes first passes there: on live
`python -m app.materials.bundle` failed (bundle -> ingest -> mapping -> app.agent.tools ->
tools/materials -> ingest) while the API and every test were fine."""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_each.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("import_each", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_list_has_every_module_file() -> None:
    names = _script().modules()

    assert "app" in names
    assert "app.main" in names
    assert "app.materials.bundle" in names
    assert "app.agent.schema" in names
    assert not any(n.endswith(("__main__", "__init__")) for n in names)
    assert len(names) == len(set(names)) > 100


def test_a_broken_module_is_reported() -> None:
    script = _script()

    assert script.import_alone("app.agent.schema") is None
    error = script.import_alone("app.no_such_module")
    assert error is not None
    assert "ModuleNotFoundError" in error


def test_every_module_imports_alone() -> None:
    script = _script()

    failed = script.failures(script.modules())

    assert failed == {}, "\n\n".join(f"{name}:\n{error}" for name, error in failed.items())


def test_the_materials_cli_imports_first() -> None:
    """What import-materials-live.ps1 runs first in the live api."""
    assert _script().import_alone("app.materials.bundle") is None
