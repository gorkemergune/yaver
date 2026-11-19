"""LLM usage accounting: cost calculation, persistence (llm_usage) and monthly totals."""

import datetime as dt
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LlmUsage
from app.llm.config import PER_MILLION, PriceTable
from app.llm.types import TokenUsage

logger = logging.getLogger(__name__)
COST_QUANTUM = Decimal("0.000001")


def compute_cost(
    prices: PriceTable, provider: str, model: str, usage: TokenUsage, *, reports_cost: bool
) -> Decimal | None:
    """USD cost of one call. Provider-reported cost wins; None if the model has no price."""
    if reports_cost and usage.reported_cost_usd is not None:
        return usage.reported_cost_usd.quantize(COST_QUANTUM)
    price = prices.lookup(provider, model)
    if price is None:
        return None
    rates = price.rates_for(usage.prompt_tokens)
    cache_read = rates.cache_read if rates.cache_read is not None else rates.input
    cache_write = rates.cache_write if rates.cache_write is not None else rates.input
    total = (
        usage.input_tokens * rates.input
        + usage.output_tokens * rates.output
        + usage.cached_input_tokens * cache_read
        + usage.cache_write_tokens * cache_write
    ) / PER_MILLION
    return total.quantize(COST_QUANTUM)


def month_start(now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """Start of the current calendar month in `tz`, as a UTC instant."""
    local = now.astimezone(tz)
    first = dt.datetime(local.year, local.month, 1, tzinfo=tz)
    return first.astimezone(dt.UTC)


@dataclass(slots=True)
class UsageRecord:
    provider: str
    model: str
    tier: str
    purpose: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: Decimal = Decimal(0)
    agent_id: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


class UsageStore(Protocol):
    async def record(self, record: UsageRecord) -> int | None: ...

    async def spend_since(self, since: dt.datetime, provider: str | None = None) -> Decimal: ...


class InMemoryUsageStore:
    """For tests and for running without a database."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> int | None:
        self.records.append(record)
        return len(self.records)

    async def spend_since(self, since: dt.datetime, provider: str | None = None) -> Decimal:
        return sum(
            (
                r.cost_usd
                for r in self.records
                if r.created_at >= since and (provider is None or r.provider == provider)
            ),
            Decimal(0),
        )


class DbUsageStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(self, record: UsageRecord) -> int | None:
        row = LlmUsage(
            provider=record.provider,
            model=record.model,
            tier=record.tier,
            purpose=record.purpose,
            agent_id=record.agent_id,
            input_tokens=record.usage.input_tokens,
            output_tokens=record.usage.output_tokens,
            cached_input_tokens=record.usage.cached_input_tokens,
            cache_write_tokens=record.usage.cache_write_tokens,
            cost_usd=record.cost_usd,
            latency_ms=record.latency_ms,
            error=record.error,
            created_at=record.created_at,
        )
        async with self._sessionmaker() as session:
            session.add(row)
            await session.commit()
            return row.id

    async def spend_since(self, since: dt.datetime, provider: str | None = None) -> Decimal:
        query = select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
            LlmUsage.created_at >= since
        )
        if provider is not None:
            query = query.where(LlmUsage.provider == provider)
        async with self._sessionmaker() as session:
            total = await session.scalar(query)
        return Decimal(total or 0)


async def month_summary(session: AsyncSession, now: dt.datetime, tz: ZoneInfo) -> dict[str, Any]:
    """Per provider/model/tier totals for the current month (local time)."""
    since = month_start(now, tz)
    rows = (
        await session.execute(
            select(
                LlmUsage.provider,
                LlmUsage.model,
                LlmUsage.tier,
                func.count(),
                func.count(LlmUsage.error),
                func.sum(LlmUsage.input_tokens),
                func.sum(LlmUsage.output_tokens),
                func.sum(LlmUsage.cached_input_tokens),
                func.sum(LlmUsage.cache_write_tokens),
                func.sum(LlmUsage.cost_usd),
            )
            .where(LlmUsage.created_at >= since)
            .group_by(LlmUsage.provider, LlmUsage.model, LlmUsage.tier)
            .order_by(func.sum(LlmUsage.cost_usd).desc(), LlmUsage.provider, LlmUsage.model)
        )
    ).all()
    by_model: list[dict[str, Any]] = [
        {
            "provider": provider,
            "model": model,
            "tier": tier,
            "calls": calls,
            "errors": errors,
            "input_tokens": int(inp or 0),
            "output_tokens": int(out or 0),
            "cached_input_tokens": int(cached or 0),
            "cache_write_tokens": int(written or 0),
            "cost_usd": Decimal(cost or 0),
        }
        for provider, model, tier, calls, errors, inp, out, cached, written, cost in rows
    ]
    return {
        "month": since.astimezone(tz).strftime("%Y-%m"),
        "since": since,
        "total_usd": sum((m["cost_usd"] for m in by_model), Decimal(0)),
        "by_model": by_model,
    }
