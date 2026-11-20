"""One employee: notebook, inbox and a direct chat (its own prompt and tools, the same
change_set / undo as the main chat). Messages of a direct chat are read with
/api/conversations/{id}/messages like any other conversation."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator, unsent_attachments
from app.agent.loop import Emit
from app.api.chat import (
    ChatResponse,
    get_coordinator,
    get_session_factory,
    response_of,
    stream_reply,
)
from app.db.models import Conversation, Employee, EmployeeNote, EmployeeTask
from app.db.models.enums import ConversationMode
from app.db.session import get_session
from app.office.state import Office, get_office

router = APIRouter(tags=["employees"])


def _when(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _employee(session: AsyncSession, employee_id: str) -> Employee:
    employee = await session.get(Employee, employee_id)
    if employee is None or not employee.active:
        raise HTTPException(404, detail={"code": "unknown_employee", "id": employee_id})
    return employee


@router.get("/employees/{employee_id}/notes")
async def notes(
    employee_id: str,
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, description="note id: older notes (paging)"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The notebook (defter), newest first."""
    employee = await _employee(session, employee_id)
    query = select(EmployeeNote).where(EmployeeNote.employee_id == employee.id)
    if before is not None:
        query = query.where(EmployeeNote.id < before)
    rows = (await session.scalars(query.order_by(EmployeeNote.id.desc()).limit(limit))).all()
    return {
        "employee_id": employee.id,
        "notes": [
            {
                "id": row.id,
                "content": row.content,
                "source": row.source,
                "created_at": _when(row.created_at),
            }
            for row in rows
        ],
    }


@router.get("/employees/{employee_id}/tasks")
async def tasks(
    employee_id: str,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The inbox (gelen kutusu), newest first."""
    employee = await _employee(session, employee_id)
    rows = (
        await session.scalars(
            select(EmployeeTask)
            .where(EmployeeTask.employee_id == employee.id)
            .order_by(EmployeeTask.id.desc())
            .limit(limit)
        )
    ).all()
    return {
        "employee_id": employee.id,
        "tasks": [
            {
                "id": row.id,
                "source": row.source.value,
                "requested_by": row.requested_by,
                "instruction": row.instruction,
                "status": row.status.value,
                "result": row.result,
                "conversation_id": row.conversation_id,
                "change_set_id": row.change_set_id,
                "tools": (row.details or {}).get("tools", []),
                "started_at": _when(row.started_at),
                "finished_at": _when(row.finished_at),
            }
            for row in rows
        ],
    }


@router.get("/employees/{employee_id}/chat")
async def latest_chat(
    employee_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """The employee's latest direct chat (its messages: /api/conversations/{id}/messages)."""
    employee = await _employee(session, employee_id)
    query = select(Conversation.id).where(Conversation.mode == ConversationMode.CHAT)
    query = query.where(
        Conversation.employee_id.is_(None)
        if employee.is_coordinator
        else Conversation.employee_id == employee.id
    )
    conversation_id = await session.scalar(
        query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(1)
    )
    return {"employee_id": employee.id, "conversation_id": conversation_id}


class EmployeeChatRequest(BaseModel):
    message: str = Field("", max_length=20000)
    # None: the employee's latest direct chat (a new one if there is none)
    conversation_id: int | None = None
    attachment_ids: list[int] = Field(default_factory=list, max_length=6)


async def _conversation_for(
    session: AsyncSession, coordinator: Coordinator, employee_id: str, body: EmployeeChatRequest
) -> int | None:
    """The conversation to continue; 404 unknown employee, 422 someone else's chat."""
    team = coordinator.team
    is_coordinator = employee_id == team.coordinator.id
    if not is_coordinator and team.get(employee_id) is None:
        raise HTTPException(404, detail={"code": "unknown_employee", "id": employee_id})
    if not body.message.strip() and not body.attachment_ids:
        raise HTTPException(422, detail={"code": "empty_message"})
    try:
        await unsent_attachments(session, body.attachment_ids)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "bad_attachments", "message": str(exc)}) from exc
    owner = None if is_coordinator else employee_id
    if body.conversation_id is not None:
        conversation = await session.get(Conversation, body.conversation_id)
        if conversation is None or conversation.employee_id != owner:
            raise HTTPException(422, detail={"code": "not_this_employees_chat"})
        return conversation.id
    query = select(Conversation.id).where(Conversation.mode == ConversationMode.CHAT)
    query = query.where(
        Conversation.employee_id.is_(None) if owner is None else Conversation.employee_id == owner
    )
    latest: int | None = await session.scalar(
        query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(1)
    )
    return latest


async def _office_ready(office: Office | None) -> None:
    # a direct chat is stored on the employee: its row must exist
    if office is None or not await office.ensure_ready():
        raise HTTPException(503, detail={"code": "office_not_ready"})


@router.post("/employees/{employee_id}/chat")
async def chat(
    employee_id: str,
    body: EmployeeChatRequest,
    session: AsyncSession = Depends(get_session),
    coordinator: Coordinator = Depends(get_coordinator),
    office: Office | None = Depends(get_office),
) -> ChatResponse:
    await _office_ready(office)
    conversation_id = await _conversation_for(session, coordinator, employee_id, body)
    reply = await coordinator.handle(
        session,
        body.message,
        conversation_id=conversation_id,
        attachment_ids=body.attachment_ids,
        employee_id=employee_id,
    )
    return response_of(reply)


@router.post("/employees/{employee_id}/chat/stream")
async def chat_stream(
    employee_id: str,
    body: EmployeeChatRequest,
    coordinator: Coordinator = Depends(get_coordinator),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    office: Office | None = Depends(get_office),
) -> Any:
    """The same events as /api/chat/stream."""
    await _office_ready(office)
    async with session_factory() as check:
        conversation_id = await _conversation_for(check, coordinator, employee_id, body)

    async def answer(emit: Emit) -> ChatReply:
        async with session_factory() as session:
            return await coordinator.handle(
                session,
                body.message,
                conversation_id=conversation_id,
                emit=emit,
                attachment_ids=body.attachment_ids,
                employee_id=employee_id,
            )

    return stream_reply(answer)
