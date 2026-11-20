"""Read-only data for the web app: team, day/week plans, attendance, chat history."""

import datetime as dt
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.team import Team, get_team
from app.api.uploads import attachment_view
from app.config import get_settings
from app.core.change_log import describe_changes
from app.core.time_resolver import week_start
from app.db.models import Attachment, ChangeLog, Conversation, Message, RecurringBlock, Term
from app.db.models.enums import ConversationMode, MessageRole
from app.db.session import get_session
from app.services.attendance import all_course_summaries
from app.services.plan_view import plan_to_dict
from app.services.schedule import get_day_plan

router = APIRouter(tags=["views"])


def _today() -> dt.date:
    settings = get_settings()
    return dt.datetime.now(dt.UTC).astimezone(settings.tz).date()


@router.get("/team")
async def team(members: Team = Depends(get_team)) -> dict[str, Any]:
    def view(member: Any) -> dict[str, Any]:
        return {
            "id": member.id,
            "name": member.name,
            "color": member.color,
            "domain": member.domain,
        }

    return {
        "coordinator": view(members.coordinator),
        "agents": [view(agent) for agent in members.agents],
        "onboarding": view(members.onboarding) if members.onboarding else None,
        "user_name": get_settings().app_user_name,
    }


@router.get("/team/activity")
async def team_activity(
    per_agent: int = Query(5, ge=1, le=20),
    members: Team = Depends(get_team),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Recent changes per yaver (newest first) for the team page."""
    activity: dict[str, Any] = {}
    for member in (members.coordinator, *members.agents):
        entries = list(
            (
                await session.scalars(
                    select(ChangeLog)
                    .where(ChangeLog.agent_id == member.id)
                    .order_by(ChangeLog.id.desc())
                    .limit(per_agent)
                )
            ).all()
        )
        changes = await describe_changes(session, entries)
        for change, entry in zip(changes, entries, strict=True):
            change["at"] = entry.created_at
        activity[member.id] = changes
    return {"activity": activity}


@router.get("/onboarding/status")
async def onboarding_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Nothing set up yet (no term, no weekly blocks): the web app offers the setup chat
    (the user can skip it)."""
    has_term = await session.scalar(select(Term.id).limit(1)) is not None
    has_blocks = await session.scalar(select(RecurringBlock.id).limit(1)) is not None
    open_setup = await session.scalar(
        select(Conversation.id)
        .where(Conversation.mode == ConversationMode.ONBOARDING)
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    return {
        "needed": not (has_term or has_blocks),
        "open_conversation_id": open_setup,  # setup started but not finished
    }


@router.get("/plan/day")
async def day_plan(
    date: dt.date | None = Query(None, description="YYYY-MM-DD; default today"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    today = _today()
    plan = await get_day_plan(session, date or today, get_settings().tz)
    return {"today": today.isoformat(), **plan_to_dict(plan)}


@router.get("/plan/week")
async def week_plan(
    date: dt.date | None = Query(None, description="any day of the week; default today"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    today = _today()
    monday = week_start(date or today)
    days = []
    for offset in range(7):
        plan = await get_day_plan(session, monday + dt.timedelta(days=offset), get_settings().tz)
        days.append(plan_to_dict(plan))
    return {"today": today.isoformat(), "week_start": monday.isoformat(), "days": days}


@router.get("/attendance")
async def attendance(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return {"courses": await all_course_summaries(session)}


@router.get("/conversations/latest")
async def latest_conversation(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    conversation_id = await session.scalar(
        select(Conversation.id).order_by(Conversation.updated_at.desc()).limit(1)
    )
    return {"conversation_id": conversation_id}


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: int,
    limit: int = Query(60, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if await session.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    rows = list(
        reversed(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.id.desc())
                    .limit(limit)
                )
            ).all()
        )
    )
    set_ids = {row.change_set_id for row in rows if row.change_set_id}
    change_sets: dict[str, dict[str, Any]] = {}
    if set_ids:
        entries = (
            await session.scalars(
                select(ChangeLog).where(ChangeLog.change_set_id.in_(set_ids)).order_by(ChangeLog.id)
            )
        ).all()
        grouped: dict[uuid.UUID, list[ChangeLog]] = defaultdict(list)
        for entry in entries:
            grouped[entry.change_set_id].append(entry)
        for set_id, group in grouped.items():
            changes = await describe_changes(session, group)
            change_sets[str(set_id)] = {
                "changes": changes,
                "undone": all(change["undone"] for change in changes),
            }
    images: dict[int, list[dict[str, Any]]] = defaultdict(list)
    message_ids = [row.id for row in rows if row.role is MessageRole.USER]
    if message_ids:
        for attachment in (
            await session.scalars(
                select(Attachment)
                .where(Attachment.message_id.in_(message_ids))
                .order_by(Attachment.id)
            )
        ).all():
            assert attachment.message_id is not None
            images[attachment.message_id].append(attachment_view(attachment))
    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "id": row.id,
                "role": "user" if row.role is MessageRole.USER else "assistant",
                "agent_id": row.agent_id,
                "content": row.content,
                "created_at": row.created_at,
                "change_set_id": str(row.change_set_id) if row.change_set_id else None,
                "attachments": images.get(row.id, []),
                "kind": row.kind,  # briefing / checkin / followup: written by the scheduler
            }
            for row in rows
            if row.role in (MessageRole.USER, MessageRole.ASSISTANT)
        ],
        "change_sets": change_sets,
    }
