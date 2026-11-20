"""Reads the PDFs of a chat message in code, before any yaver sees the message (like
agent.vision does for images). The team gets "[PDF N ...]" blocks.

1. Text comes from the PDF itself (pypdf), never from a model.
2. `document_classify` (fast tier, first pages only): syllabus, lecture notes / slides, other.
3. A syllabus is read by `syllabus_parse` (Sonnet): course + topics per week -> a proposal
   with a table. Nothing is saved before the user says yes (apply_proposal); then the
   weekly topics, the material and its searchable passages are written.
4. Lecture notes become a pending material (agent.intake): Friday links them to a course
   and week (save_material), then they are searchable.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.context import ToolContext
from app.agent.intake import pending_material
from app.agent.tools import json_schema
from app.db.models import Proposal
from app.db.models.enums import ProposalKind
from app.llm.router import LLMUnavailableError
from app.llm.types import ChatMessage, LLMRequest, LLMResponse, ProviderError, ToolSpec
from app.rag.pdf import PdfError, page_texts

logger = logging.getLogger(__name__)

CLASSIFY_PURPOSE = "document_classify"  # fast tier
SYLLABUS_PURPOSE = "syllabus_parse"  # smart tier (Sonnet)
CLASSIFY_CHARS = 3000
SYLLABUS_CHARS = 40_000  # ~10k tokens: a syllabus is a few pages
MIN_TEXT_CHARS = 80  # less: probably a scanned PDF (no text layer)


class DocumentKind(BaseModel):
    kind: Literal["syllabus", "notes", "other"] = Field(
        description="syllabus: a course outline with weekly topics; notes: lecture notes, "
        "slides, a textbook chapter; other: anything else"
    )
    course: str | None = Field(None, description="course code or name as written, if any")
    summary: str = Field(description="one short Turkish sentence: what the document is")


class SyllabusWeekIn(BaseModel):
    week_no: int = Field(ge=1, le=30)
    topics: str = Field(description="the week's topics, short, as written (keep the language)")


class ParsedSyllabus(BaseModel):
    course_code: str | None = Field(None, description="e.g. 'EE211', as written")
    course_name: str | None = None
    weeks: list[SyllabusWeekIn] = Field(default_factory=list)
    unclear: list[str] = Field(
        default_factory=list, description="weeks or lines that could not be read"
    )


CLASSIFY_TOOL = ToolSpec("document_kind", "Say what the document is.", json_schema(DocumentKind))
SYLLABUS_TOOL = ToolSpec(
    "syllabus", "Return the course and its weekly topics.", json_schema(ParsedSyllabus)
)

CLASSIFY_PROMPT = (
    "You get the first pages of a PDF a university student sent. Say what it is by calling "
    "document_kind. A syllabus / course outline lists the course's topics week by week."
)
SYLLABUS_PROMPT = (
    "You get the text of a course syllabus. Call syllabus with the course code and name and "
    "one entry per teaching week: its number and its topics, short and in the document's "
    "language. Midterm / final weeks are weeks too ('Ara sınav'). Keep the document's week "
    "numbers; do not invent weeks or topics. Weeks you cannot read go into unclear."
)


@dataclass(slots=True)
class DocumentInput:
    attachment_id: int
    filename: str
    data: bytes


async def read_documents(ctx: ToolContext, documents: list[DocumentInput], first: int = 1) -> str:
    """The "[PDF N ...]" blocks; `first` continues the numbering after the images."""
    blocks = []
    for number, item in enumerate(documents, start=first):
        try:
            blocks.append(await _read_one(ctx, number, item))
        except PdfError as exc:
            reason = {"encrypted": "şifreli", "too_many_pages": "çok uzun"}.get(exc.code, "bozuk")
            blocks.append(f"[PDF {number}: {item.filename} okunamadı ({reason})]")
        except (LLMUnavailableError, ProviderError, ValidationError, ValueError) as exc:
            logger.warning("PDF %s could not be read: %s", item.attachment_id, exc)
            blocks.append(f"[PDF {number}: {item.filename} şu an okunamadı (model yok)]")
    return "\n\n".join(blocks)


async def _read_one(ctx: ToolContext, number: int, item: DocumentInput) -> str:
    pages = await asyncio.to_thread(page_texts, item.data)
    text = "\n\n".join(f"[s. {i}]\n{page}" for i, page in enumerate(pages, start=1) if page)
    name = f"{item.filename}, {len(pages)} sayfa"
    if sum(len(p) for p in pages) < MIN_TEXT_CHARS:
        return (
            f"[PDF {number}: {name}: içinde metin yok (taranmış olabilir); sayfaların "
            "fotoğrafını gönderirse okuyabilirim]"
        )
    response = await _ask(
        ctx, CLASSIFY_PROMPT, CLASSIFY_TOOL, text[:CLASSIFY_CHARS], CLASSIFY_PURPOSE
    )
    kind = DocumentKind.model_validate(_arguments(response, CLASSIFY_TOOL.name))
    if kind.kind == "syllabus":
        return await _syllabus(ctx, number, item, name, text)
    if kind.kind == "notes":
        pending = await pending_material(
            ctx,
            attachment_id=item.attachment_id,
            title=item.filename,
            pages=len(pages),
            sample=text,
            course_hint=kind.course,
        )
        return f"[PDF {number}: {name}: {kind.summary} {pending}]"
    return f"[PDF {number}: {name}: {kind.summary}]"


async def _syllabus(
    ctx: ToolContext, number: int, item: DocumentInput, name: str, text: str
) -> str:
    response = await _ask(
        ctx, SYLLABUS_PROMPT, SYLLABUS_TOOL, text[:SYLLABUS_CHARS], SYLLABUS_PURPOSE
    )
    parsed = ParsedSyllabus.model_validate(_arguments(response, SYLLABUS_TOOL.name))
    weeks = sorted({w.week_no: w for w in parsed.weeks}.values(), key=lambda w: w.week_no)
    course = parsed.course_code or parsed.course_name
    if not weeks or not course:
        missing = "haftalık konu" if not weeks else "ders kodu"
        return _with_unclear(
            f"[PDF {number}: {name}: syllabus gibi ama {missing} okunamadı]", parsed.unclear
        )
    proposal = Proposal(
        conversation_id=ctx.conversation_id,
        kind=ProposalKind.SYLLABUS,
        source_text=f"[pdf #{item.attachment_id}] {item.filename}",
        entries=[
            {
                "attachment_id": item.attachment_id,
                "filename": item.filename,
                "course": parsed.course_code,
                "course_name": parsed.course_name,
                "week_no": week.week_no,
                "topics": week.topics,
            }
            for week in weeks
        ],
        unclear=parsed.unclear or None,
        parsed_by=f"{response.provider}/{response.model}",
    )
    ctx.session.add(proposal)
    await ctx.session.flush()
    ctx.new_proposals.add(proposal.id)
    title = " ".join(p for p in (parsed.course_code, parsed.course_name) if p)
    header = (
        f"[PDF {number}: {name}: {title} syllabus'u, {len(weeks)} hafta -> öneri "
        f"#{proposal.id}, henüz kaydedilmedi]"
    )
    return _with_unclear(f"{header}\n{syllabus_table(weeks)}", parsed.unclear)


def syllabus_table(weeks: list[SyllabusWeekIn]) -> str:
    lines = ["| Hafta | Konular |", "|---|---|"]
    lines += [f"| {w.week_no} | {w.topics.replace('|', '/')} |" for w in weeks]
    return "\n".join(lines)


async def _ask(
    ctx: ToolContext, system: str, tool: ToolSpec, text: str, purpose: str
) -> LLMResponse:
    if ctx.llm is None:
        raise ValueError("no LLM client")
    response: LLMResponse = await ctx.llm.complete(
        LLMRequest(
            system=system,
            messages=[ChatMessage("user", text)],
            tools=[tool],
            tool_choice="required",
            max_tokens=8192,
        ),
        purpose=purpose,
        agent_id="document_reader",
    )
    return response


def _arguments(response: LLMResponse, name: str) -> dict[str, object]:
    call = next((c for c in response.tool_calls if c.name == name), None)
    if call is None or call.arguments is None:
        raise ValueError(f"the model did not call {name} with valid JSON")
    return call.arguments


def _with_unclear(text: str, unclear: list[str]) -> str:
    if not unclear:
        return text
    return text + "\nBelirsiz (tahmin edilmedi): " + "; ".join(unclear)
