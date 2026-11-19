"""Live: a pasted schedule (examples/sample_schedule.md) parsed by the smart tier (Sonnet).

docker compose exec api pytest -m live -k onboarding -s
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.tools import run_tool
from app.config import get_settings
from app.db.models import Proposal
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore
from tests.db.test_agent_tools import context

pytestmark = pytest.mark.live

SAMPLE = Path(__file__).resolve().parents[3] / "examples" / "sample_schedule.md"


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    if not env_value(get_settings(), "ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    if not SAMPLE.is_file():
        pytest.skip("examples/ not mounted")
    router = build_router(store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


async def test_pasted_schedule_is_parsed_by_sonnet(
    session: AsyncSession, router: LLMRouter
) -> None:
    text = SAMPLE.read_text(encoding="utf-8")
    table = text[text.index("| Gün") : text.index("## Diğer")].strip()
    ctx = context(session, "onboarding")
    ctx.llm = router

    result = await run_tool("propose_schedule", {"text": table}, ctx)

    print(f"\nparsed by {result.get('parsed_by')}:\n{result.get('table')}")
    print(f"unclear: {result.get('unclear')}")
    assert "error" not in result, result
    assert result["parsed_by"].startswith("anthropic/claude-sonnet")
    proposal = await session.get(Proposal, result["proposal_id"])
    assert proposal is not None
    by_day = {
        (day, entry["start_time"][:5], entry["kind"])
        for entry in proposal.entries
        for day in entry["weekdays"]
    }
    assert ("monday", "09:00", "class") in by_day  # MATH221
    assert ("wednesday", "09:00", "class") in by_day
    assert ("wednesday", "13:00", "lab") in by_day  # EE211 lab
    assert ("thursday", "15:00", "lab") in by_day  # Fizik II problem saati
    assert len(by_day) == 9
