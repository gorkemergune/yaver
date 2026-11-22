"""The reports tab (read only): a local day or week of the office.

GET /api/reports?period=day|week&date=YYYY-MM-DD
- per employee: requests (from the user / delegated by Yaver / its shift jobs), LLM cost,
  failed requests and handoffs (with their reasons), tool errors
- the routing of each answer: the user's message -> intents -> who got it (messages.meta)
- the requests that failed or were handed back, with why
- open bug reports (👎 "Hatalı")
"""

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.team import Team, get_team
from app.config import Settings, get_settings
from app.core.localtime import local_datetime
from app.db.models import BugReport, EmployeeTask, LlmUsage, Message
from app.db.models.enums import EmployeeTaskStatus, MessageRole, TaskOrigin
from app.db.session import get_session

router = APIRouter(tags=["reports"])
MAX_ANSWERS = 200  # routing rows in one report


def window(period: str, day: dt.date) -> tuple[dt.date, dt.date]:
    """[first, last] local days: the day, or its Monday..Sunday."""
    if period == "day":
        return day, day
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=6)


@router.get("/reports")
async def reports(
    period: Literal["day", "week"] = "day",
    date: dt.date | None = Query(None, description="YYYY-MM-DD; default today"),
    session: AsyncSession = Depends(get_session),
    team: Team = Depends(get_team),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    tz = settings.tz
    today = dt.datetime.now(tz).date()
    first, last = window(period, date or today)
    start = local_datetime(first, dt.time(), tz)
    end = local_datetime(last + dt.timedelta(days=1), dt.time(), tz)
    names = {m.id: m.name for m in (team.coordinator, *team.agents)}

    employees: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "requests": 0,
            "delegated": 0,
            "shift": 0,
            "failed": 0,
            "handoffs": 0,
            "tool_errors": 0,
            "cost_usd": Decimal(0),
        }
    )
    tasks = (
        await session.scalars(
            select(EmployeeTask)
            .where(EmployeeTask.created_at >= start, EmployeeTask.created_at < end)
            .order_by(EmployeeTask.id)
        )
    ).all()
    problems: list[dict[str, Any]] = []
    for task in tasks:
        row = employees[task.employee_id]
        key = {TaskOrigin.USER: "requests", TaskOrigin.YAVER: "delegated"}.get(task.source, "shift")
        row[key] += 1
        if task.status is EmployeeTaskStatus.FAILED:
            row["failed"] += 1
            problems.append(
                {
                    "at": task.created_at,
                    "kind": "failed",
                    "agent_id": task.employee_id,
                    "text": task.instruction[:300],
                    "reason": (task.result or "")[:300],
                }
            )

    for agent_id, cost in (
        await session.execute(
            select(LlmUsage.agent_id, func.sum(LlmUsage.cost_usd))
            .where(LlmUsage.created_at >= start, LlmUsage.created_at < end)
            .group_by(LlmUsage.agent_id)
        )
    ).all():
        employees[agent_id or "yaver"]["cost_usd"] += cost or Decimal(0)

    answers = (
        await session.scalars(
            select(Message)
            .where(
                Message.role == MessageRole.ASSISTANT,
                Message.meta.is_not(None),
                Message.created_at >= start,
                Message.created_at < end,
            )
            .order_by(Message.id.desc())
            .limit(MAX_ANSWERS)
        )
    ).all()
    asked = await _questions(session, answers)
    routing = []
    for answer in answers:
        meta = answer.meta or {}
        text = asked.get(answer.id, "")
        for step in meta.get("trace", []):
            if step.get("error"):
                employees[step.get("agent_id") or "yaver"]["tool_errors"] += 1
        for handoff in meta.get("handoffs", []):
            employees[handoff.get("agent_id") or "?"]["handoffs"] += 1
            problems.append(
                {
                    "at": answer.created_at,
                    "kind": "handoff",
                    "agent_id": handoff.get("agent_id"),
                    "text": text[:300],
                    "reason": handoff.get("reason") or "",
                    "area": handoff.get("area") or "",
                    "in_words": bool(handoff.get("in_words")),
                }
            )
        routing.append(
            {
                "at": answer.created_at,
                "message_id": answer.id,
                "text": text[:300],
                "intents": meta.get("intents", []),
                "speaker": meta.get("speaker") or answer.agent_id,
                "helpers": meta.get("helpers", []),
                "handoffs": len(meta.get("handoffs", [])),
                "errors": meta.get("errors", 0),
                "cost_usd": meta.get("cost_usd"),
            }
        )

    bugs = (
        await session.scalars(
            select(BugReport)
            .where(BugReport.status == "open")
            .order_by(BugReport.id.desc())
            .limit(20)
        )
    ).all()
    open_bugs = await session.scalar(
        select(func.count()).select_from(BugReport).where(BugReport.status == "open")
    )
    order = [team.coordinator.id, *(a.id for a in team.agents)]
    return {
        "period": period,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "employees": [
            {"id": agent_id, "name": names.get(agent_id, agent_id), **_money(employees[agent_id])}
            for agent_id in sorted(
                set(order) | set(employees), key=lambda a: (order.index(a) if a in order else 99, a)
            )
        ],
        "totals": _money(
            {
                key: sum(
                    (e[key] for e in employees.values()), Decimal(0) if key == "cost_usd" else 0
                )
                for key in (
                    "requests",
                    "delegated",
                    "shift",
                    "failed",
                    "handoffs",
                    "tool_errors",
                    "cost_usd",
                )
            }
        ),
        "routing": routing,
        "problems": sorted(problems, key=lambda p: p["at"], reverse=True),
        "bugs": {
            "open": open_bugs or 0,
            "latest": [
                {
                    "id": b.id,
                    "at": b.created_at,
                    "agent_id": b.agent_id,
                    "note": b.note,
                    "text": b.user_text[:200],
                    "source": b.source,
                }
                for b in bugs
            ],
        },
    }


def _money(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "cost_usd": str(Decimal(row["cost_usd"]).quantize(Decimal("0.0001")))}


async def _questions(session: AsyncSession, answers: list[Message] | Any) -> dict[int, str]:
    """answer id -> the user's message it answered (the last user message before it)."""
    found: dict[int, str] = {}
    by_conversation: dict[int, list[Message]] = defaultdict(list)
    for answer in answers:
        by_conversation[answer.conversation_id].append(answer)
    for conversation_id, group in by_conversation.items():
        users = (
            await session.execute(
                select(Message.id, Message.content)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == MessageRole.USER,
                    Message.id < max(a.id for a in group),
                    Message.id >= min(a.id for a in group) - 50,
                )
                .order_by(Message.id)
            )
        ).all()
        for answer in group:
            before = [content for mid, content in users if mid < answer.id]
            found[answer.id] = before[-1] if before else ""
    return found
