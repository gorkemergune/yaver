"""Live: Creator drafts next week's posts for the made-up "Örnek Girişim" from seeded notes
(no web search key). One smart call (~$0.02).
docker compose exec api pytest -m live -k content -s
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import LlmUsage
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore
from app.office.state import Office
from tests.db.test_content_calendar import run, seed
from tests.db.test_shift_jobs import office  # noqa: F401

pytestmark = pytest.mark.live


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    if not env_value(get_settings(), "ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    router = build_router(store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


async def test_a_weekly_draft_from_the_teams_notes(
    session: AsyncSession,
    office: Office,  # noqa: F811
    router: LLMRouter,
) -> None:
    await seed(session)

    note = await run(session, office, router, web=None)  # type: ignore[arg-type]

    print(f"\n{note}\n")
    rows = (await session.scalars(select(LlmUsage).order_by(LlmUsage.id))).all()
    for row in rows:
        print(f"  {row.purpose} {row.tier} {row.provider}/{row.model} ${row.cost_usd}")
    assert note.startswith("İçerik takvimi taslağı (23 Kas - 29 Kas), paylaşılmadı")
    assert note.count("\n| ") >= 4  # header + at least 3 posts
    assert "Trend yok" in note
    assert any(r.purpose == "content_calendar" and r.tier == "smart" for r in rows)
