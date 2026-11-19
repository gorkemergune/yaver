import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.llm.budget import BudgetLevel, budget_level
from app.llm.config import load_providers_config
from app.llm.usage import month_summary

router = APIRouter(prefix="/usage", tags=["usage"])


class ModelUsage(BaseModel):
    provider: str
    model: str
    tier: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    cost_usd: Decimal


class BudgetInfo(BaseModel):
    provider: str
    limit_usd: Decimal
    spent_usd: Decimal
    ratio: float | None
    level: BudgetLevel


class MonthUsage(BaseModel):
    month: str
    timezone: str
    since: dt.datetime
    total_usd: Decimal
    budget: BudgetInfo
    by_model: list[ModelUsage]


@router.get("/month")
async def usage_this_month(session: AsyncSession = Depends(get_session)) -> MonthUsage:
    settings = get_settings()
    budget_config = load_providers_config().budget
    summary = await month_summary(session, dt.datetime.now(dt.UTC), settings.tz)
    limit = Decimal(str(settings.claude_monthly_budget_usd))
    spent = sum(
        (m["cost_usd"] for m in summary["by_model"] if m["provider"] == budget_config.provider),
        Decimal(0),
    )
    return MonthUsage(
        month=summary["month"],
        timezone=settings.app_timezone,
        since=summary["since"],
        total_usd=summary["total_usd"],
        budget=BudgetInfo(
            provider=budget_config.provider,
            limit_usd=limit,
            spent_usd=spent,
            ratio=float(spent / limit) if limit > 0 else None,
            level=budget_level(spent, limit, budget_config),
        ),
        by_model=[ModelUsage(**m) for m in summary["by_model"]],
    )
