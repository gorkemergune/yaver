"""Venture's meeting preparation: an hour before a startup meeting (an event linked to
Venture when it was added, app.startup.meeting) a chat message - the latest week's
presentation draft per member from the repo, whose folder is empty - and a push. Built in
code from the read-only GitHub summary (no LLM); sent once (events.prep_sent_at).

Runs every CHECK_MINUTES (app.jobs.scheduler), so a meeting added less than an hour
before gets its message at the next check.
"""

import datetime as dt
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.tools import github as github_tools
from app.config import Settings, get_settings
from app.core.time_resolver import WEEKDAY_NAMES_TR, normalize
from app.db.models import Conversation, Event, Message
from app.db.models.enums import ConversationMode, MessageRole
from app.db.session import get_sessionmaker
from app.integrations import github as gh
from app.services.push import Notification, preview, send_push
from app.startup.meeting import STARTUP_ID

logger = logging.getLogger(__name__)

PREP_AHEAD = dt.timedelta(hours=1)
CHECK_MINUTES = 5
KIND = "meeting_prep"
LINE_CHARS = 160


def _first_line(text: str | None) -> str:
    """A README's title / first sentence, without markdown."""
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("(", "!", "<", "```")):
            return line[:LINE_CHARS]
    return ""


def _who(member: dict[str, Any]) -> str:
    authors = list(member.get("commit_authors") or {})
    name = str(member["folder_or_file"])
    if authors:
        return f"{name} ({', '.join(a.split(' (')[0] for a in authors[:2])})"
    return name


def draft(summary: dict[str, Any], event: Event, tz: dt.tzinfo) -> str:
    """The message: when, the week's draft per member, empty / missing folders."""
    start = event.start_at.astimezone(tz)
    head = (
        f"{event.title} {WEEKDAY_NAMES_TR[start.weekday()]} {start:%H:%M}'de (1 saatten az kaldı)."
    )
    if summary.get("error"):
        folders = ", ".join(summary.get("week_folders") or []) or "yok"
        week = summary.get("week")
        return f"{head} Depoda week {week} klasörü bulamadım (week klasörleri: {folders})."
    week = summary["week"]
    lines = [head, f"Week {week} sunum taslağı hazır ({summary['folder']}):"]
    if summary.get("single_author"):
        lines.append(
            f"Bu haftanın bütün dosyaları tek kişiden ({summary['single_author']}); üye bazında "
            "teslim yok, parçalar:"
        )
    for member in summary["members"]:
        if member.get("empty"):
            continue
        what = _first_line(member.get("readme")) or ", ".join(member.get("files", [])[:3])
        commits = member.get("commit_messages") or []
        if commits and normalize(commits[0]) not in normalize(what):
            what = f"{what} (son commit: {commits[0]})" if what else commits[0]
        lines.append(f"- {_who(member)}: {what}")
    empty = list(summary.get("empty_folders") or [])
    missing = list(summary.get("no_folder_this_week") or [])
    if empty:
        lines.append(f"Klasörü boş: {', '.join(empty)}.")
    if missing:
        lines.append(f"Geçen hafta teslim edip bu hafta klasörü olmayan: {', '.join(missing)}.")
    if not empty and not missing:
        lines.append("Boş klasör yok.")
    return "\n".join(lines)


async def _post(session: AsyncSession, employee_id: str, text: str, now: dt.datetime) -> None:
    """Into the latest main chat (a new one if none), like the shift jobs' messages."""
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.mode == ConversationMode.CHAT, Conversation.employee_id.is_(None))
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(1)
    )
    if conversation is None:
        conversation = Conversation(title="Yaver")
        session.add(conversation)
        await session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            agent_id=employee_id,
            content=text,
            kind=KIND,
        )
    )
    conversation.updated_at = now
    conversation.pending_action = None


async def prepare_due(
    session: AsyncSession,
    now: dt.datetime,
    settings: Settings,
    *,
    github_factory: Callable[..., gh.GitHub | None] | None = None,
) -> list[str]:
    """Send the preparation of every linked meeting starting within PREP_AHEAD; the texts."""
    due = (
        await session.scalars(
            select(Event)
            .where(
                Event.owner_id == STARTUP_ID,
                Event.prep_sent_at.is_(None),
                Event.all_day.is_(False),
                Event.start_at > now,
                Event.start_at <= now + PREP_AHEAD,
            )
            .order_by(Event.start_at)
        )
    ).all()
    sent: list[str] = []
    for event in due:
        problem = gh.setup_problem(settings)
        client = None if problem else (github_factory or gh.get_github)(settings)
        if client is None:
            start = event.start_at.astimezone(settings.tz)
            text = (
                f"{event.title} {start:%H:%M}'de (1 saatten az kaldı). Sunum taslağını "
                f"hazırlayamadım: {problem or gh.NO_REPO}"
            )
        else:
            try:
                summary = await github_tools.summarize_week(client, None, settings.tz)
                text = draft(summary, event, settings.tz)
            except gh.GitHubError as exc:
                text = f"{event.title}: sunum taslağını hazırlayamadım: {exc}"
            finally:
                await client.aclose()
        await _post(session, event.owner_id or STARTUP_ID, text, now)
        event.prep_sent_at = now
        sent.append(text)
    if sent:
        await session.commit()
        for text in sent:  # committed: a failed push changes nothing
            try:
                await send_push(
                    session,
                    settings,
                    Notification(title="Toplantı hazırlığı 🚀", body=preview(text), tag=KIND),
                    now,
                )
            except Exception:
                logger.exception("Web Push for the meeting preparation failed")
                await session.rollback()
    return sent


async def run_meeting_prep(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> list[str]:
    """The scheduler's entry point (every CHECK_MINUTES)."""
    settings = settings or get_settings()
    async with (sessionmaker or get_sessionmaker())() as session:
        return await prepare_due(session, now or dt.datetime.now(dt.UTC), settings)
