"""Shift jobs (mesai): scheduled work an employee does on its own. Each one shows the
employee working while it runs and stops when the employee's daily budget is used up
(the red dot tells the user). O3 adds the employees' own jobs; the existing scheduled
jobs (briefing, check-in, ...) already run through here."""

import logging
from collections.abc import Awaitable, Callable

from app.db.models.enums import Activity
from app.office.state import BUDGET, Office

logger = logging.getLogger(__name__)


class OverBudgetError(Exception):
    def __init__(self, employee_id: str) -> None:
        super().__init__(f"daily budget of {employee_id} is used up")
        self.employee_id = employee_id


async def run_shift[T](
    office: Office | None,
    employee_id: str,
    task: str,
    job: Callable[[], Awaitable[T]],
    *,
    check_budget: bool = True,
) -> T:
    """Runs `job` as the employee's shift. OverBudgetError (job not run) when the budget
    is used up; `check_budget=False` for a run the user asked for."""
    if office is None or not await office.ensure_ready() or office.employee_id(employee_id) is None:
        return await job()
    if check_budget and await office.over_budget(employee_id):
        logger.warning("Shift of %s skipped: daily budget used up (%s)", employee_id, task)
        await office.flag(employee_id, BUDGET)
        raise OverBudgetError(employee_id)
    office.acquire(employee_id)
    try:
        await office.set_state(employee_id, Activity.WORKING, task=task)
    except Exception:
        logger.exception("Office state update failed")
    try:
        return await job()
    finally:
        try:
            await office.release(employee_id)
            await office.refresh_budget_flags([employee_id])
        except Exception:
            logger.exception("Office state update failed")
