"""Monthly Claude budget guard (CLAUDE_MONTHLY_BUDGET_USD).

>= downgrade_at (80%): tiers are downgraded (smart -> fallback).
>= limit_at (100%):    tiers on the budgeted provider (Claude) are dropped from the chain,
                       whichever tier name they have (fast may be Haiku). A chain with
                       nothing left uses `allowed_at_limit` (also minus Claude tiers).

Some tiers also have their own monthly limit (`tier_limits`: deep = Opus,
DEEP_MONTHLY_BUDGET_USD). Once this month's spend on that tier reaches it, the tier is
replaced by its `over_limit` tier; its spend still counts toward the Claude budget.
"""

import datetime as dt
from collections.abc import Callable, Mapping
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
class TierBudget:
    tier: str
    limit_usd: Decimal
    spent_usd: Decimal
    over_limit: str  # used instead once spent >= limit

    @property
    def reached(self) -> bool:
        return self.limit_usd <= 0 or self.spent_usd >= self.limit_usd


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
        *,
        tier_providers: Mapping[str, str],
        tier_limits: Mapping[str, Decimal] | None = None,
    ) -> None:
        self.config = config
        self._tier_providers = dict(tier_providers)
        self.tier_limits = dict(tier_limits or {})  # tier -> USD this month (from .env)
        self.limit_usd = limit_usd
        self._store = store
        self._tz = tz
        self._clock = clock

    async def status(self) -> BudgetStatus:
        spent = await self._store.spend_since(
            month_start(self._clock(), self._tz), self.config.provider
        )
        return BudgetStatus(self.config.provider, self.limit_usd, spent, self._level(spent))

    async def tier_budgets(self) -> list[TierBudget]:
        since = month_start(self._clock(), self._tz)
        return [
            TierBudget(
                tier,
                limit,
                await self._store.spend_since(since, tier=tier),
                self.config.tier_limits[tier].over_limit,
            )
            for tier, limit in sorted(self.tier_limits.items())
            if tier in self.config.tier_limits
        ]

    async def apply_tier_limits(self, chain: list[str]) -> list[str]:
        """Tiers over their own monthly limit step down (order kept, duplicates removed)."""
        if not any(tier in self.tier_limits for tier in chain):
            return chain
        reached = {b.tier: b.over_limit for b in await self.tier_budgets() if b.reached}
        return list(dict.fromkeys(reached.get(tier, tier) for tier in chain))

    def _level(self, spent: Decimal) -> BudgetLevel:
        return budget_level(spent, self.limit_usd, self.config)

    def apply(self, chain: list[str], level: BudgetLevel) -> list[str]:
        """Rewrite a tier chain for the budget level (order kept, duplicates removed)."""
        if level is BudgetLevel.DOWNGRADE:
            chain = [self.config.downgrade.get(tier, tier) for tier in chain]
        elif level is BudgetLevel.LIMIT:
            chain = [tier for tier in chain if not self._budgeted(tier)]
            if not chain:
                chain = [t for t in self.config.allowed_at_limit if not self._budgeted(t)]
        return list(dict.fromkeys(chain))

    def _budgeted(self, tier: str) -> bool:
        return self._tier_providers.get(tier) == self.config.provider
