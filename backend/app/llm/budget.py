"""Monthly Claude budget guard (CLAUDE_MONTHLY_BUDGET_USD).

>= downgrade_at (80%): tiers are downgraded (smart -> fallback).
>= limit_at (100%):    only `allowed_at_limit` tiers (fast, local) may run.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.llm.config import BudgetConfig
from app.llm.usage import UsageStore, month_start


class BudgetLevel(StrEnum):
    OK = "ok"
    DOWNGRADE = "downgrade"
    LIMIT = "limit"


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    provider: str
    limit_usd: Decimal
    spent_usd: Decimal
    level: BudgetLevel

    @property
    def ratio(self) -> float | None:
        return float(self.spent_usd / self.limit_usd) if self.limit_usd > 0 else None


def budget_level(spent: Decimal, limit: Decimal, config: BudgetConfig) -> BudgetLevel:
    if limit <= 0:
        return BudgetLevel.LIMIT  # a zero budget means "no Claude"
    ratio = spent / limit
    if ratio >= Decimal(str(config.limit_at)):
        return BudgetLevel.LIMIT
    if ratio >= Decimal(str(config.downgrade_at)):
        return BudgetLevel.DOWNGRADE
    return BudgetLevel.OK


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class BudgetGuard:
    def __init__(
        self,
        config: BudgetConfig,
        limit_usd: Decimal,
        store: UsageStore,
        tz: ZoneInfo,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self.config = config
        self.limit_usd = limit_usd
        self._store = store
        self._tz = tz
        self._clock = clock

    async def status(self) -> BudgetStatus:
        spent = await self._store.spend_since(
            month_start(self._clock(), self._tz), self.config.provider
        )
        return BudgetStatus(self.config.provider, self.limit_usd, spent, self._level(spent))

    def _level(self, spent: Decimal) -> BudgetLevel:
        return budget_level(spent, self.limit_usd, self.config)

    def apply(self, chain: list[str], level: BudgetLevel) -> list[str]:
        """Rewrite a tier chain for the budget level (order kept, duplicates removed)."""
        if level is BudgetLevel.DOWNGRADE:
            chain = [self.config.downgrade.get(tier, tier) for tier in chain]
        elif level is BudgetLevel.LIMIT:
            allowed = self.config.allowed_at_limit
            chain = [tier if tier in allowed else allowed[0] for tier in chain]
        return list(dict.fromkeys(chain))
