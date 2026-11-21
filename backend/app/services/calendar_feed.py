"""The plan as an iCalendar feed (RFC 5545) for a calendar subscription (iPhone Takvim).

Occurrences are expanded with the same `compute_day_plan` the app uses, so cancellations
(left out), moves (at their new time), holidays and terms match what Yaver shows. Times
are written in UTC; the phone shows them in its own zone."""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.localtime import local_datetime
from app.db.models import BlockOverride, Course, Event, Holiday, RecurringBlock, Term
from app.services.schedule import PlanItem, PlanSources, compute_day_plan

PAST_DAYS = 30
FUTURE_DAYS = 180
BLOCK_KINDS = frozenset({"class", "lab"})  # weekly sport / work stay out of the shared feed
KIND_TR = {
    "class": "Ders",
    "lab": "Lab",
    "exam": "Sınav",
    "quiz": "Quiz",
    "makeup": "Telafi",
    "meeting": "Toplantı",
    "deadline": "Teslim",
    "hackathon": "Hackathon",
    "other": "Etkinlik",
}


@dataclass(frozen=True, slots=True)
class FeedItem:
    uid: str
    item: PlanItem


async def feed_items(session: AsyncSession, today: dt.date, tz: ZoneInfo) -> list[FeedItem]:
    first = today - dt.timedelta(days=PAST_DAYS)
    last = today + dt.timedelta(days=FUTURE_DAYS)
    window_start = local_datetime(first - dt.timedelta(days=1), dt.time(), tz)
    window_end = local_datetime(last + dt.timedelta(days=1), dt.time(), tz)
    sources = PlanSources(
        terms=(await session.scalars(select(Term))).all(),
        holidays=(await session.scalars(select(Holiday))).all(),
        courses=(await session.scalars(select(Course))).all(),
        blocks=(
            await session.scalars(
                select(RecurringBlock).where(RecurringBlock.kind.in_(BLOCK_KINDS))
            )
        ).all(),
        overrides=(await session.scalars(select(BlockOverride))).all(),
        events=(
            await session.scalars(
                select(Event).where(
                    Event.start_at < window_end,
                    or_(Event.end_at > window_start, Event.start_at >= window_start),
                )
            )
        ).all(),
    )
    seen: dict[str, FeedItem] = {}
    day = first
    while day <= last:
        for item in compute_day_plan(day, tz, sources).items:
            if item.source == "block" and item.kind not in BLOCK_KINDS:
                continue
            if item.source == "block":
                origin = (item.moved_from or item.start).astimezone(tz).date()
                uid = f"block-{item.source_id}-{origin:%Y%m%d}@yaver"
            else:
                uid = f"event-{item.source_id}@yaver"
            seen.setdefault(uid, FeedItem(uid, item))  # an overnight item shows on two days
        day += dt.timedelta(days=1)
    return sorted(seen.values(), key=lambda f: (f.item.start, f.uid))


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Lines longer than 75 octets continue on the next line after a space."""
    out, current = [], ""
    for char in line:
        if len((current + char).encode()) > 75:
            out.append(current)
            current = " " + char
        else:
            current += char
    out.append(current)
    return out


def _utc(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def render(items: list[FeedItem], now: dt.datetime, name: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Yaver//Takvim//TR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "X-PUBLISHED-TTL:PT1H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    ]
    stamp = _utc(now)
    for feed in items:
        item = feed.item
        lines += ["BEGIN:VEVENT", f"UID:{feed.uid}", f"DTSTAMP:{stamp}"]
        if item.all_day:
            start = item.start.date()
            end = (item.end.date() if item.end else start) + dt.timedelta(days=1)
            if item.end and item.end.time() == dt.time() and item.end.date() > start:
                end = item.end.date()  # an exclusive midnight end already
            lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
        else:
            lines += [f"DTSTART:{_utc(item.start)}", f"DTEND:{_utc(item.end or item.start)}"]
        lines.append(f"SUMMARY:{_escape(item.title)}")
        if item.location:
            lines.append(f"LOCATION:{_escape(item.location)}")
        details = [KIND_TR.get(item.kind, item.kind)]
        if item.moved_from:
            details.append(f"Taşındı (önce {item.moved_from:%d.%m %H:%M})")
        if item.note:
            details.append(item.note)
        lines.append(f"DESCRIPTION:{_escape(' · '.join(details))}")
        lines.append(f"CATEGORIES:{_escape(KIND_TR.get(item.kind, item.kind))}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "".join(part + "\r\n" for line in lines for part in _fold(line))
