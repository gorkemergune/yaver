"""Entry point for a user message: direct addressing ("Friday, ...") or the coordinator,
which splits the message and delegates to yavers. Everything changed while answering one
message shares one change_set_id, so a single undo reverts all of it."""

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import ToolContext
from app.agent.loop import AgentRun, Emit, LLMClient, run_agent
from app.agent.team import Member, Team
from app.config import Settings
from app.core.change_log import ChangeRecorder, describe_changes
from app.core.time_resolver import WEEKDAY_NAMES_TR, build_calendar_context, format_calendar_context
from app.db.models import Conversation, Memory, Message
from app.db.models.enums import MessageRole
from app.llm.types import ChatMessage

HISTORY_MESSAGES = 10
_ADDRESS = re.compile(r"^\s*([^\s,:;!?]+)\s*[,:;!]\s*(.+)$", re.DOTALL)


@dataclass(slots=True)
class LLMCall:
    agent_id: str
    tier: str
    provider: str
    model: str
    cost_usd: Decimal
    tool_calls: int


@dataclass(slots=True)
class ChatReply:
    conversation_id: int
    reply: str
    speaker: str  # agent id that answered the user
    change_set_id: uuid.UUID | None
    agents: list[dict[str, str]] = field(default_factory=list)  # [{agent_id, name, reply}]
    actions: list[dict[str, Any]] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)  # for the change card
    trace: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)

    @property
    def cost_usd(self) -> Decimal:
        return sum((call.cost_usd for call in self.llm_calls), Decimal(0))


def system_suffix(ctx: ToolContext, memories: list[str]) -> str:
    """Per-day context, kept out of the cached system prompt."""
    local = ctx.now.astimezone(ctx.tz)
    lines = [
        f"Şu an: {local:%Y-%m-%d %H:%M} {WEEKDAY_NAMES_TR[local.weekday()]} ({ctx.tz.key})",
        "Takvim (bugün + 14 gün). Sadece düz 'bugün' / 'yarın' buradan okunur; diğer her ifade "
        "için resolve_date kullan:",
        format_calendar_context(build_calendar_context(local.date())),
    ]
    if memories:
        lines += ["Kullanıcı hakkında bilinenler:", *(f"- {m}" for m in memories)]
    return "\n".join(lines)


class Coordinator:
    def __init__(self, llm: LLMClient, team: Team, settings: Settings) -> None:
        self.llm = llm
        self.team = team
        self.settings = settings
        self.max_steps = 6

    def addressed_member(self, text: str) -> tuple[Member, str] | None:
        """'Friday, yarın ne var?' -> (Friday, 'yarın ne var?')"""
        match = _ADDRESS.match(text)
        if not match:
            return None
        member = self.team.by_name(match.group(1))
        if member is None or member is self.team.coordinator:
            return None
        return member, match.group(2).strip()

    async def handle(
        self,
        session: AsyncSession,
        text: str,
        *,
        conversation_id: int | None = None,
        now: dt.datetime | None = None,
        emit: Emit | None = None,
    ) -> ChatReply:
        """`emit` receives progress events (see app.agent.loop) for streaming clients."""
        try:
            reply = await self._handle(session, text, conversation_id, now, emit)
        except BaseException:
            await session.rollback()
            raise
        await session.commit()
        return reply

    async def _handle(
        self,
        session: AsyncSession,
        text: str,
        conversation_id: int | None,
        now: dt.datetime | None,
        emit: Emit | None,
    ) -> ChatReply:
        conversation = await self._conversation(session, conversation_id, text)
        history = await self._history(session, conversation.id)
        change_set_id = uuid.uuid4()
        ctx = ToolContext(
            session=session,
            now=now or dt.datetime.now(dt.UTC),
            tz=self.settings.tz,
            change_set_id=change_set_id,
            recorder=ChangeRecorder(session, change_set_id),
            clock=self.settings.clock,
        )
        memories = list((await session.scalars(select(Memory.content).where(Memory.active))).all())
        suffix = system_suffix(ctx, memories)
        runs: list[AgentRun] = []

        addressed = self.addressed_member(text)
        if addressed is not None:
            member, rest = addressed
            final = await run_agent(
                self.llm,
                member,
                [*history, ChatMessage("user", rest)],
                ctx,
                system_suffix=suffix,
                max_steps=self.max_steps,
                emit=emit,
                stream_text=True,
            )
        else:
            delegated: dict[str, dict[str, Any]] = {}

            async def delegate(arguments: dict[str, Any]) -> dict[str, Any]:
                agent = self.team.get(str(arguments.get("agent_id", "")))
                instruction = str(arguments.get("instruction", "")).strip()
                if agent is None or not instruction:
                    return {"error": "unknown agent_id or empty instruction"}
                if agent.id in delegated:  # one delegation per yaver per message
                    return {"already_done": True, **delegated[agent.id]}
                if emit is not None:
                    await emit(
                        {
                            "type": "delegate",
                            "agent_id": agent.id,
                            "name": agent.name,
                            "instruction": instruction,
                        }
                    )
                sub = await run_agent(
                    self.llm,
                    agent,
                    [ChatMessage("user", instruction)],
                    ctx,
                    system_suffix=suffix,
                    max_steps=self.max_steps,
                    emit=emit,
                )
                runs.append(sub)
                delegated[agent.id] = {"agent": agent.name, "reply": sub.reply}
                if emit is not None:
                    await emit(
                        {
                            "type": "agent_reply",
                            "agent_id": agent.id,
                            "name": agent.name,
                            "reply": sub.reply,
                        }
                    )
                return {**delegated[agent.id], "tools_used": sub.tool_calls}

            final = await run_agent(
                self.llm,
                self.team.coordinator,
                [*history, ChatMessage("user", text)],
                ctx,
                system_suffix=suffix,
                max_steps=self.max_steps,
                delegate=delegate,
                delegate_spec=self.team.delegate_spec(),
                emit=emit,
                stream_text=True,
            )

        changed = bool(ctx.recorder.entries)
        stored_set = change_set_id if changed else None
        session.add(Message(conversation_id=conversation.id, role=MessageRole.USER, content=text))
        for sub in runs:
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role=MessageRole.ASSISTANT,
                    agent_id=sub.agent_id,
                    content=sub.reply,
                    change_set_id=stored_set,
                )
            )
        session.add(
            Message(
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                agent_id=final.agent_id,
                content=final.reply,
                change_set_id=stored_set,
            )
        )
        conversation.updated_at = ctx.now
        await session.flush()
        changes = await describe_changes(session, ctx.recorder.entries)

        return ChatReply(
            conversation_id=conversation.id,
            reply=final.reply,
            speaker=final.agent_id,
            change_set_id=stored_set,
            agents=[{"agent_id": r.agent_id, "name": r.name, "reply": r.reply} for r in runs],
            actions=ctx.actions,
            changes=changes,
            trace=ctx.trace,
            llm_calls=[
                LLMCall(
                    run.agent_id,
                    resp.tier,
                    resp.provider,
                    resp.model,
                    resp.cost_usd,
                    len(resp.tool_calls),
                )
                for run in [*runs, final]
                for resp in run.responses
            ],
        )

    async def _conversation(
        self, session: AsyncSession, conversation_id: int | None, text: str
    ) -> Conversation:
        if conversation_id is not None:
            existing = await session.get(Conversation, conversation_id)
            if existing is not None:
                return existing
        conversation = Conversation(title=text[:80])
        session.add(conversation)
        await session.flush()
        return conversation

    async def _history(self, session: AsyncSession, conversation_id: int) -> list[ChatMessage]:
        """Recent user turns and final answers as plain text (tool traffic is not replayed)."""
        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc())
                .limit(HISTORY_MESSAGES * 2)
            )
        ).all()
        history: list[ChatMessage] = []
        for row in reversed(rows):
            if row.role is MessageRole.USER:
                history.append(ChatMessage("user", row.content))
            elif row.role is MessageRole.ASSISTANT:
                if history and history[-1].role == "assistant":
                    history[-1] = ChatMessage("assistant", row.content)  # keep the final answer
                else:
                    history.append(ChatMessage("assistant", row.content))
        history = history[-HISTORY_MESSAGES:]
        while history and history[0].role != "user":  # providers want a user turn first
            history.pop(0)
        return history
