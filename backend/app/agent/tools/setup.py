"""First-run setup tools: term, holidays, and a pasted weekly schedule that is parsed into a
proposal, shown as a table and written only after the user confirms (one change set)."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, json_schema, tool
from app.agent.tools.schedule import AddBlockArgs, Weekday, create_weekly_blocks
from app.core.time_resolver import WEEKDAY_NAMES_TR
from app.db.models import Conversation, Holiday, ScheduleProposal, Term
from app.db.models.enums import ConversationMode, ProposalStatus
from app.llm.types import ChatMessage, LLMRequest, ToolSpec

# Longer pastes are parsed by the smart tier (routing.purposes.schedule_parse).
LONG_SCHEDULE_CHARS = 300
LONG_SCHEDULE_LINES = 4
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# --- term and holidays -----------------------------------------------------------------


class TermArgs(BaseModel):
    name: str = Field(description="e.g. '2026-2027 Güz'")
    start_date: dt.date
    end_date: dt.date

    @model_validator(mode="after")
    def _order(self) -> "TermArgs":
        if self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


@tool("add_term", "Store the semester's first and last day.", TermArgs, mutates=True)
async def add_term(args: TermArgs, ctx: ToolContext) -> ToolResult:
    term = Term(name=args.name, start_date=args.start_date, end_date=args.end_date)
    ctx.session.add(term)
    await ctx.recorder.created(term)
    return {
        "term": {
            "term_id": term.id,
            "name": term.name,
            "start": term.start_date.isoformat(),
            "end": term.end_date.isoformat(),
        }
    }


class HolidayArgs(BaseModel):
    name: str = Field(description="e.g. 'Ara tatil', '29 Ekim'")
    start_date: dt.date
    end_date: dt.date | None = Field(None, description="last day; omit for one day")


@tool("add_holiday", "Store a holiday (no classes on these days).", HolidayArgs, mutates=True)
async def add_holiday(args: HolidayArgs, ctx: ToolContext) -> ToolResult:
    end = args.end_date or args.start_date
    if end < args.start_date:
        raise ToolError("end_date is before start_date")
    terms = (await ctx.session.scalars(select(Term))).all()
    term = next((t for t in terms if t.contains(args.start_date)), None)
    holiday = Holiday(
        name=args.name, start_date=args.start_date, end_date=end, term_id=term.id if term else None
    )
    ctx.session.add(holiday)
    await ctx.recorder.created(holiday)
    return {
        "holiday": {
            "name": holiday.name,
            "start": args.start_date.isoformat(),
            "end": end.isoformat(),
        }
    }


# --- schedule parsing ------------------------------------------------------------------


class ParsedEntry(BaseModel):
    kind: Literal["class", "lab", "sport", "work", "other"]
    title: str
    course: str | None = None
    weekdays: list[Weekday] = Field(min_length=1)
    start_time: dt.time
    end_time: dt.time
    location: str | None = None


class ParsedSchedule(BaseModel):
    entries: list[ParsedEntry]
    unclear: list[str] = Field(default_factory=list)


_PARSER_TOOL = ToolSpec(
    "schedule_entries",
    "Return every weekly entry of the schedule.",
    json_schema(ParsedSchedule),
)
_PARSER_PROMPT = (
    "You turn a Turkish university student's weekly schedule (free text or a pasted table) "
    "into structured entries. Call schedule_entries exactly once.\n"
    "- One entry per course session type; list every weekday it happens on.\n"
    "- kind: class for lectures, lab for labs / PS / uygulama, sport, work, other.\n"
    "- title: as the student would call it ('Linear Algebra', 'EE211 Lab'); course: the "
    "course code if there is one (EE211), else the course name.\n"
    "- Times as HH:MM, 24h. Turkish days: Pazartesi..Pazar; 'Pzt, Sal, Çar, Per, Cum, Cmt, Paz'.\n"
    "- Never guess: anything you cannot read with certainty (missing time, unclear day) goes "
    "into `unclear` as the original line, not into entries."
)


def _is_long(text: str) -> bool:
    return len(text) > LONG_SCHEDULE_CHARS or text.count("\n") + 1 > LONG_SCHEDULE_LINES


def schedule_table(entries: list[ParsedEntry]) -> str:
    """Markdown table for the confirmation step, sorted by weekday and time."""
    rows = sorted(
        ((day, entry) for entry in entries for day in entry.weekdays),
        key=lambda pair: (_WEEKDAYS.index(pair[0]), pair[1].start_time),
    )
    lines = ["| Gün | Saat | Ders / blok | Tür | Yer |", "|---|---|---|---|---|"]
    kinds = {"class": "Ders", "lab": "Lab", "sport": "Spor", "work": "İş", "other": "Diğer"}
    for day, entry in rows:
        when = f"{entry.start_time:%H:%M}-{entry.end_time:%H:%M}"
        title = entry.title + (
            f" ({entry.course})" if entry.course and entry.course not in entry.title else ""
        )
        lines.append(
            f"| {WEEKDAY_NAMES_TR[_WEEKDAYS.index(day)]} | {when} | {title} | "
            f"{kinds[entry.kind]} | {entry.location or ''} |"
        )
    return "\n".join(lines)


class ProposeArgs(BaseModel):
    text: str = Field(description="the schedule exactly as the user wrote or pasted it")


@tool(
    "propose_schedule",
    "Parse a written or pasted weekly schedule into a proposal. Show the returned table to "
    "the user and ask for confirmation; nothing is saved until apply_schedule.",
    ProposeArgs,
)
async def propose_schedule(args: ProposeArgs, ctx: ToolContext) -> ToolResult:
    if ctx.llm is None:
        raise ToolError("schedule parsing is not available here")
    text = args.text.strip()
    if not text:
        raise ToolError("empty schedule")
    purpose = "schedule_parse" if _is_long(text) else "schedule_parse_short"
    response = await ctx.llm.complete(
        LLMRequest(
            system=_PARSER_PROMPT,
            messages=[ChatMessage("user", text)],
            tools=[_PARSER_TOOL],
            tool_choice="required",
            max_tokens=8192,
        ),
        purpose=purpose,
        agent_id="schedule_parser",
    )
    call = next((c for c in response.tool_calls if c.name == "schedule_entries"), None)
    try:
        parsed = ParsedSchedule.model_validate(call.arguments if call else {})
    except ValidationError as exc:
        raise ToolError(f"could not read the schedule: {exc.errors()[0]['msg']}") from exc
    if not parsed.entries:
        raise ToolError("no weekly entries found; ask the user to write day, time and course")
    proposal = ScheduleProposal(
        conversation_id=ctx.conversation_id,
        source_text=text,
        entries=[entry.model_dump(mode="json") for entry in parsed.entries],
        unclear=parsed.unclear or None,
        parsed_by=f"{response.provider}/{response.model}",
    )
    ctx.session.add(proposal)
    await ctx.session.flush()
    result: dict[str, Any] = {
        "proposal_id": proposal.id,
        "entries": len(parsed.entries),
        "table": schedule_table(parsed.entries),
        "parsed_by": proposal.parsed_by,
    }
    if parsed.unclear:
        result["unclear"] = parsed.unclear
    return result


class ApplyArgs(BaseModel):
    proposal_id: int


@tool(
    "apply_schedule",
    "Save a schedule proposal after the user confirmed the table.",
    ApplyArgs,
    mutates=True,
)
async def apply_schedule(args: ApplyArgs, ctx: ToolContext) -> ToolResult:
    proposal = await ctx.session.get(ScheduleProposal, args.proposal_id)
    if proposal is None:
        raise ToolError(f"no proposal {args.proposal_id}")
    if proposal.status is not ProposalStatus.PENDING:
        raise ToolError(f"proposal {args.proposal_id} is already {proposal.status.value}")
    created, existing = 0, 0
    for raw in proposal.entries:
        entry = ParsedEntry.model_validate(raw)
        result = await create_weekly_blocks(ctx, AddBlockArgs(**entry.model_dump()))
        created += len(result["created"])
        existing += len(result.get("already_existed", []))
    # Superseded proposals of this conversation are closed too.
    others = (
        await ctx.session.scalars(
            select(ScheduleProposal).where(
                ScheduleProposal.status == ProposalStatus.PENDING,
                ScheduleProposal.id != proposal.id,
                ScheduleProposal.conversation_id == proposal.conversation_id,
            )
        )
    ).all()
    for other in others:
        other.status = ProposalStatus.DISCARDED
    proposal.status = ProposalStatus.APPLIED
    proposal.applied_at = ctx.now
    await ctx.session.flush()
    return {"blocks_created": created, "already_existed": existing}


# --- finishing -------------------------------------------------------------------------


class FinishArgs(BaseModel):
    pass


@tool(
    "finish_onboarding",
    "End the setup conversation; later messages go to the normal assistant team.",
    FinishArgs,
)
async def finish_onboarding(_: FinishArgs, ctx: ToolContext) -> ToolResult:
    if ctx.conversation_id is not None:
        conversation = await ctx.session.get(Conversation, ctx.conversation_id)
        if conversation is not None:
            conversation.mode = ConversationMode.CHAT
    return {"onboarding": "finished"}
