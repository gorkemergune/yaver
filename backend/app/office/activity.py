"""Who works on one chat message, told to the office as it happens.

  begin(member)          the employee who answers: working ("İsteği okuyor"), inbox row
  tool(member, name)     before every tool call: working + what the tool does
  delegate(a, b, text)   handover: both in a meeting, the delegate gets an inbox row
  tool(b, ...)           the delegate's first tool call ends the meeting: b at its desk,
                         the coordinator back to working (waiting for b)
  delegated(b, reply)    b is done: break (unless another message still holds it)
  close(...)             everyone left goes to break; an open question = red dot

Inbox rows (employee_tasks) go into the chat's own transaction: a cancelled message
leaves none. State changes are published at once (they are what is happening now).
"""

import datetime as dt
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmployeeTask
from app.db.models.enums import Activity, EmployeeTaskStatus, TaskOrigin
from app.office.labels import MERGING, preview, tool_label, waiting_for
from app.office.state import QUESTION, Office

logger = logging.getLogger(__name__)


class MessageActivity:
    def __init__(
        self,
        office: Office | None,
        session: AsyncSession,
        now: dt.datetime,
        conversation_id: int | None = None,
    ) -> None:
        self.office = office if office is not None and office.ready else None
        self.session = session
        self.now = now
        self.conversation_id = conversation_id
        self._held: list[str] = []  # acquired employee ids, released in close()
        self._meetings: dict[str, str] = {}  # delegate -> coordinator, while handing over
        self._tasks: dict[str, EmployeeTask] = {}
        self.asking: str | None = None  # left an open question (set by the coordinator)
        self.answered: str | None = None  # whose earlier question this message answered
        self.notes: list[dict[str, Any]] = []  # notebook entries (ToolContext.notes)

    def _id(self, member_id: str) -> str | None:
        return self.office.employee_id(member_id) if self.office is not None else None

    async def begin(self, member_id: str, request: str, *, source: TaskOrigin) -> None:
        employee = self._id(member_id)
        if employee is None or self.office is None:
            return
        self._hold(employee)
        await self._safe(self.office.set_state(employee, Activity.WORKING, task=preview(request)))
        await self._open_task(employee, request, source, requested_by=None)

    async def tool(self, member_id: str, tool_name: str) -> None:
        employee = self._id(member_id)
        if employee is None or self.office is None:
            return
        await self._end_meeting(employee)
        await self._safe(
            self.office.set_state(
                employee, Activity.WORKING, task=tool_label(tool_name), tool=tool_name
            )
        )

    async def delegate(self, coordinator_id: str, agent_id: str, instruction: str) -> None:
        coordinator, agent = self._id(coordinator_id), self._id(agent_id)
        if coordinator is None or agent is None or self.office is None:
            return
        self._hold(agent)
        self._meetings[agent] = coordinator
        task = preview(instruction)
        await self._safe(
            self.office.set_state(coordinator, Activity.MEETING, task=task, meeting_with=agent)
        )
        await self._safe(
            self.office.set_state(agent, Activity.MEETING, task=task, meeting_with=coordinator)
        )
        await self._open_task(agent, instruction, TaskOrigin.YAVER, requested_by=coordinator)

    async def delegated(self, agent_id: str, reply: str, tools: list[str]) -> None:
        agent = self._id(agent_id)
        if agent is None or self.office is None:
            return
        coordinator = self._meetings.get(agent)
        await self._end_meeting(agent, back_to_work=False)
        await self._finish_task(agent, reply, tools)
        if agent in self._held:
            self._held.remove(agent)
            await self._safe(self.office.release(agent))
        coordinator = coordinator or self.office.coordinator_id
        if coordinator in self._held:
            await self._safe(self.office.set_state(coordinator, Activity.WORKING, task=MERGING))

    async def finish(self, member_id: str, reply: str, tools: list[str]) -> None:
        """The answering employee's inbox row is done (the message succeeded)."""
        employee = self._id(member_id)
        if employee is not None:
            await self._finish_task(employee, reply, tools)

    def set_change_set(self, change_set_id: uuid.UUID | None) -> None:
        for task in self._tasks.values():
            task.change_set_id = change_set_id

    async def close(self) -> None:
        """After commit or rollback: everyone this message held goes back to break."""
        if self.office is None:
            return
        office = self.office
        for employee in list(self._meetings):
            await self._end_meeting(employee, back_to_work=False)
        held, self._held = self._held, []
        for employee in held:
            await self._safe(office.release(employee))
        answered = self._id(self.answered) if self.answered else None
        asking = self._id(self.asking) if self.asking else None
        if answered is not None and answered != asking:
            await self._safe(office.unflag(answered, QUESTION))
        if asking is not None:
            await self._safe(office.flag(asking, QUESTION))
        if held:
            await self._safe(office.refresh_budget_flags(held))

    # ---- internals ---------------------------------------------------------------------

    def _hold(self, employee: str) -> None:
        if self.office is not None and employee not in self._held:
            self.office.acquire(employee)
            self._held.append(employee)

    async def _end_meeting(self, agent: str, *, back_to_work: bool = True) -> None:
        coordinator = self._meetings.pop(agent, None)
        if coordinator is None or self.office is None:
            return
        name = self.office.employees[agent].name if agent in self.office.employees else agent
        if back_to_work:
            # the coordinator walks back to its room and waits for the result
            await self._safe(
                self.office.set_state(coordinator, Activity.WORKING, task=waiting_for(name))
            )

    async def _open_task(
        self, employee: str, instruction: str, source: TaskOrigin, requested_by: str | None
    ) -> None:
        if employee in self._tasks:  # one row per employee per message
            return
        task = EmployeeTask(
            employee_id=employee,
            source=source,
            requested_by=requested_by,
            instruction=instruction,
            status=EmployeeTaskStatus.RUNNING,
            conversation_id=self.conversation_id,
            started_at=self.now,
            created_at=self.now,
        )
        self.session.add(task)
        self._tasks[employee] = task

    async def _finish_task(self, employee: str, reply: str, tools: list[str]) -> None:
        task = self._tasks.get(employee)
        if task is None or task.status is not EmployeeTaskStatus.RUNNING:
            return
        task.status = EmployeeTaskStatus.DONE
        task.result = reply
        task.finished_at = max(self.now, self.office.clock()) if self.office else self.now
        task.details = {"tools": tools} if tools else None

    @staticmethod
    async def _safe(awaitable: Any) -> None:
        try:
            await awaitable
        except Exception:  # the office must never break a chat message
            logger.exception("Office state update failed")
