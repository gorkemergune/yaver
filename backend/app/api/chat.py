import asyncio
import datetime as dt
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator, unsent_attachments
from app.agent.loop import Emit
from app.agent.team import get_team
from app.config import get_settings
from app.core.change_log import NothingToUndoError, undo_change_set
from app.db.models import Conversation
from app.db.models.enums import ConversationMode
from app.db.session import get_session, get_sessionmaker
from app.llm.router import LLMUnavailableError, get_router
from app.office.state import get_office

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@lru_cache
def get_coordinator() -> Coordinator:
    return Coordinator(
        get_router(), get_team(), get_settings(), get_office(), after_message=review_plan_after
    )


_background: set[asyncio.Task[Any]] = set()


def adds_an_exam(reply: ChatReply) -> bool:
    return any(
        c["entity"] == "events" and c["op"] == "create" and c["data"].get("kind") == "exam"
        for c in reply.changes
    )


def review_plan_after(reply: ChatReply) -> None:
    """An exam added in the chat: its review plan is drafted in the background and comes as
    a message of its own; the answer does not wait for it."""
    if not adds_an_exam(reply):
        return
    task = asyncio.create_task(_review_plan())
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _review_plan() -> None:
    from app.jobs.runner import run_job

    try:
        await asyncio.sleep(1)  # after the answer has reached the client
        await run_job("exam_prep", force=True, record=False, office=get_office())
    except Exception:
        logger.exception("Review plan after a new exam failed")


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
    if body.conversation_id is not None:  # QA O5: never an employee's direct chat
        conversation = await session.get(Conversation, body.conversation_id)
        if conversation is not None and conversation.employee_id is not None:
            raise HTTPException(422, detail={"code": "not_the_main_chat"})


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    speaker: str
    change_set_id: uuid.UUID | None
    agents: list[dict[str, str]]
    actions: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    cost_usd: Decimal


def response_of(reply: ChatReply) -> ChatResponse:
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
    return response_of(reply)


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def stream_reply(
    answer: Callable[[Emit], Awaitable[ChatReply]],
    *,
    timeout: float | None = None,
    ping: float | None = None,
) -> StreamingResponse:
    """Runs `answer` with an emitter and streams its events, then `done` or `error`.
    Closing the connection cancels it (the coordinator rolls back: nothing is saved).
    While nothing happens a `ping` event goes out every `ping` seconds (the client's idle
    timer and proxies see a live stream); after `timeout` seconds the answer is cancelled
    and the stream ends with `error` code `timeout`."""
    settings = get_settings()
    timeout = settings.chat_timeout_seconds if timeout is None else timeout
    ping = settings.chat_ping_seconds if ping is None else ping
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            async with asyncio.timeout(timeout):
                reply = await answer(emit)
            await emit({"type": "done", **response_of(reply).model_dump(mode="json")})
        except TimeoutError:
            logger.warning("Chat message took longer than %s s: cancelled", timeout)
            await emit({"type": "error", "code": "timeout"})
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
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), ping)
                except TimeoutError:
                    yield sse({"type": "ping"})
                    continue
                if event is None:
                    break
                yield sse(event)
        finally:
            if not task.done():  # client went away mid-answer
                task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


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

    async def answer(emit: Emit) -> ChatReply:
        async with session_factory() as session:
            return await coordinator.handle(
                session,
                body.message,
                conversation_id=body.conversation_id,
                emit=emit,
                mode=body.mode,
                attachment_ids=body.attachment_ids,
            )

    return stream_reply(answer)


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
