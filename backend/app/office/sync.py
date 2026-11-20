"""config/agents.yaml -> employees (+ an employee_state row each)."""

import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.team import AGENT_COLORS, COORDINATOR_COLOR, TeamConfig
from app.db.models import Employee, EmployeeState
from app.db.models.enums import Activity, DeskRow

COORDINATOR_ROLE = "Genel Müdür"


async def sync_employees(
    session: AsyncSession, config: TeamConfig, now: dt.datetime, *, reset_activity: bool = False
) -> list[Employee]:
    """Upserts every member of the team; employees no longer in the file become inactive
    (their notes and tasks stay). `reset_activity` (startup): nothing runs yet, so a
    working / meeting state left by a stopped process goes back to break."""
    desks = config.desks()
    office_budget = config.office.daily_budget_usd
    members = [(config.coordinator, True), *((agent, False) for agent in config.agents)]
    existing = {e.id: e for e in (await session.scalars(select(Employee))).all()}
    synced: list[Employee] = []
    for order, (member, is_coordinator) in enumerate(members):
        row, col = desks[member.id]
        if is_coordinator:
            color = member.color or COORDINATOR_COLOR
            role = member.role or COORDINATOR_ROLE
            domain = ""
        else:
            color = member.color or AGENT_COLORS[(order - 1) % len(AGENT_COLORS)]
            role = member.role or (getattr(member, "briefing_section", None) or "")
            domain = getattr(member, "domain", "")
        values = {
            "name": member.name,
            "role": role,
            "color": color,
            "desk_row": DeskRow(row),
            "desk_col": col,
            "persona": member.persona.strip(),
            "domain": domain,
            "shift": member.shift,
            "tools": list(member.tools),
            "daily_budget_usd": (
                member.daily_budget_usd if member.daily_budget_usd is not None else office_budget
            ),
            "is_coordinator": is_coordinator,
            "active": True,
            "sort_order": order,
        }
        employee = existing.get(member.id)
        if employee is None:
            employee = Employee(id=member.id, **values)
            session.add(employee)
        else:
            for key, value in values.items():
                setattr(employee, key, value)
        synced.append(employee)
    kept = {e.id for e in synced}
    for employee in existing.values():
        if employee.id not in kept:
            employee.active = False
    await session.flush()

    states = set((await session.scalars(select(EmployeeState.employee_id))).all())
    for employee in synced:
        if employee.id not in states:
            session.add(
                EmployeeState(
                    employee_id=employee.id, activity=Activity.BREAK, since=now, updated_at=now
                )
            )
    if reset_activity:
        await session.execute(
            update(EmployeeState)
            .where(EmployeeState.activity.in_([Activity.WORKING, Activity.MEETING]))
            .values(
                activity=Activity.BREAK,
                current_task=None,
                tool=None,
                meeting_with=None,
                since=now,
                updated_at=now,
            )
        )
    await session.flush()
    return synced
