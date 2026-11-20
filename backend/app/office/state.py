"""The office's live state. `Office.set_state` is the only writer of employee_state: it
stores the row and publishes the change to every /api/office/stream subscriber.

Nothing here may break a chat message: database errors are logged and swallowed, and an
office that could not start (tables missing, database down) does nothing at all.
"""

import asyncio
import datetime as dt
import logging
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.team import TeamConfig
from app.db.models import Employee, EmployeeState
from app.db.models.enums import Activity
from app.office.budget import over_budget, spent_today
from app.office.sync import sync_employees

logger = logging.getLogger(__name__)
QUESTION = "question"  # needs_user: an open question waits for the user's answer
BUDGET = "budget"  # needs_user: the daily budget is used up, shift jobs stopped
SUBSCRIBER_QUEUE = 256
RETRY_START_SECONDS = 60.0


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True, slots=True)
class StateView:
    employee_id: str
    activity: Activity
    since: dt.datetime
    updated_at: dt.datetime
    task: str | None = None
    tool: str | None = None
    meeting_with: str | None = None
    needs_user: bool = False
    needs_user_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "activity": self.activity.value,
            "task": self.task,
            "tool": self.tool,
            "meeting_with": self.meeting_with,
            "needs_user": self.needs_user,
            "needs_user_reason": self.needs_user_reason,
            "since": self.since.isoformat(),
            "ts": self.updated_at.isoformat(),
        }

    def same_as(self, other: "StateView") -> bool:
        keys = ("activity", "task", "tool", "meeting_with", "needs_user", "needs_user_reason")
        return all(getattr(self, k) == getattr(other, k) for k in keys)


@dataclass(frozen=True, slots=True)
class EmployeeInfo:
    id: str
    name: str
    role: str
    color: str
    desk_row: str
    desk_col: int
    is_coordinator: bool
    domain: str
    shift: str
    daily_budget_usd: Decimal | None

    @classmethod
    def of(cls, row: Employee) -> "EmployeeInfo":
        return cls(
            row.id,
            row.name,
            row.role,
            row.color,
            row.desk_row.value,
            row.desk_col,
            row.is_coordinator,
            row.domain,
            row.shift,
            row.daily_budget_usd,
        )


class OfficeHub:
    """In-process publish/subscribe (one API process). A subscriber that cannot keep up
    loses events; it reloads the snapshot when it reconnects."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Office subscriber is not reading; event dropped")

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(SUBSCRIBER_QUEUE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)


@dataclass(slots=True)
class Office:
    sessionmaker: async_sessionmaker[AsyncSession]
    config: TeamConfig
    tz: ZoneInfo
    clock: Callable[[], dt.datetime] = _utc_now
    hub: OfficeHub = field(default_factory=OfficeHub)
    ready: bool = False
    employees: dict[str, EmployeeInfo] = field(default_factory=dict)
    _states: dict[str, StateView] = field(default_factory=dict)
    # How many running jobs (chat messages, delegations, shifts) hold each employee: it
    # goes back to break only when the last one ends.
    _busy: Counter[str] = field(default_factory=Counter)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _failed_at: dt.datetime | None = None

    @property
    def coordinator_id(self) -> str:
        return self.config.coordinator.id

    async def start(self) -> bool:
        """Sync employees from agents.yaml and load their states (startup). Nothing can
        set a state before this succeeds, so a stored working / meeting is from a stopped
        process: it goes back to break."""
        async with self._start_lock:
            if self.ready:
                return True
            return await self._start()

    async def _start(self) -> bool:
        now = self.clock()
        try:
            async with self.sessionmaker() as session:
                rows = await sync_employees(session, self.config, now, reset_activity=True)
                infos = {row.id: EmployeeInfo.of(row) for row in rows}
                states = (
                    await session.scalars(
                        select(EmployeeState).where(EmployeeState.employee_id.in_(list(infos)))
                    )
                ).all()
                await session.commit()
        except Exception:
            logger.exception("The office could not start (migrations applied?)")
            self._failed_at = now
            return False
        self.employees = infos
        self._states = {
            s.employee_id: StateView(
                s.employee_id,
                s.activity,
                s.since,
                s.updated_at,
                s.current_task,
                s.tool,
                s.meeting_with,
                s.needs_user,
                s.needs_user_reason,
            )
            for s in states
        }
        self.ready = True
        logger.info("Office ready: %d employees", len(infos))
        return True

    async def ensure_ready(self) -> bool:
        if self.ready:
            return True
        failed = self._failed_at
        if failed is not None and (self.clock() - failed).total_seconds() < RETRY_START_SECONDS:
            return False
        return await self.start()

    def employee_id(self, member_id: str) -> str | None:
        """The employee a member speaks for: the setup assistant is the coordinator."""
        if member_id == "onboarding":
            member_id = self.coordinator_id
        return member_id if member_id in self.employees else None

    def state(self, employee_id: str) -> StateView | None:
        return self._states.get(employee_id)

    # ---- the one writer ------------------------------------------------------------

    async def set_state(
        self,
        employee_id: str,
        activity: Activity,
        *,
        task: str | None = None,
        tool: str | None = None,
        meeting_with: str | None = None,
        needs_user: bool | None = None,
        needs_user_reason: str | None = None,
    ) -> StateView | None:
        """Activity, task, tool and meeting partner are replaced; `needs_user` None keeps
        the flag (and its reason) as it is. Returns the new state, None if nothing
        changed or the employee is unknown."""
        if not self.ready or employee_id not in self.employees:
            return None
        async with self._lock:
            now = self.clock()
            old = self._states.get(employee_id)
            flag = old.needs_user if old is not None else False
            reason = old.needs_user_reason if old is not None else None
            if needs_user is not None:
                flag, reason = needs_user, (needs_user_reason if needs_user else None)
            new = StateView(
                employee_id,
                activity,
                since=old.since if old is not None and old.activity is activity else now,
                updated_at=now,
                task=task,
                tool=tool,
                meeting_with=meeting_with,
                needs_user=flag,
                needs_user_reason=reason,
            )
            if old is not None and old.same_as(new):
                return None
            self._states[employee_id] = new
            await self._store(new)
        self.hub.publish({"type": "state", **new.as_dict()})
        return new

    async def _store(self, state: StateView) -> None:
        values = {
            "activity": state.activity,
            "current_task": state.task,
            "tool": state.tool,
            "meeting_with": state.meeting_with,
            "needs_user": state.needs_user,
            "needs_user_reason": state.needs_user_reason,
            "since": state.since,
            "updated_at": state.updated_at,
        }
        statement = insert(EmployeeState).values(employee_id=state.employee_id, **values)
        try:
            async with self.sessionmaker() as session:
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[EmployeeState.employee_id], set_=values
                    )
                )
                await session.commit()
        except Exception:  # the live state is still right; only the stored copy lags
            logger.exception("Could not store the state of %s", state.employee_id)

    # ---- helpers on top of set_state ---------------------------------------------------

    async def flag(self, employee_id: str, reason: str) -> None:
        """Red dot: the employee waits for the user."""
        current = self._states.get(employee_id)
        if current is None:
            return
        if current.needs_user and current.needs_user_reason == QUESTION and reason != QUESTION:
            return  # an open question says more than a budget warning
        await self._keep_activity(current, needs_user=True, needs_user_reason=reason)

    async def unflag(self, employee_id: str, reason: str) -> None:
        current = self._states.get(employee_id)
        if current is not None and current.needs_user and current.needs_user_reason == reason:
            await self._keep_activity(current, needs_user=False)

    async def _keep_activity(self, current: StateView, **flags: Any) -> None:
        await self.set_state(
            current.employee_id,
            current.activity,
            task=current.task,
            tool=current.tool,
            meeting_with=current.meeting_with,
            **flags,
        )

    def acquire(self, employee_id: str) -> None:
        self._busy[employee_id] += 1

    async def release(self, employee_id: str) -> None:
        """One job of the employee ended: break once nothing else holds it."""
        if self._busy[employee_id] > 0:
            self._busy[employee_id] -= 1
        if self._busy[employee_id] == 0:
            del self._busy[employee_id]
            await self.set_state(employee_id, Activity.BREAK)

    def busy(self, employee_id: str) -> bool:
        return self._busy[employee_id] > 0

    # ---- budget ------------------------------------------------------------------------

    async def spent_today(self, employee_ids: Iterable[str] | None = None) -> dict[str, Decimal]:
        ids = list(employee_ids if employee_ids is not None else self.employees)
        async with self.sessionmaker() as session:
            return await spent_today(session, self.clock(), self.tz, ids)

    async def over_budget(self, employee_id: str) -> bool:
        info = self.employees.get(employee_id)
        if not self.ready or info is None:
            return False
        try:
            spent = (await self.spent_today([employee_id]))[employee_id]
        except Exception:
            logger.exception("Could not read today's spend of %s", employee_id)
            return False
        return over_budget(spent, info.daily_budget_usd)

    async def refresh_budget_flags(
        self, employee_ids: Iterable[str] | None = None
    ) -> dict[str, Decimal]:
        """Sets / clears the budget red dot from today's spend; returns the spend."""
        if not self.ready:
            return {}
        try:
            spent = await self.spent_today(employee_ids)
        except Exception:
            logger.exception("Could not read today's spend")
            return {}
        for employee_id, amount in spent.items():
            info = self.employees.get(employee_id)
            if info is None:
                continue
            if over_budget(amount, info.daily_budget_usd):
                await self.flag(employee_id, BUDGET)
            else:
                await self.unflag(employee_id, BUDGET)
        return spent

    # ---- reading -----------------------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        """Every active employee with its desk, state and today's spend."""
        now = self.clock()
        if not await self.ensure_ready():
            return {"ready": False, "employees": [], "ts": now.isoformat()}
        spent = await self.refresh_budget_flags()
        employees = []
        for info in self.employees.values():
            state = self._states.get(info.id) or StateView(info.id, Activity.BREAK, now, now)
            employees.append(
                {
                    "id": info.id,
                    "name": info.name,
                    "role": info.role,
                    "color": info.color,
                    "desk": {"row": info.desk_row, "col": info.desk_col},
                    "is_coordinator": info.is_coordinator,
                    "domain": info.domain,
                    "shift": info.shift,
                    "daily_budget_usd": (
                        float(info.daily_budget_usd) if info.daily_budget_usd is not None else None
                    ),
                    "spent_today_usd": float(spent.get(info.id, Decimal(0))),
                    **state.as_dict(),
                }
            )
        return {"ready": True, "employees": employees, "ts": now.isoformat()}

    def publish_notes(self, notes: Iterable[dict[str, Any]]) -> None:
        """Notebook entries of a committed message."""
        for note in notes:
            created = note.get("created_at")
            self.hub.publish(
                {
                    "type": "note",
                    "employee_id": note["employee_id"],
                    "note": {
                        "id": note["id"],
                        "content": note["content"],
                        "created_at": created.isoformat()
                        if isinstance(created, dt.datetime)
                        else created,
                    },
                    "ts": self.clock().isoformat(),
                }
            )


@lru_cache
def get_office() -> Office:
    from app.agent.team import load_team_config
    from app.config import get_settings
    from app.db.session import get_sessionmaker

    return Office(get_sessionmaker(), load_team_config(), get_settings().tz)
