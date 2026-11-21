"""The app really loads: the module uvicorn imports (`app.main:app`) answers /health, and
every module under app/ imports. Catches import-time errors such as a class field that
shadows a module used in a later annotation (`github: github.GitHub`, `date: date`),
which unit tests importing other modules can miss."""

import importlib
import pkgutil

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
