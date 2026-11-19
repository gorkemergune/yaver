import datetime as dt
import uuid
from decimal import Decimal
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import Coordinator
from app.agent.team import get_team
from app.config import get_settings
from app.core.change_log import NothingToUndoError, undo_change_set
from app.db.session import get_session
from app.llm.router import get_router

router = APIRouter(tags=["chat"])


@lru_cache
def get_coordinator() -> Coordinator:
    return Coordinator(get_router(), get_team(), get_settings())


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    speaker: str
    change_set_id: uuid.UUID | None
    agents: list[dict[str, str]]
    actions: list[dict[str, Any]]
    cost_usd: Decimal


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    coordinator: Coordinator = Depends(get_coordinator),
) -> ChatResponse:
    reply = await coordinator.handle(session, body.message, conversation_id=body.conversation_id)
    return ChatResponse(
        conversation_id=reply.conversation_id,
        reply=reply.reply,
        speaker=reply.speaker,
        change_set_id=reply.change_set_id,
        agents=reply.agents,
        actions=reply.actions,
        cost_usd=reply.cost_usd,
    )


class UndoResponse(BaseModel):
    change_set_id: uuid.UUID
    reverted: int


@router.post("/changes/{change_set_id}/undo")
async def undo(
    change_set_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> UndoResponse:
    """The "Geri al" button: reverts one message's changes without going through the LLM."""
    try:
        entries = await undo_change_set(session, change_set_id, dt.datetime.now(dt.UTC))
    except NothingToUndoError as exc:
        raise HTTPException(status_code=404, detail="nothing to undo") from exc
    await session.commit()
    return UndoResponse(change_set_id=change_set_id, reverted=len(entries))
