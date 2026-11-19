import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health_returns_ok(path: str) -> None:
    client = TestClient(create_app())

    response = client.get(path)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
