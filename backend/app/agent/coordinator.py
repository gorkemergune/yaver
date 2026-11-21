"""Entry point for a user message: direct addressing ("Friday, ...") or the coordinator,
which splits the message and delegates to yavers. Everything changed while answering one
message shares one change_set_id, so a single undo reverts all of it."""

import datetime as dt
import logging
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ads.intake import CSV_MIME, AdFileInput, read_ad_files
from app.ads.report import analyze
from app.agent import intents
from app.agent.context import ToolContext
from app.agent.documents import DocumentInput, read_documents
from app.agent.loop import AgentRun, Emit, LLMClient, OnTool, run_agent
from app.agent.pending import (
    Binding,
    PendingAction,
    bind,
    done_note,
    observe,
    proposal_pending,
    reply_note,
    word_set,
)
from app.agent.reply import dedupe_questions
from app.agent.team import Member, Team
from app.agent.tools import REGISTRY, dump_result, run_tool
from app.agent.vision import ImageInput, read_images
from app.config import Settings
from app.core.change_log import ChangeRecorder, describe_changes
from app.core.time_resolver import (
    WEEKDAY_NAMES_TR,
    build_calendar_context,
    format_calendar_context,
    normalize,
)
from app.db.models import AdReport, Attachment, Conversation, Followup, Memory, Message
from app.db.models.enums import ConversationMode, FollowupStatus, MessageRole, TaskOrigin
from app.llm.types import ChatMessage, ImagePart, LLMRequest, ToolCall
from app.office.activity import MessageActivity
from app.office.state import Office
from app.services.images import resolve_stored

HISTORY_MESSAGES = 10
_ADDRESS = re.compile(r"^\s*([^\s,:;!?]+)\s*[,:;!]\s*(.+)$", re.DOTALL)


logger = logging.getLogger(__name__)
PDF_MIME = "application/pdf"
AD_REPORT_TOOL = "get_ad_report"  # whoever has it analyses ad report files
ANALYZE_ADS = "analyze_ads"  # office label while the analysis runs (no model tool)
AD_REPORT_TASK = "Reklam raporunu analiz et"
# After a long block read from an image / PDF the model drifts to English without this.
CONTEXT_REMINDER = "(Bu blokları kod okudu. Cevabın Türkçe olsun.)"
# after a part, the whole message as context (a yaver never acts on it: agent.md rule 6)
CONTEXT_PREFIX = "\nKullanıcının mesajı: "


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
    # (intent, owner) per part, as the code routed it (empty: not classified)
    intents: list[tuple[str, str | None]] = field(default_factory=list)

    @property
    def cost_usd(self) -> Decimal:
        return sum((call.cost_usd for call in self.llm_calls), Decimal(0))


def system_suffix(ctx: ToolContext, memories: list[str], followups: list[str] | None = None) -> str:
    """Per-day context, kept out of the cached system prompt."""
    local = ctx.now.astimezone(ctx.tz)
    lines = [
        f"Şu an: {local:%Y-%m-%d %H:%M} {WEEKDAY_NAMES_TR[local.weekday()]} ({ctx.tz.key})",
        "Takvim (yalnız düz bugün/yarın buradan; diğer ifadeler resolve_date):",
        format_calendar_context(build_calendar_context(local.date())),
    ]
    if memories:
        lines += ["Kullanıcı hakkında bilinenler:", *(f"- {m}" for m in memories)]
    if followups:
        lines += [
            "Bekleyen takipler (haberi gelince update_followup, başlıktan bir kelimeyle):",
            *(f"- {f}" for f in followups),
        ]
    # The last line the model reads before answering: the rules above are English and Haiku
    # then sometimes answers in English.
    lines.append("Cevabını Türkçe yaz.")
    return "\n".join(lines)


# Past-tense change verbs ("kaydettim", "eklendi", "iptal etti"...); negations such as
# "eklemedim" do not match.
_CLAIM = re.compile(
    r"\b(kaydett|kaydedil|ekledi|eklendi|ekledim|iptal ett|iptal edil|tasidi|tasindi|"
    r"guncelledi|guncellendi|sildi|silindi|isaretledi|isaretlendi|tamamlandi olarak)"
)
NO_TOOL_RAN = (
    "Önceki denemende bu mesaj için hiçbir araç çalıştırmadın. Geçmişteki cevaplar bu mesaj "
    "için bir şey yapmaz: kullanıcının son mesajındaki isteği şimdi araçla yerine getir "
    "(ilgili yavere delegate et ya da aracı çağır; zaten kayıtlıysa araç bunu söyler) ve "
    "araç sonucuna göre cevap ver."
)


# Requests to change something ("gitmedim", "iptal", "ekle", "sil", "taşı"...).
_REQUEST = re.compile(
    r"\b(gitmedim|gidemedim|gitmeyecegim|gidemeyecegim|katilmadim|katilamadim|iptal|ekle|"
    r"kaydet|sil|tasi|ertele|degistir|isaretle|tamamladim|bitirdim)"
)


_ENGLISH = word_set(
    "the you your and was has have added cancelled canceled would is are to for of it this "
    "that with will can recorded class today tomorrow meeting there no not"
)
_TURKISH = word_set(
    "ve bir bu icin mi mu da de ile yarin bugun ders iptal ekledi kaydetti var yok sen"
)
TURKISH_REWRITE = (
    "Aşağıdaki asistan cevabını Türkçeye çevir. İçerik, isimler, ders kodları, tarihler, "
    'saatler ve sayılar aynen kalsın; kullanıcıya "sen" diye hitap et. Yalnızca çeviriyi yaz.'
)


def looks_english(text: str) -> bool:
    """The answer drifted to English (live runs: after long context blocks, Haiku)."""
    english = sum(1 for w in re.findall(r"[a-z]+", text.lower()) if w in _ENGLISH)
    turkish = sum(1 for w in re.findall(r"[a-z]+", normalize(text)) if w in _TURKISH)
    turkish += sum(1 for ch in text if ch in "ğüşıöçĞÜŞİÖÇ")
    return english >= 3 and english > turkish


OWN_PART_HINTS = {
    "memory": "a lasting fact: call remember yourself; only with weekly hours ('her cuma "
    "9-17') it is a weekly block: delegate it (agenda area)",
    "question": "a question: answer it yourself with get_day_plan / get_week_plan",
    "undo": "call undo yourself",
}


def own_parts_note(classified: "list[intents.Routed] | None") -> str:
    """The parts the code left to the coordinator, with what to do (live: "bu dönem cuma
    günleri medipoldeyim" is a memory, the coordinator delegated it as a weekly block)."""
    lines = [
        f'- "{p.text}": {OWN_PART_HINTS[p.intent]}'
        for p in classified or []
        if p.owner is None and p.intent in OWN_PART_HINTS
    ]
    return "Bu mesajda senin işin (kod ayırdı):\n" + "\n".join(lines) if lines else ""


def worked(ctx: ToolContext) -> bool:
    """Any tool call besides resolve_date (live run: the coordinator resolved "geçen salı",
    then asked "onay verir misin?" without delegating)."""
    return any(entry["tool"] != "resolve_date" for entry in ctx.trace)


def claims_a_change(reply: str) -> bool:
    return _CLAIM.search(normalize(reply)) is not None


def requests_a_change(text: str) -> bool:
    return _REQUEST.search(normalize(text)) is not None


def with_image_context(text: str, context: str | None) -> str:
    """The user's words plus what the code read from their images (see agent.vision)."""
    if not context:
        return text
    return f"{text.strip() or '(Yalnızca görsel gönderdim.)'}\n\n{context}\n\n{CONTEXT_REMINDER}"


async def unsent_attachments(session: AsyncSession, ids: Sequence[int]) -> list[Attachment]:
    """The uploads in the given order; ValueError if one is unknown or already sent."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    rows = (await session.scalars(select(Attachment).where(Attachment.id.in_(wanted)))).all()
    by_id = {row.id: row for row in rows}
    bad = [i for i in wanted if i not in by_id or by_id[i].message_id is not None]
    if bad:
        raise ValueError(f"unknown or already sent attachment(s): {bad}")
    return [by_id[i] for i in wanted]


class Coordinator:
    def __init__(
        self,
        llm: LLMClient,
        team: Team,
        settings: Settings,
        office: Office | None = None,
        after_message: Callable[[ChatReply], None] | None = None,
    ) -> None:
        self.llm = llm
        self.team = team
        self.settings = settings
        self.office = office  # None: nothing is shown in the office (tests, scripts)
        # called once the message is saved: long follow-up work (an exam's review plan)
        # runs in the background instead of keeping the answer waiting
        self.after_message = after_message
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
        mode: ConversationMode = ConversationMode.CHAT,
        attachment_ids: Sequence[int] = (),
        employee_id: str | None = None,
    ) -> ChatReply:
        """`emit` receives progress events (see app.agent.loop) for streaming clients.
        `attachment_ids`: uploaded images (POST /api/uploads) sent with this message.
        `employee_id`: a direct chat with that employee (its prompt and tools); the
        coordinator's id is the main chat."""
        now = now or dt.datetime.now(dt.UTC)
        office = self.office
        if office is not None and not await office.ensure_ready():
            office = None
        activity = MessageActivity(office, session, now)
        try:
            reply = await self._handle(
                session,
                text,
                conversation_id,
                now,
                emit,
                mode,
                attachment_ids,
                activity,
                employee_id,
            )
        except BaseException:
            await session.rollback()
            await activity.close()
            raise
        await session.commit()
        await activity.close()
        if office is not None:
            office.publish_notes(activity.notes)
        if self.after_message is not None:
            try:
                self.after_message(reply)
            except Exception:  # the answer is saved; follow-up work never breaks it
                logger.exception("after_message failed")
        return reply

    async def _handle(
        self,
        session: AsyncSession,
        text: str,
        conversation_id: int | None,
        now: dt.datetime | None,
        emit: Emit | None,
        mode: ConversationMode = ConversationMode.CHAT,
        attachment_ids: Sequence[int] = (),
        activity: MessageActivity | None = None,
        employee_id: str | None = None,
    ) -> ChatReply:
        forced = self._member(employee_id) if employee_id else None
        if employee_id and forced is None:
            raise ValueError(f"unknown employee {employee_id!r}")
        if forced is self.team.coordinator:
            forced = None  # the coordinator's own chat is the main chat
        conversation = await self._conversation(
            session,
            conversation_id,
            text or "Görsel",
            mode,
            employee_id=forced.id if forced is not None else None,
        )
        history = await self._history(session, conversation.id)
        activity = activity or MessageActivity(None, session, now or dt.datetime.now(dt.UTC))
        activity.conversation_id = conversation.id
        on_tool: OnTool = activity.tool
        change_set_id = uuid.uuid4()
        ctx = ToolContext(
            session=session,
            now=now or dt.datetime.now(dt.UTC),
            tz=self.settings.tz,
            change_set_id=change_set_id,
            recorder=ChangeRecorder(session, change_set_id),
            clock=self.settings.clock,
            conversation_id=conversation.id,
            llm=self.llm,
        )
        activity.notes = ctx.notes
        memories = list((await session.scalars(select(Memory.content).where(Memory.active))).all())
        open_followups = list(
            (
                await session.scalars(
                    select(Followup.title)
                    .where(Followup.status == FollowupStatus.WAITING)
                    .order_by(Followup.id)
                )
            ).all()
        )
        suffix = system_suffix(ctx, memories, open_followups)
        runs: list[AgentRun] = []
        attachments, image_context = await self._read_images(session, ctx, attachment_ids, emit)
        model_text = with_image_context(text, image_context)

        # A direct chat goes to its employee; in the main chat a name addresses one.
        addressed = (forced, text) if forced is not None else self.addressed_member(text)
        # An ad report file (CSV / screenshot) goes to the ad analyst, unless someone else
        # was named
        analyst = self._ad_analyst()
        if ctx.ad_reports and addressed is None and analyst is not None:
            addressed = (analyst, text)
        final_member: Member = self.team.coordinator
        final_messages = [*history, ChatMessage("user", model_text)]
        # Instruction each yaver got this turn (the open question's context).
        instructions: dict[str, str] = {}

        classified: list[intents.Routed] | None = None
        waiting = PendingAction.load(conversation.pending_action)
        conversation.pending_action = None  # answered now, or replaced at the end
        binding = None
        if (
            waiting is not None
            and not waiting.expired(ctx.now)
            and conversation.mode is ConversationMode.CHAT
            and (addressed is None or forced is not None)
            and not attachments
        ):
            binding = bind(waiting, text)
            if binding.kind == "reply" and requests_a_change(text):
                # "Geçen salı EE211'e gitmedim" after Karen's question: a new request (live
                # run), not an answer; picked options ("evet, kaydet") are not affected
                binding = Binding("other")
            if binding.kind == "reply":
                # A new request right after a question is not its answer (real use: "yarın
                # sabah Medipoldeki kahvaltıya gidicem" went to Scholar, who had asked about
                # a class, and Scholar did nothing). The intent decides, not the length.
                classified = await self._classify(text, waiting.question)
                if classified is not None and not any(
                    # an answer, or something for the one who asked: it keeps the question
                    # (live: "cse 211" to "DSA hangi ders?" came back as course_note)
                    r.intent == "answer" or r.owner == waiting.agent_id
                    for r in classified
                ):
                    binding = Binding("other")
            logger.info(
                "Open question of %s, answer %r -> %s", waiting.agent_id, text, binding.kind
            )
        answering = None
        if waiting is not None and binding is not None and binding.kind in ("option", "reply"):
            answering = self._member(waiting.agent_id)
            if answering is self.team.coordinator and binding.kind == "reply":
                answering = None  # the coordinator sees its own question in the history

        delegated: dict[str, dict[str, Any]] = {}
        # parts of this message the code is about to hand out, by owner (coordinate())
        queued: dict[str, list[str]] = {}

        async def delegate(arguments: dict[str, Any]) -> dict[str, Any]:
            agent = self.team.get(str(arguments.get("agent_id", "")))
            instruction = str(arguments.get("instruction", "")).strip()
            if agent is None or not instruction:
                return {"error": "unknown agent_id or empty instruction"}
            if agent.id in delegated:  # one delegation per yaver per message
                return {"already_done": True, **delegated[agent.id]}
            instructions[agent.id] = instruction
            await activity.delegate(self.team.coordinator.id, agent.id, instruction)
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
                on_tool=on_tool,
            )
            await activity.delegated(agent.id, sub.reply, sub.tool_calls)
            if sub.handoff is not None:
                # not its area: the owner of the area it names gets the same words, once
                delegated[agent.id] = {"agent": agent.name, "handoff": sub.handoff.get("reason")}
                instructions.pop(agent.id, None)
                target = intents.owner_of(str(sub.handoff.get("area", "")), self._team_ids())
                if target is not None and target != agent.id and target not in delegated:
                    if target in queued:
                        # it gets its own part of this message next: both in one go (live:
                        # run first, it then skipped its own part as "already done")
                        queued[target].insert(0, instruction.split(CONTEXT_PREFIX)[0])
                        return {**delegated[agent.id], "note": "handed over with the rest"}
                    return await delegate({"agent_id": target, "instruction": instruction})
                return {
                    **delegated[agent.id],
                    "note": "not this yaver's area: do it yourself or ask the user",
                }
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

        async def coordinate() -> AgentRun:
            """The main chat: the intents decide who gets which part (in code), then the
            coordinator writes the answer from their results (and handles its own parts)."""
            nonlocal classified
            await activity.begin(self.team.coordinator.id, text, source=TaskOrigin.USER)
            if classified is None and not attachments:
                classified = await self._classify(text)
            messages = list(final_messages)
            queued.clear()
            for part in classified or []:
                if part.owner is not None and part.owner not in delegated:
                    queued.setdefault(part.owner, []).append(part.text)
            calls: list[ToolCall] = []
            results: list[ChatMessage] = []
            number = 0
            while queued:
                owner = next(iter(queued))
                parts = queued.pop(owner)
                number += 1
                instruction = "\n".join(dict.fromkeys(parts))
                if len(classified or []) > 1:
                    instruction += f"{CONTEXT_PREFIX}{text}"
                arguments = {"agent_id": owner, "instruction": instruction}
                result = await delegate(arguments)
                call_id = f"route_{number}"
                calls.append(ToolCall(call_id, "delegate", arguments))
                results.append(ChatMessage("tool", dump_result(result), tool_call_id=call_id))
                ctx.trace.append(
                    {
                        "agent_id": self.team.coordinator.id,
                        "tool": "delegate",
                        "arguments": arguments,
                        "error": result.get("error"),
                        "routed": True,
                    }
                )
            if calls:
                # as if the coordinator had delegated itself: now it only writes the answer
                messages += [ChatMessage("assistant", "", tool_calls=calls), *results]
            holder["delegate"] = delegate
            ctx.intents = [(p.intent, p.owner) for p in classified or []]
            return await run_agent(
                self.llm,
                self.team.coordinator,
                messages,
                ctx,
                system_suffix=f"{suffix}\n{own_parts_note(classified)}".rstrip(),
                max_steps=self.max_steps,
                delegate=delegate,
                delegate_spec=self.team.delegate_spec(),
                emit=emit,
                stream_text=True,
                on_tool=on_tool,
            )

        holder: dict[str, Any] = {}
        if waiting is not None and binding is not None and answering is not None:
            final_member = answering
            final_messages = [
                ChatMessage("user", waiting.request),
                ChatMessage("assistant", waiting.question),
                ChatMessage("user", model_text),
            ]
            note = reply_note(waiting)
            done = False
            await activity.begin(answering.id, text, source=TaskOrigin.USER)
            if binding.option is not None:
                tool_name, arguments = waiting.call(binding.option)
                result = await self._run_bound(ctx, answering, tool_name, arguments, emit, on_tool)
                left = observe(answering.id, waiting.request, tool_name, arguments, result)
                done = "error" not in result and left is None
                if done:
                    note = done_note(tool_name, arguments, dump_result(result))
                else:
                    note += f"\nKod şunu denedi: {tool_name}({arguments}) -> {dump_result(result)}"
            final = await run_agent(
                self.llm,
                answering,
                final_messages,
                ctx,
                system_suffix=f"{suffix}\n{note}",
                max_steps=self.max_steps,
                emit=emit,
                stream_text=True,
                use_tools=not done,
                on_tool=on_tool,
            )
        elif conversation.mode is ConversationMode.ONBOARDING and self.team.onboarding is not None:
            final_member = self.team.onboarding
            await activity.begin(final_member.id, text, source=TaskOrigin.USER)
            final = await run_agent(
                self.llm,
                self.team.onboarding,
                final_messages,
                ctx,
                system_suffix=suffix,
                max_steps=self.max_steps,
                emit=emit,
                stream_text=True,
                on_tool=on_tool,
            )
        elif addressed is not None:
            member, rest = addressed
            final_member = member
            await activity.begin(member.id, rest or AD_REPORT_TASK, source=TaskOrigin.USER)
            if ctx.ad_reports and member is analyst:
                # the analysis is code + one deep-tier call, not a tool the model may skip
                await activity.tool(member.id, ANALYZE_ADS)
                analyses = await self._analyze_ads(ctx, member.id)
                image_context = f"{image_context}\n\n{analyses}".strip()
            final_messages = [
                *history,
                ChatMessage("user", with_image_context(rest, image_context)),
            ]
            final = await run_agent(
                self.llm,
                member,
                final_messages,
                ctx,
                system_suffix=suffix,
                max_steps=self.max_steps,
                emit=emit,
                stream_text=True,
                on_tool=on_tool,
            )
        else:
            final = await coordinate()

        if final.handoff is not None and final_member is not self.team.coordinator:
            # the employee the message went straight to says it is not its area: the
            # coordinator routes it, in this same message (same change set)
            logger.info("%s handed %r back: %s", final_member.id, text, final.handoff)
            final_member = self.team.coordinator
            final_messages = [*history, ChatMessage("user", model_text)]
            final = await coordinate()

        if (
            not ctx.actions
            and not ctx.new_proposals  # an image's table shown for confirmation: no tool yet
            and (claims_a_change(final.reply) or (not worked(ctx) and requests_a_change(text)))
        ):
            # Live runs: after a few "gitmedim" messages Haiku answered the next one with
            # "kaydettim" - or with an apology - and no tool call at all. One more turn: do it
            # with a tool now (an already recorded thing is reported by the tool).
            logger.warning("No tool ran for %r; reply was %r", text, final.reply)
            if emit is not None:
                await emit({"type": "reset", "agent_id": final.agent_id})
            # Same user message again (it must stay the last one: a note sent as a message
            # was read as the user's new request); the note goes into the system context.
            # A self-contained request is retried without the history: the earlier
            # "kaydettim" answers are what it copied. "evet" & co keep it (they need it).
            retry_messages = final_messages[-1:] if requests_a_change(text) else final_messages
            final = await run_agent(
                self.llm,
                final_member,
                retry_messages,
                ctx,
                system_suffix=f"{suffix}\n{NO_TOOL_RAN}",
                max_steps=self.max_steps,
                delegate=holder.get("delegate"),
                delegate_spec=self.team.delegate_spec() if holder.get("delegate") else None,
                emit=emit,
                stream_text=True,
                on_tool=on_tool,
            )

        if not final.reply.strip() and ctx.actions:
            final.reply = "Tamam, yaptım."  # never an empty bubble after a change
        if looks_english(final.reply):
            await self._rewrite_in_turkish(final, final_member, emit)
        reply_text = dedupe_questions(final.reply)
        if reply_text != final.reply:
            logger.info("Dropped a repeated question from the final answer: %r", final.reply)
        still_open = self._still_open(
            ctx, runs, final, reply_text, instructions, waiting if answering else None, model_text
        )
        conversation.pending_action = still_open.dump() if still_open else None
        changed = bool(ctx.recorder.entries)
        stored_set = change_set_id if changed else None
        # the office: who left a question (red dot), whose question this message replaced
        activity.asking = still_open.agent_id if still_open else None
        activity.answered = waiting.agent_id if waiting is not None else None
        await activity.finish(final.agent_id, reply_text, final.tool_calls)
        activity.set_change_set(stored_set)
        user_message = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=text,
            context=image_context or None,
        )
        session.add(user_message)
        if attachments:
            await session.flush()
            for attachment in attachments:
                attachment.message_id = user_message.id
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
                content=reply_text,
                change_set_id=stored_set,
            )
        )
        conversation.updated_at = ctx.now
        await session.flush()
        changes = await describe_changes(session, ctx.recorder.entries)

        return ChatReply(
            intents=ctx.intents,
            conversation_id=conversation.id,
            reply=reply_text,
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

    def _ad_analyst(self) -> Member | None:
        """The employee with the ad report tool (Metrics), if the team has one."""
        return next(
            (a for a in self.team.agents if any(t.name == AD_REPORT_TOOL for t in a.tools)),
            None,
        )

    async def _analyze_ads(self, ctx: ToolContext, agent_id: str) -> str:
        blocks = []
        for report_id in ctx.ad_reports:
            report = await ctx.session.get(AdReport, report_id)
            if report is not None:
                blocks.append(f"[Rapor #{report.id}] " + await analyze(ctx, report, agent_id))
        return "\n\n".join(blocks)

    def _team_ids(self) -> set[str]:
        return {a.id for a in self.team.agents}

    async def _classify(
        self, text: str, open_question: str | None = None
    ) -> list[intents.Routed] | None:
        if not text.strip():
            return None
        return await intents.classify(self.llm, text, self._team_ids(), open_question=open_question)

    def _member(self, agent_id: str) -> Member | None:
        if agent_id == self.team.coordinator.id:
            return self.team.coordinator
        return self.team.get(agent_id)

    async def _run_bound(
        self,
        ctx: ToolContext,
        member: Member,
        tool_name: str,
        arguments: dict[str, Any],
        emit: Emit | None,
        on_tool: OnTool | None = None,
    ) -> dict[str, Any]:
        """The tool call the user's short answer picked, run by the code for `member`."""
        if on_tool is not None:
            await on_tool(member.id, tool_name)
        ctx.agent_id = ctx.recorder.agent_id = member.id
        result = await run_tool(tool_name, arguments, ctx)
        step: dict[str, Any] = {
            "agent_id": member.id,
            "tool": tool_name,
            "arguments": arguments,
            "error": result.get("error"),
            "bound": True,
        }
        ctx.trace.append(step)
        if emit is not None:
            tool = REGISTRY.get(tool_name)
            await emit({"type": "tool", **step, "mutates": bool(tool and tool.mutates)})
        return result

    def _still_open(
        self,
        ctx: ToolContext,
        runs: list[AgentRun],
        final: AgentRun,
        reply_text: str,
        instructions: dict[str, str],
        answered: PendingAction | None,
        user_text: str,
    ) -> PendingAction | None:
        """The question this answer leaves open, if exactly one yaver asked one."""
        coordinator = self.team.coordinator.id
        if len(ctx.new_proposals) == 1:  # a table shown for "evet"
            pending = proposal_pending(coordinator, user_text, next(iter(ctx.new_proposals)))
        elif "?" not in reply_text:
            return None
        else:
            asking = {run.agent_id for run in runs if "?" in run.reply}
            if final.agent_id != coordinator:
                asking.add(final.agent_id)
            ask = ctx.asks[-1] if ctx.asks else None
            if ask is not None and asking <= {ask.agent_id}:
                pending = ask
            elif ask is None and len(asking) == 1:
                agent_id = asking.pop()
                request = instructions.get(agent_id) or (
                    answered.request if answered is not None else user_text
                )
                pending = PendingAction(agent_id, request)
            else:
                return None  # several yavers asked: the coordinator sorts out the answer
        if answered is not None and pending.agent_id == answered.agent_id:
            pending.request = answered.request  # still the same job
        # the yaver's own words: it reads them back as its last message
        own = [run.reply for run in runs if run.agent_id == pending.agent_id]
        pending.question = own[-1] if own else reply_text
        pending.created_at = ctx.now.isoformat()
        return pending

    async def _rewrite_in_turkish(self, final: AgentRun, member: Member, emit: Emit | None) -> None:
        """One rewrite of an English answer; the streamed English text is replaced."""
        logger.warning("Answer in English, rewriting: %r", final.reply)
        response = await self.llm.complete(
            LLMRequest(
                messages=[ChatMessage("user", final.reply)],
                system=TURKISH_REWRITE,
                max_tokens=1024,
                cache=False,
            ),
            purpose="language_fix",
            tier=member.tier,
            agent_id=member.id,
        )
        final.responses.append(response)
        fixed = response.text.strip()
        if not fixed or looks_english(fixed):
            logger.warning("Rewrite still not Turkish: %r", fixed)
            return
        final.reply = fixed
        if emit is not None:
            await emit({"type": "reset", "agent_id": final.agent_id})
            await emit({"type": "text", "agent_id": final.agent_id, "delta": fixed})

    async def _conversation(
        self,
        session: AsyncSession,
        conversation_id: int | None,
        text: str,
        mode: ConversationMode = ConversationMode.CHAT,
        *,
        employee_id: str | None = None,
    ) -> Conversation:
        if conversation_id is not None:
            existing = await session.get(Conversation, conversation_id)
            if existing is not None:
                return existing
        conversation = Conversation(title=text[:80], mode=mode, employee_id=employee_id)
        session.add(conversation)
        await session.flush()
        return conversation

    async def _read_images(
        self,
        session: AsyncSession,
        ctx: ToolContext,
        attachment_ids: Sequence[int],
        emit: Emit | None,
    ) -> tuple[list[Attachment], str]:
        attachments = await unsent_attachments(session, attachment_ids)
        if not attachments:
            return [], ""
        if emit is not None:
            await emit(
                {
                    "type": "status",
                    "agent_id": self.team.coordinator.id,
                    "code": "reading_images",
                    "count": len(attachments),
                }
            )

        def data(attachment: Attachment) -> bytes:
            return resolve_stored(self.settings.upload_dir, attachment.path).read_bytes()

        images = [a for a in attachments if a.mime not in (PDF_MIME, CSV_MIME)]
        pdfs = [a for a in attachments if a.mime == PDF_MIME]
        csvs = [a for a in attachments if a.mime == CSV_MIME]
        blocks = []
        if csvs:
            files = [AdFileInput(a.id, a.filename or "reklam.csv", data(a), a.sha256) for a in csvs]
            blocks.append(await read_ad_files(ctx, files))
        if images:
            inputs = [ImageInput(a.id, ImagePart(a.mime, data(a))) for a in images]
            blocks.append(await read_images(ctx, inputs))
        if pdfs:
            documents = [DocumentInput(a.id, a.filename or "belge.pdf", data(a)) for a in pdfs]
            blocks.append(await read_documents(ctx, documents))
        return attachments, "\n\n".join(blocks)

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
        previous_kind: str | None = None
        for row in reversed(rows):
            if row.role is MessageRole.USER:
                history.append(ChatMessage("user", with_image_context(row.content, row.context)))
                previous_kind = None
            elif row.role is MessageRole.ASSISTANT:
                content = f"{row.content}\n\n{row.context}" if row.context else row.content
                previous = history[-1] if history and history[-1].role == "assistant" else None
                if previous is None:
                    history.append(ChatMessage("assistant", content))
                elif row.kind or previous_kind:
                    # a scheduler message (briefing, weekly plan) is kept next to the answer
                    # before it: a Monday briefing must not hide Sunday's plan draft
                    history[-1] = ChatMessage("assistant", f"{previous.content}\n\n{content}")
                else:
                    history[-1] = ChatMessage("assistant", content)  # keep the final answer
                previous_kind = row.kind
        history = history[-HISTORY_MESSAGES:]
        while history and history[0].role != "user":  # providers want a user turn first
            history.pop(0)
        return history
