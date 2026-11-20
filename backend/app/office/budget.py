"""Per-employee daily budget: the employee's llm_usage (agent_id) since local midnight."""

import datetime as dt
from collections.abc import Iterable
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LlmUsage


def day_start(now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """Local midnight of `now`'s day, as a UTC instant."""
    local = now.astimezone(tz)
    return dt.datetime.combine(local.date(), dt.time(), tzinfo=tz).astimezone(dt.UTC)


async def spent_today(
    session: AsyncSession, now: dt.datetime, tz: ZoneInfo, employee_ids: Iterable[str]
) -> dict[str, Decimal]:
    ids = list(employee_ids)
    spent = {employee_id: Decimal(0) for employee_id in ids}
    if not ids:
        return spent
    rows = (
        await session.execute(
            select(LlmUsage.agent_id, func.coalesce(func.sum(LlmUsage.cost_usd), 0))
            .where(LlmUsage.created_at >= day_start(now, tz), LlmUsage.agent_id.in_(ids))
            .group_by(LlmUsage.agent_id)
        )
    ).all()
    for agent_id, total in rows:
        spent[str(agent_id)] = Decimal(total or 0)
    return spent


def over_budget(spent: Decimal, limit: Decimal | None) -> bool:
    """`limit` None = no limit; a limit of 0 means no autonomous work at all."""
    return limit is not None and spent >= limit
