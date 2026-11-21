"""Low findings of docs/QA_REPORT.md fixed with a test: D1 (a failing rollback), D4 (files
of a refused batch)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import Coordinator
from app.api.auth import require_auth
from app.config import Settings, get_settings
from app.db.models import Attachment
from app.db.session import get_session
from app.main import create_app
from app.office import activity as activity_module
from tests.agent_fakes import NOW, ScriptedLLM, example_team


async def test_a_failing_rollback_still_ends_the_work_and_keeps_the_error(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D1: the employee must not stay "working" in the office, and the real error is the
    one raised (not the rollback's)."""
    closed: list[bool] = []

    async def close(self: Any) -> None:
        closed.append(True)

    async def broken_rollback() -> None:
        raise ConnectionError("connection lost")

    async def failing_handle(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the model call failed")

    monkeypatch.setattr(activity_module.MessageActivity, "close", close)
    monkeypatch.setattr(session, "rollback", broken_rollback)
    coordinator = Coordinator(ScriptedLLM(), example_team(), Settings(_env_file=None))
    monkeypatch.setattr(coordinator, "_handle", failing_handle)

    with pytest.raises(RuntimeError, match="the model call failed"):
        await coordinator.handle(session, "x", now=NOW)

    assert closed == [True]


def files_in(directory: Path) -> list[Path]:
    return [p for p in directory.rglob("*") if p.is_file()]


async def test_a_refused_file_leaves_no_files_of_its_batch(
    session: AsyncSession, tmp_path: Path
) -> None:
    """D4: the first file (a CSV) was written to disk, the second is refused: nothing is
    saved, so the first file goes too."""
    app = create_app()
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, upload_dir=tmp_path)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    csv = "Kampanya adı;Harcanan tutar (TRY)\nA;10\n".encode()
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/uploads",
            files=[
                ("files", ("Kampanyalar.csv", csv, "text/csv")),
                ("files", ("not-an-image.png", b"definitely not a png", "image/png")),
            ],
        )

    assert response.status_code in (415, 422), response.text
    assert files_in(tmp_path) == []
    assert await session.scalar(select(func.count()).select_from(Attachment)) == 0
