"""Live: an Ads Manager CSV (made-up "Örnek Kafe" numbers) sent in the chat -> Metrics,
compared with the week before, analysed by Opus (deep tier), noted, answered.

One Opus call + one Metrics reply (~$0.05-0.10).
docker compose exec api pytest -m live -k ads -s
"""

import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ads.parse import parse_meta_csv
from app.ads.report import save_report
from app.agent.coordinator import Coordinator
from app.agent.team import get_team, load_team_config
from app.config import Settings, get_settings
from app.db.models import AdReport, EmployeeNote, LlmUsage
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore
from app.office.sync import sync_employees
from tests.ads.test_parse import WEEK_1, WEEK_2
from tests.db.test_ads import stored_csv
from tests.db.test_agent_tools import context

pytestmark = pytest.mark.live

NOW = dt.datetime(2026, 11, 16, 7, 0, tzinfo=dt.UTC)  # Monday after the second week


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    if not env_value(get_settings(), "ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    router = build_router(store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


async def test_a_weekly_csv_is_analysed_by_opus_and_relayed_by_metrics(
    session: AsyncSession, router: LLMRouter, tmp_path: Path
) -> None:
    await sync_employees(session, load_team_config(), NOW)  # Metrics' notebook exists
    week1 = context(session, "ads")
    await save_report(
        week1, parse_meta_csv(WEEK_1.encode()), source="csv", attachment_id=None, sha256=None
    )  # last week, no analysis
    attachment = await stored_csv(session, tmp_path, WEEK_2, "kampanyalar-9-15-kasim.csv")
    yaver = Coordinator(router, get_team(), Settings(_env_file=None, upload_dir=tmp_path))

    reply = await yaver.handle(session, "", now=NOW, attachment_ids=[attachment.id])

    rows = list((await session.scalars(select(LlmUsage).order_by(LlmUsage.id))).all())
    print(f"\n{reply.speaker}: {reply.reply}\n")
    for row in rows:
        print(
            f"  {row.purpose:<18} {row.tier:<8} {row.provider}/{row.model} "
            f"in={row.input_tokens} out={row.output_tokens} ${row.cost_usd} {row.error or ''}"
        )
    print(f"  total ${sum(r.cost_usd for r in rows)}")
    report = await session.scalar(
        select(AdReport).where(AdReport.source == "csv").order_by(AdReport.id.desc())
    )
    assert report is not None
    print(f"\n  summary: {report.summary}")
    for rec in report.recommendations or []:
        print(f"  - {rec}")

    assert reply.speaker == "ads"
    analysis = next(r for r in rows if r.purpose == "ads_weekly_report" and not r.error)
    assert (analysis.tier, analysis.model, analysis.agent_id) == ("deep", "claude-opus-5-5", "ads")
    assert report.recommendations is not None
    assert len(report.recommendations) == 3
    note = await session.scalar(select(EmployeeNote).where(EmployeeNote.employee_id == "ads"))
    assert note is not None
    assert note.content.startswith(f"Reklam analizi, 9-15 Kas 2026 (rapor #{report.id})")
