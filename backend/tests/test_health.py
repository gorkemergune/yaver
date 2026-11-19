import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.main import create_app


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health_returns_ok(path: str) -> None:
    client = TestClient(create_app())

    response = client.get(path)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionRefusedError("db down")


def test_ready_when_database_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session, "ping_database", _ok)
    client = TestClient(create_app())

    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_not_ready_when_database_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session, "ping_database", _fail)
    client = TestClient(create_app())

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
