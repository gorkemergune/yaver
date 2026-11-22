"""👎 "Hatalı": the user marks an answer as wrong (web chat, desktop mini chat).

POST /api/bug-reports {message_id?, note, source}: the server fills in the rest from the
stored answer - the user's message before it, who answered, the tools run and their errors,
the routing - and the log lines of those seconds (app.core.recent_logs). A failed answer
that was never stored is reported with the texts the client still has.
GET /api/bug-reports: the list (reports tab); scripts/export-bugs.ps1 reads the table.
"""

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import recent_logs
from app.db.models import BugReport, Message
from app.db.models.enums import MessageRole
from app.db.session import get_session

router = APIRouter(tags=["bugs"])
LOG_WINDOW = dt.timedelta(seconds=5)
MAX_WAIT = dt.timedelta(minutes=10)  # an answer's log lines: at most this long


class BugReportIn(BaseModel):
    message_id: int | None = None
    note: str = Field("", max_length=2000)
    source: Literal["web", "desktop"] = "web"
    # only when there is no stored answer (a stream that failed): what the client shows
    user_text: str = Field("", max_length=4000)
    reply_text: str = Field("", max_length=4000)
    error: str | None = Field(None, max_length=200)


def view(report: BugReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "created_at": report.created_at,
        "status": report.status,
        "source": report.source,
        "agent_id": report.agent_id,
        "message_id": report.message_id,
        "conversation_id": report.conversation_id,
        "user_text": report.user_text,
        "reply_text": report.reply_text,
        "note": report.note,
        "tools": report.tools,
        "intents": report.intents,
        "errors": report.errors,
        "log_summary": report.log_summary,
    }


async def _user_message_before(session: AsyncSession, answer: Message) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(
            Message.conversation_id == answer.conversation_id,
            Message.role == MessageRole.USER,
            Message.id < answer.id,
        )
        .order_by(Message.id.desc())
        .limit(1)
    )


@router.post("/bug-reports", status_code=201)
async def report_bug(
    body: BugReportIn, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    report = BugReport(note=body.note.strip(), source=body.source)
    start, end = now - MAX_WAIT, now
    if body.message_id is not None:
        answer = await session.get(Message, body.message_id)
        if answer is None or answer.role is not MessageRole.ASSISTANT:
            raise HTTPException(status_code=404, detail="no such answer")
        asked = await _user_message_before(session, answer)
        meta = answer.meta or {}
        report.message_id = answer.id
        report.conversation_id = answer.conversation_id
        report.agent_id = answer.agent_id
        report.reply_text = answer.content
        report.user_text = asked.content if asked is not None else ""
        report.tools = [
            {k: step.get(k) for k in ("agent_id", "tool", "error", "area", "reason") if step.get(k)}
            for step in meta.get("trace", [])
        ]
        report.intents = list(meta.get("intents", []))
        report.errors = [str(s["error"]) for s in meta.get("trace", []) if s.get("error")]
        # created_at is when the request began (its transaction): the answer's log lines
        # run from there until the next message of the chat (at most MAX_WAIT, not later
        # than now)
        start = (asked.created_at if asked is not None else answer.created_at) - LOG_WINDOW
        following = await session.scalar(
            select(Message.created_at)
            .where(Message.conversation_id == answer.conversation_id, Message.id > answer.id)
            .order_by(Message.id)
            .limit(1)
        )
        end = min(now, following or now, start + MAX_WAIT + LOG_WINDOW)
    else:
        report.user_text = body.user_text
        report.reply_text = body.reply_text
        if body.error:
            report.errors = [body.error]
    report.log_summary = "\n".join(line.render() for line in recent_logs.between(start, end))
    session.add(report)
    await session.commit()
    return view(report)


@router.get("/bug-reports")
async def bug_reports(
    status: Literal["open", "closed", "all"] = "open",
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    statement = select(BugReport).order_by(BugReport.id.desc()).limit(limit)
    if status != "all":
        statement = statement.where(BugReport.status == status)
    rows = (await session.scalars(statement)).all()
    total = await session.scalar(
        select(func.count()).select_from(BugReport).where(BugReport.status == "open")
    )
    return {"open": total or 0, "reports": [view(r) for r in rows]}
