"""llm_usage persistence, monthly totals and GET /api/usage/month on real PostgreSQL."""

import datetime as dt
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LlmUsage
from app.db.session import get_session
from app.llm.types import TokenUsage
from app.llm.usage import DbUsageStore, UsageRecord, month_start, month_summary
from app.main import create_app
from tests.factories import IST

NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.UTC)


def _store(session: AsyncSession) -> DbUsageStore:
    return DbUsageStore(async_sessionmaker(session.bind, expire_on_commit=False))


async def test_record_and_spend_since(session: AsyncSession) -> None:
    store = _store(session)
    usage = TokenUsage(input_tokens=100, output_tokens=20, cached_input_tokens=2000)

    row_id = await store.record(
        UsageRecord(
            "anthropic",
            "claude-haiku-5-5",
            "fallback",
            "chat",
            usage=usage,
            cost_usd=Decimal("0.000123"),
            agent_id="academic",
            latency_ms=850,
            created_at=NOW,
        )
    )
    await store.record(
        UsageRecord(
            "groq", "openai/gpt-oss-120b", "fast", "chat", cost_usd=Decimal("0.5"), created_at=NOW
        )
    )
    await store.record(  # last month
        UsageRecord(
            "anthropic",
            "claude-haiku-5-5",
            "fallback",
            "chat",
            cost_usd=Decimal("9"),
            created_at=dt.datetime(2026, 10, 15, tzinfo=dt.UTC),
        )
    )

    row = await session.get(LlmUsage, row_id)
    assert row is not None
    assert (row.cached_input_tokens, row.agent_id, row.latency_ms) == (2000, "academic", 850)
    since = month_start(NOW, IST)
    assert await store.spend_since(since, "anthropic") == Decimal("0.000123")
    assert await store.spend_since(since) == Decimal("0.500123")


async def test_month_summary_groups_by_model(session: AsyncSession) -> None:
    store = _store(session)
    for cost, error in (("0.10", None), ("0.20", None), ("0", "rate limited")):
        await store.record(
            UsageRecord(
                "anthropic",
                "claude-haiku-5-5",
                "fallback",
                "chat",
                usage=TokenUsage(1000, 100),
                cost_usd=Decimal(cost),
                error=error,
                created_at=NOW,
            )
        )

    summary = await month_summary(session, NOW, IST)

    assert summary["month"] == "2026-11"
    assert summary["total_usd"] == Decimal("0.30")
    (haiku,) = summary["by_model"]
    assert (haiku["calls"], haiku["errors"], haiku["input_tokens"]) == (3, 1, 3000)


async def test_usage_endpoint(session: AsyncSession) -> None:
    store = _store(session)
    now = dt.datetime.now(dt.UTC)
    await store.record(
        UsageRecord(
            "anthropic",
            "claude-haiku-5-5",
            "fallback",
            "chat",
            usage=TokenUsage(1000, 100),
            cost_usd=Decimal("1.5"),
            created_at=now,
        )
    )
    await store.record(
        UsageRecord(
            "groq", "openai/gpt-oss-120b", "fast", "chat", cost_usd=Decimal("0.25"), created_at=now
        )
    )
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/usage/month")

    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Europe/Istanbul"
    assert body["total_usd"] == "1.750000"
    assert body["budget"]["provider"] == "anthropic"
    assert body["budget"]["spent_usd"] == "1.500000"
    assert [m["provider"] for m in body["by_model"]] == ["anthropic", "groq"]


async def test_record_returns_the_id_even_when_commit_expires_rows(session: AsyncSession) -> None:
    store = DbUsageStore(async_sessionmaker(session.bind))  # expire_on_commit=True (default)

    row_id = await store.record(UsageRecord("groq", "m", "fast", "chat", created_at=NOW))

    assert isinstance(row_id, int)
