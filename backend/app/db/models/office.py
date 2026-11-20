"""The office (docs/OFFICE.md): every agent is an employee with a desk, a state, a notebook
and an inbox. `employees` mirrors config/agents.yaml (app.office.sync); the id is the agent
id ("yaver", "academic", ...)."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin
from app.db.models.enums import Activity, DeskRow, EmployeeTaskStatus, TaskOrigin
from app.db.types import str_enum


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(100), default="", server_default="")
    color: Mapped[str] = mapped_column(String(7))
    desk_row: Mapped[DeskRow] = mapped_column(str_enum(DeskRow, "desk_row"))
    desk_col: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    persona: Mapped[str] = mapped_column(Text, default="", server_default="")
    domain: Mapped[str] = mapped_column(Text, default="", server_default="")
    shift: Mapped[str] = mapped_column(Text, default="", server_default="")  # mesai planı
    tools: Mapped[list[str]] = mapped_column(JSONB, default=list)
    daily_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    is_coordinator: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Removed from agents.yaml: kept (its notes and tasks stay), hidden from the office.
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class EmployeeState(Base):
    """One row per employee; written only by app.office.state.Office.set_state."""

    __tablename__ = "employee_state"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    activity: Mapped[Activity] = mapped_column(str_enum(Activity, "activity"))
    current_task: Mapped[str | None] = mapped_column(Text)
    tool: Mapped[str | None] = mapped_column(String(100))  # the tool being called, if any
    meeting_with: Mapped[str | None] = mapped_column(String(50))
    needs_user: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    needs_user_reason: Mapped[str | None] = mapped_column(String(20))  # question | budget
    since: Mapped[dt.datetime]  # when the activity started
    updated_at: Mapped[dt.datetime]


class EmployeeNote(CreatedAtMixin, Base):
    """The employee's notebook (defter): short dated notes. Undoable (change_log)."""

    __tablename__ = "employee_notes"
    __table_args__ = (Index("ix_employee_notes_employee_id_id", "employee_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="agent", server_default="agent")


class EmployeeTask(CreatedAtMixin, Base):
    """The employee's inbox: one row per job it got (a chat message, a delegation, a shift)."""

    __tablename__ = "employee_tasks"
    __table_args__ = (Index("ix_employee_tasks_employee_id_id", "employee_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    source: Mapped[TaskOrigin] = mapped_column(str_enum(TaskOrigin, "task_origin"))
    requested_by: Mapped[str | None] = mapped_column(String(50))  # employee id (delegation)
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[EmployeeTaskStatus] = mapped_column(
        str_enum(EmployeeTaskStatus, "employee_task_status")
    )
    result: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    started_at: Mapped[dt.datetime | None]
    finished_at: Mapped[dt.datetime | None]
