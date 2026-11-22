"""Creator's weekly content calendar: a DRAFT, never posted.

The context is gathered in code - the brands / topics Creator works for (agents.yaml
`topics` of the content_calendar job, or the chat), memories mentioning them, Venture's
recent notebook (the startup's news, the repo map), upcoming events about them and, when
a web search key exists, this week's trends. One structured call (`content_calendar`,
smart) proposes the posts; weekdays become dates in code. The result goes to Creator's
notebook as "taslak, paylaşılmadı": there is no tool that posts anything.
"""

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schema import json_schema
from app.db.models import EmployeeNote, Event, Memory
from app.integrations import web_search as websearch
from app.llm.router import LLMUnavailableError
from app.llm.types import ChatMessage, LLMRequest, ProviderError, ToolSpec

logger = logging.getLogger(__name__)

PURPOSE = "content_calendar"  # smart (providers.yaml)
TITLE = "İçerik takvimi taslağı"
STARTUP_ID = "startup"  # Venture: its notebook is the startup's news
NOTES_DAYS = 14
MAX_NOTES = 12
MAX_NOTE_CHARS = 600
EVENT_DAYS = 14
WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
MONTHS = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")


class PlannedPost(BaseModel):
    weekday: Literal["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    platform: Literal["Instagram", "LinkedIn", "X", "TikTok"]
    format: Literal["post", "carousel", "reel", "story", "thread"]
    topic: str = Field(max_length=120)
    draft: str = Field(max_length=400, description="caption / text draft in Turkish")
    basis: str = Field(
        max_length=160, description="what it builds on: a note, an event, a memory or a trend"
    )


class ContentPlan(BaseModel):
    posts: list[PlannedPost] = Field(min_length=3, max_length=7)
    needs: list[str] = Field(
        default_factory=list, description="what the team must provide (photo, number, quote)"
    )


TOOL = ToolSpec("content_plan", "Return the week's post drafts.", json_schema(ContentPlan))
PROMPT = (
    "You are Creator, the content producer of a Turkish user's small team. Plan next week's "
    "social media posts for the brand(s) given. Call content_plan exactly once.\n"
    "- 4-6 posts on different days; mix formats; Instagram and LinkedIn first.\n"
    "- Build only on the context: notes, events, memories and (if any) trends. Never invent "
    "facts, numbers, customers, dates or quotes; anything the team must supply goes to needs.\n"
    '- basis: name what each post builds on ("Venture notu: ...", "etkinlik: ...", '
    '"trend: ...").\n'
    "- These are drafts the user will review: never say anything was or will be posted.\n"
    "- Dated events: read their weekday from the list. A post before an event announces it; "
    "only a post on or after its day may say it happened.\n"
    "- Turkish, natural, short captions with at most 3 hashtags."
)


@dataclass(slots=True)
class CalendarResult:
    text: str  # the notebook note / tool result
    posts: int
    trends: bool


def week_after(today: dt.date) -> tuple[dt.date, dt.date]:
    """Monday-Sunday of the week to plan: this week if today is Monday, else the next."""
    monday = today + dt.timedelta(days=(7 - today.weekday()) % 7)
    return monday, monday + dt.timedelta(days=6)


async def gather_context(
    session: AsyncSession,
    topics: list[str],
    now: dt.datetime,
    tz: ZoneInfo,
    search: websearch.WebSearch | None,
) -> tuple[str, bool]:
    """(context text, trends included?)."""
    parts = [f"Marka / konular: {', '.join(topics) or '(belirtilmedi)'}"]
    words = [t for t in topics if t.strip()]
    if words:
        memories = (
            await session.scalars(
                select(Memory.content)
                .where(Memory.active, or_(*(Memory.content.ilike(f"%{w}%") for w in words)))
                .order_by(Memory.id)
            )
        ).all()
        if memories:
            parts.append("Kalıcı bilgiler:\n" + "\n".join(f"- {m}" for m in memories))
    notes = (
        await session.scalars(
            select(EmployeeNote)
            .where(
                EmployeeNote.employee_id == STARTUP_ID,
                EmployeeNote.created_at >= now - dt.timedelta(days=NOTES_DAYS),
            )
            .order_by(EmployeeNote.created_at.desc())
            .limit(MAX_NOTES)
        )
    ).all()
    useful = [n for n in notes if "bekliyor" not in n.content]  # skip "integration pending"
    if useful:
        parts.append(
            "Venture'ın son notları (startup):\n"
            + "\n".join(f"- {n.content[:MAX_NOTE_CHARS]}" for n in reversed(useful))
        )
    start = now
    end = now + dt.timedelta(days=EVENT_DAYS)
    query = select(Event).where(Event.start_at >= start, Event.start_at < end)
    if words:
        query = query.where(
            or_(
                *(
                    func.concat(Event.title, " ", func.coalesce(Event.notes, "")).ilike(f"%{w}%")
                    for w in words
                )
            )
        )
    events = (await session.scalars(query.order_by(Event.start_at).limit(10))).all()
    if events:
        parts.append(
            "Yaklaşan etkinlikler:\n"
            + "\n".join(f"- {_dated(e.start_at.astimezone(tz).date())}: {e.title}" for e in events)
        )
    trends = False
    if search is not None and words:
        lines = []
        for topic in words[:2]:
            try:
                results = await search.search(f"{topic} sosyal medya içerik trendleri", 4)
            except websearch.SearchError as exc:
                logger.warning("content calendar trends: %s", exc)
                continue
            lines += [f"- {r.title} ({r.site}): {r.snippet[:160]}" for r in results]
        if lines:
            parts.append("Bu haftanın trendleri (web):\n" + "\n".join(lines))
            trends = True
    if not trends:
        parts.append("Trend verisi yok: plan yalnızca ekibin notlarına dayanmalı.")
    return "\n\n".join(parts), trends


async def draft_calendar(
    session: AsyncSession,
    llm: Any,
    *,
    employee_id: str,
    topics: list[str],
    now: dt.datetime,
    tz: ZoneInfo,
    search: websearch.WebSearch | None,
) -> CalendarResult | None:
    """The draft (the caller writes it to the notebook), or None if no model answered."""
    monday, sunday = week_after(now.astimezone(tz).date())
    context, trends = await gather_context(session, topics, now, tz, search)
    request = LLMRequest(
        system=PROMPT,
        messages=[
            ChatMessage(
                "user",
                f"Planlanacak hafta: {_day(monday)} - {_day(sunday)} ("
                + ", ".join(_dated(monday + dt.timedelta(days=i)) for i in range(7))
                + f")\n\n{context}",
            )
        ],
        tools=[TOOL],
        tool_choice="required",
        max_tokens=8000,
    )
    try:
        response = await llm.complete(request, purpose=PURPOSE, agent_id=employee_id)
        call = next((c for c in response.tool_calls if c.name == TOOL.name), None)
        if call is None or call.arguments is None:
            raise ValueError("the model did not call content_plan")
        plan = ContentPlan.model_validate(call.arguments)
    except (LLMUnavailableError, ProviderError, ValidationError, ValueError) as exc:
        logger.warning("content calendar: %s", exc)
        return None
    return CalendarResult(calendar_text(plan, monday, sunday, trends), len(plan.posts), trends)


def calendar_text(plan: ContentPlan, monday: dt.date, sunday: dt.date, trends: bool) -> str:
    rows = sorted(plan.posts, key=lambda p: WEEKDAYS.index(p.weekday))
    lines = [
        f"{TITLE} ({_day(monday)} - {_day(sunday)}), paylaşılmadı, onayını bekliyor:",
        "| Gün | Platform | Biçim | Konu | Taslak | Dayanak |",
        "|---|---|---|---|---|---|",
    ]
    for post in rows:
        day = monday + dt.timedelta(days=WEEKDAYS.index(post.weekday))
        cells = [
            f"{_day(day)} {post.weekday}",
            post.platform,
            post.format,
            post.topic,
            post.draft.replace("\n", " "),
            post.basis,
        ]
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    if plan.needs:
        lines.append("Ekipten gerekenler: " + "; ".join(plan.needs))
    lines.append(
        "Trendler eklendi (web)."
        if trends
        else "Trend yok: web arama anahtarı gelince trendleri de eklerim."
    )
    return "\n".join(lines)


def _dated(day: dt.date) -> str:
    """'28 Kas Cumartesi': the model reads the weekday instead of computing it."""
    return f"{_day(day)} {WEEKDAYS[day.weekday()]}"


def _day(day: dt.date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"
