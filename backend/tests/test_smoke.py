"""The app really loads: the module uvicorn imports (`app.main:app`) answers /health, and
every module under app/ imports. Catches import-time errors such as a class field that
shadows a module used in a later annotation (`github: github.GitHub`, `date: date`),
which unit tests importing other modules can miss."""

import importlib
import importlib.util
import pkgutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_package


def test_the_served_app_object_answers_health() -> None:
    from app.main import app  # exactly what uvicorn loads

    client = TestClient(app)  # no lifespan: it starts network checks and backups

    for path in ("/health", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json()["status"] == "ok"


@pytest.mark.parametrize(
    "module",
    sorted(
        m.name
        for m in pkgutil.walk_packages(app_package.__path__, prefix="app.")
        if not m.name.endswith("__main__")
    ),
)
def test_every_module_imports(module: str) -> None:
    importlib.import_module(module)


def test_no_class_field_shadows_an_import() -> None:
    """QA O2: `github: github.GitHub` stopped the API for 4 hours; the AST scan of app/ must
    stay empty (backend/scripts/shadow_scan.py, also a pre-commit hook)."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "shadow_scan.py"
    spec = importlib.util.spec_from_file_location("shadow_scan", path)
    assert spec is not None
    assert spec.loader is not None
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)

    assert scanner.scan_tree(Path(app_package.__path__[0])) == []
