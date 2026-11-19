import asyncio
import datetime as dt
import json
import logging
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator, unsent_attachments
from app.agent.team import get_team
from app.config import get_settings
from app.core.change_log import NothingToUndoError, undo_change_set
from app.db.models.enums import ConversationMode
from app.db.session import get_session, get_sessionmaker
from app.llm.router import LLMUnavailableError, get_router

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@lru_cache
def get_coordinator() -> Coordinator:
    return Coordinator(get_router(), get_team(), get_settings())


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """The streaming endpoint opens its own session: it outlives the request handler."""
    return get_sessionmaker()


class ChatRequest(BaseModel):
    message: str = Field("", max_length=20000)  # pasted schedules can be long
    conversation_id: int | None = None
    # A new conversation in "onboarding" mode goes to the setup assistant.
    mode: ConversationMode = ConversationMode.CHAT
    # Images uploaded first with POST /api/uploads; read by Claude before the team answers.
    attachment_ids: list[int] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _something_to_say(self) -> "ChatRequest":
        if not self.message.strip() and not self.attachment_ids:
            raise ValueError("message or attachment_ids is required")
        return self


async def _check_attachments(session: AsyncSession, body: ChatRequest) -> None:
    try:
        await unsent_attachments(session, body.attachment_ids)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "bad_attachments", "message": str(exc)}) from exc


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    speaker: str
    change_set_id: uuid.UUID | None
    agents: list[dict[str, str]]
    actions: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    cost_usd: Decimal


def _response(reply: ChatReply) -> ChatResponse:
    return ChatResponse(
        conversation_id=reply.conversation_id,
        reply=reply.reply,
        speaker=reply.speaker,
        change_set_id=reply.change_set_id,
        agents=reply.agents,
        actions=reply.actions,
        changes=reply.changes,
        cost_usd=reply.cost_usd,
    )


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    coordinator: Coordinator = Depends(get_coordinator),
) -> ChatResponse:
    await _check_attachments(session, body)
    reply = await coordinator.handle(
        session,
        body.message,
        conversation_id=body.conversation_id,
        mode=body.mode,
        attachment_ids=body.attachment_ids,
    )
    return _response(reply)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    coordinator: Coordinator = Depends(get_coordinator),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> StreamingResponse:
    """Server-sent events: progress (turn/text/reset/tool/delegate/agent_reply), then
    `done` with the full reply, or `error`. Closing the connection cancels the message
    (nothing is saved)."""
    async with session_factory() as check:
        await _check_attachments(check, body)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            async with session_factory() as session:
                reply = await coordinator.handle(
                    session,
                    body.message,
                    conversation_id=body.conversation_id,
                    emit=emit,
                    mode=body.mode,
                    attachment_ids=body.attachment_ids,
                )
            await emit({"type": "done", **_response(reply).model_dump(mode="json")})
        except LLMUnavailableError:
            logger.warning("No LLM tier could answer", exc_info=True)
            await emit({"type": "error", "code": "llm_unavailable"})
        except Exception:
            logger.exception("Chat message failed")
            await emit({"type": "error", "code": "internal"})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())

    async def events() -> AsyncIterator[str]:
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            if not task.done():  # client went away mid-answer
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
