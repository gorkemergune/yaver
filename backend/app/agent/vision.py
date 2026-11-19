"""Reads the images of a chat message in code, before any yaver sees the message.

Only Claude reads images (the router skips providers without vision, so Groq never gets
one). The team gets the result as text - a "[Görsel N ...]" block - so the coordinator can
be any model, and the same block is replayed with the history on the next message ("evet").

1. `image_read` (Haiku): what is it - weekly schedule, event / announcement, document /
   notes, or something else - plus the events of an announcement, dates as written.
2. Schedules and documents are read again by `schedule_image` / `document_image` (Sonnet,
   smart tier: under the Claude budget guard).

Dates are never computed by a model: "28 Kasım Cuma" is resolved by core.time_resolver.
Anything unreadable or unresolvable is listed as "Belirsiz", never guessed.
"""

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.context import ToolContext
from app.agent.tools import HHMM_PATTERN, json_schema
from app.agent.tools.setup import (
    PARSER_TOOL,
    ParsedSchedule,
    ProposedEvent,
    events_table,
    schedule_table,
)
from app.core.time_resolver import Reason, Resolution, Status, resolve
from app.db.models import Proposal
from app.db.models.enums import ProposalKind
from app.llm.router import LLMUnavailableError
from app.llm.types import ChatMessage, ImagePart, LLMRequest, LLMResponse, ProviderError, ToolSpec

logger = logging.getLogger(__name__)

READ_PURPOSE = "image_read"  # Haiku
SCHEDULE_PURPOSE = "schedule_image"  # Sonnet (smart)
DOCUMENT_PURPOSE = "document_image"  # Sonnet (smart)
MAX_DOCUMENT_CHARS = 4000


class ImageEvent(BaseModel):
    kind: Literal["exam", "quiz", "makeup", "meeting", "deadline", "hackathon", "other"]
    title: str = Field(
        description="short and self-contained, with the course code if any ('EE211 Ara Sınav')"
    )
    course: str | None = Field(None, description="course code or name, if any")
    date_text: str | None = Field(
        None, description="the date exactly as written ('28 Kasım Cuma', '28.11.2026')"
    )
    start_time: str | None = Field(None, pattern=HHMM_PATTERN, description="HH:MM, 24h")
    end_time: str | None = Field(None, pattern=HHMM_PATTERN, description="HH:MM, 24h")
    location: str | None = None


class ImageReading(BaseModel):
    kind: Literal["schedule", "event", "document", "other"]
    summary: str = Field(description="one Turkish sentence: what the image shows")
    events: list[ImageEvent] = Field(default_factory=list)
    unclear: list[str] = Field(default_factory=list)


class DocumentText(BaseModel):
    text: str = Field(description="the readable content, as Markdown (tables as tables)")
    unclear: list[str] = Field(default_factory=list)


READ_TOOL = ToolSpec("image_contents", "Report what the image contains.", json_schema(ImageReading))
DOCUMENT_TOOL = ToolSpec("document_text", "Return the image's text.", json_schema(DocumentText))

READ_PROMPT = (
    "You look at an image a Turkish university student sent to their assistant. Call "
    "image_contents exactly once.\n"
    "kind: schedule = a weekly class timetable (ders programı); event = an announcement, "
    "poster, invitation or notice with one or more dated things (exam, quiz, make-up class, "
    "meeting, deadline, hackathon, event); document = notes, a slide, a table or other text "
    "worth reading in full; other = anything else.\n"
    "For event: one entry per dated thing. date_text is the date exactly as written; never "
    "compute or complete a date (no year or weekday that is not there). A missing year is "
    "normal and NOT unclear: the date is resolved later. Times HH:MM 24h.\n"
    "Never guess: anything you cannot read with certainty goes into unclear, quoted as seen."
)
SCHEDULE_PROMPT = (
    "You turn a photo or screenshot of a Turkish university student's weekly timetable into "
    "structured entries. Call schedule_entries exactly once.\n"
    "- One entry per course session type; list every weekday it happens on.\n"
    "- kind: class for lectures, lab for labs / PS / uygulama, sport, work, other.\n"
    "- title as the student would call it; course: the course code if there is one.\n"
    "- Times HH:MM, 24h.\n"
    "- Never guess: a cell you cannot read with certainty (blurred, cut off, missing time or "
    "day) goes into `unclear` as you see it, not into entries."
)
DOCUMENT_PROMPT = (
    "Transcribe the readable content of this image as Markdown (keep tables as tables, keep "
    "the original language). Call document_text exactly once. Never guess: unreadable parts "
    "go into unclear."
)


@dataclass(slots=True)
class ImageInput:
    attachment_id: int
    image: ImagePart


async def read_images(ctx: ToolContext, images: list[ImageInput]) -> str:
    """The "[Görsel N ...]" blocks for a message's images (empty string for none)."""
    blocks = []
    for number, item in enumerate(images, start=1):
        try:
            blocks.append(await _read_one(ctx, number, item))
        except (LLMUnavailableError, ProviderError, ValidationError, ValueError) as exc:
            logger.warning("Image %s could not be read: %s", item.attachment_id, exc)
            blocks.append(f"[Görsel {number} okunamadı: görseli okuyabilen model şu an yok.]")
    return "\n\n".join(blocks)


async def _read_one(ctx: ToolContext, number: int, item: ImageInput) -> str:
    response = await _ask(ctx, READ_PROMPT, READ_TOOL, item.image, READ_PURPOSE)
    reading = ImageReading.model_validate(_arguments(response, READ_TOOL.name))
    if reading.kind == "schedule":
        return await _schedule(ctx, number, item)
    if reading.kind == "event":
        return await _events(ctx, number, item, reading, response)
    if reading.kind == "document":
        return await _document(ctx, number, item)
    return f"[Görsel {number}: {reading.summary}]"


async def _schedule(ctx: ToolContext, number: int, item: ImageInput) -> str:
    response = await _ask(ctx, SCHEDULE_PROMPT, PARSER_TOOL, item.image, SCHEDULE_PURPOSE)
    parsed = ParsedSchedule.model_validate(_arguments(response, PARSER_TOOL.name))
    if not parsed.entries:
        return _with_unclear(
            f"[Görsel {number}: ders programı gibi görünüyor ama okunabilen ders yok]",
            parsed.unclear,
        )
    proposal = await _proposal(
        ctx,
        ProposalKind.SCHEDULE,
        item,
        [e.model_dump(mode="json") for e in parsed.entries],
        parsed.unclear,
        response,
    )
    header = (
        f"[Görsel {number}: haftalık ders programı -> öneri #{proposal.id}, henüz kaydedilmedi]"
    )
    return _with_unclear(f"{header}\n{schedule_table(parsed.entries)}", parsed.unclear)


async def _events(
    ctx: ToolContext, number: int, item: ImageInput, reading: ImageReading, response: LLMResponse
) -> str:
    today = ctx.now.astimezone(ctx.tz).date()
    entries: list[ProposedEvent] = []
    unclear = list(reading.unclear)
    for event in reading.events:
        resolution, problem = resolve_notice_date(event.date_text or "", today, ctx)
        if resolution is None:
            unclear.append(f"{event.title}: {problem} ({event.date_text or 'tarih yok'})")
            continue
        entries.append(
            ProposedEvent.model_validate(
                {
                    **event.model_dump(exclude={"date_text"}),
                    "date": resolution.start,
                    # "28 Kasım 14:00" may carry the time in the date text itself
                    "start_time": event.start_time or resolution.time,
                    "end_time": event.end_time or resolution.end_time,
                }
            )
        )
    if not entries:
        return _with_unclear(f"[Görsel {number}: {reading.summary}]", unclear)
    proposal = await _proposal(
        ctx,
        ProposalKind.EVENTS,
        item,
        [e.model_dump(mode="json") for e in entries],
        unclear,
        response,
    )
    header = f"[Görsel {number}: {reading.summary} -> öneri #{proposal.id}, henüz kaydedilmedi]"
    return _with_unclear(f"{header}\n{events_table(entries)}", unclear)


def resolve_notice_date(
    text: str, today: dt.date, ctx: ToolContext
) -> tuple[Resolution | None, str]:
    """A notice's date as written ("27 Kasım Cuma 10:00", "27.11.2026") -> one day, or
    (None, why). A weekday that does not fit the date, a whole month ("Aralık") or no date
    is reported, never guessed."""
    resolution = resolve(text, today, direction="future", clock=ctx.clock)
    if resolution.reason is Reason.WEEKDAY_MISMATCH:
        return None, "gün adı tarihle uyuşmuyor"
    if resolution.status is not Status.RESOLVED or resolution.span is None:
        return None, "tarih okunamadı"
    if not resolution.span.is_single_day:
        return None, "tek bir gün değil"
    return resolution, ""


async def _document(ctx: ToolContext, number: int, item: ImageInput) -> str:
    response = await _ask(ctx, DOCUMENT_PROMPT, DOCUMENT_TOOL, item.image, DOCUMENT_PURPOSE)
    document = DocumentText.model_validate(_arguments(response, DOCUMENT_TOOL.name))
    text = document.text.strip()
    if len(text) > MAX_DOCUMENT_CHARS:
        text = text[:MAX_DOCUMENT_CHARS] + "\n[... devamı kısaltıldı]"
    return _with_unclear(f"[Görsel {number}: belge / not]\n{text}", document.unclear)


async def _ask(
    ctx: ToolContext, system: str, tool: ToolSpec, image: ImagePart, purpose: str
) -> LLMResponse:
    if ctx.llm is None:
        raise ValueError("no LLM client")
    response: LLMResponse = await ctx.llm.complete(
        LLMRequest(
            system=system,
            messages=[ChatMessage("user", "", images=[image])],
            tools=[tool],
            tool_choice="required",
            max_tokens=8192,
        ),
        purpose=purpose,
        agent_id="image_reader",
    )
    return response


def _arguments(response: LLMResponse, name: str) -> dict[str, Any]:
    call = next((c for c in response.tool_calls if c.name == name), None)
    if call is None or call.arguments is None:
        raise ValueError(f"the model did not call {name} with valid JSON")
    return call.arguments


async def _proposal(
    ctx: ToolContext,
    kind: ProposalKind,
    item: ImageInput,
    entries: list[dict[str, Any]],
    unclear: list[str],
    response: LLMResponse,
) -> Proposal:
    proposal = Proposal(
        conversation_id=ctx.conversation_id,
        kind=kind,
        source_text=f"[görsel #{item.attachment_id}]",
        entries=entries,
        unclear=unclear or None,
        parsed_by=f"{response.provider}/{response.model}",
    )
    ctx.session.add(proposal)
    await ctx.session.flush()
    ctx.new_proposals.add(proposal.id)
    return proposal


def _with_unclear(text: str, unclear: list[str]) -> str:
    if not unclear:
        return text
    return text + "\nBelirsiz (tahmin edilmedi): " + "; ".join(unclear)
