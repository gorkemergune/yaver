"""Office rituals (O4): the morning standup (inside the briefing job), the day report and
the Sunday weekly meeting (around the weekly plan). The meeting is real: everyone taking
part is in the `meeting` state while the reports are written.

Each employee's standup line is one short fast-tier call on its own budget (agent_id), from
facts the code gathers (notebook, inbox, today's shift jobs); with no facts, or over budget,
the line is written by code. The day report is one fast-tier call for Yaver, with a code
fallback.
"""

import datetime as dt
import logging
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.team import Member, Team, TeamConfig
from app.db.models import EmployeeNote, EmployeeTask
from app.db.models.enums import Activity
from app.llm.types import ChatMessage, LLMRequest
from app.office.budget import day_start
from app.office.shift_jobs import shift_plans
from app.office.state import Office

logger = logging.getLogger(__name__)
NOTES_PER_EMPLOYEE = 3
STANDUP_PROMPT = (
    "Sen {name}, Yaver ofisinde {role} çalışanısın ({domain}). Sabah standup'ında 1-2 kısa "
    "cümleyle, birinci tekil şahısla, Türkçe rapor ver: son yaptığın, bugün yapacağın, "
    "bekleyen bir şey varsa o. Yalnızca verilen bilgileri kullan, hiçbir şey uydurma; "
    "liste ya da başlık yazma."
)
DAY_REPORT_PROMPT = (
    "Sen Yaver'sin, ofisin genel müdürü. Aşağıdaki gün kayıtlarından kullanıcıya kısa bir "
    "gün sonu raporu yaz: her çalışan için en fazla bir satır, '- **İsim**: ...' biçiminde, "
    "Türkçe, kullanıcıya 'sen' diye hitap ederek. Yalnızca kayıtlardaki bilgileri kullan, "
    "uydurma; kaydı olmayan çalışanı yazma."
)
QUIET = "Yeni bir şey yok; bugün planlı bir işim de yok."
OVER_BUDGET = "Günlük bütçem doldu; bugün mesai işi yapmıyorum."


@asynccontextmanager
async def meeting(
    office: Office | None, host: str, guests: Sequence[str], task: str
) -> AsyncIterator[None]:
    """Everyone in the meeting room while the block runs: the guests meet the host."""
    if office is None or not await office.ensure_ready():
        yield
        return
    people = [i for i in dict.fromkeys([host, *guests]) if office.employee_id(i)]
    for employee in people:
        office.acquire(employee)
    try:
        try:
            for employee in people:
                await office.set_state(
                    employee,
                    Activity.MEETING,
                    task=task,
                    meeting_with=None if employee == host else host,
                )
        except Exception:
            logger.exception("Office state update failed")
        yield
    finally:
        for employee in people:
            try:
                await office.release(employee)
            except Exception:
                logger.exception("Office state update failed")


@dataclass(frozen=True, slots=True)
class Facts:
    notes: list[str]
    tasks: list[str]
    jobs: list[str]

    def empty(self) -> bool:
        return not (self.notes or self.tasks or self.jobs)

    def text(self) -> str:
        parts = []
        if self.notes:
            parts.append("Defterimdeki son notlar: " + " | ".join(self.notes))
        if self.tasks:
            parts.append("Son işlerim: " + " | ".join(self.tasks))
        if self.jobs:
            parts.append("Bugünkü mesai işlerim: " + " | ".join(self.jobs))
        return "\n".join(parts)


async def facts_of(
    session: AsyncSession, member: Member, now: dt.datetime, tz: ZoneInfo, config: TeamConfig
) -> Facts:
    since = day_start(now, tz) - dt.timedelta(days=1)  # yesterday and today
    notes = (
        await session.scalars(
            select(EmployeeNote.content)
            .where(EmployeeNote.employee_id == member.id, EmployeeNote.created_at >= since)
            .order_by(EmployeeNote.id.desc())
            .limit(NOTES_PER_EMPLOYEE)
        )
    ).all()
    tasks = (
        await session.scalars(
            select(EmployeeTask)
            .where(EmployeeTask.employee_id == member.id, EmployeeTask.created_at >= since)
            .order_by(EmployeeTask.id.desc())
            .limit(NOTES_PER_EMPLOYEE)
        )
    ).all()
    weekday = now.astimezone(tz).weekday()
    jobs = [
        f"{p.job.at} {p.title}"
        for p in shift_plans(config)
        if p.employee_id == member.id and p.job.weekday in (None, weekday)
    ]
    return Facts(
        list(notes),
        [f"{t.instruction[:80]} ({t.status.value})" for t in tasks],
        jobs,
    )


def _line(text: str) -> str:
    """One or two plain sentences: no list markers, no line breaks, no name prefix."""
    line = " ".join(text.split())
    line = re.sub(r"^[-*•]\s*", "", line)
    return line[:300]


async def standup_reports(
    session: AsyncSession,
    team: Team,
    llm: Any,
    now: dt.datetime,
    tz: ZoneInfo,
    config: TeamConfig,
    office: Office | None = None,
) -> list[tuple[str, str]]:
    """(name, line) for every employee, in team order."""
    lines: list[tuple[str, str]] = []
    for member in team.agents:
        facts = await facts_of(session, member, now, tz, config)
        if facts.empty():
            lines.append((member.name, QUIET))
            continue
        if office is not None and await office.over_budget(member.id):
            lines.append((member.name, OVER_BUDGET))
            continue
        fallback = facts.notes[0] if facts.notes else (facts.tasks or facts.jobs)[0]
        try:
            response = await llm.complete(
                LLMRequest(
                    system=STANDUP_PROMPT.format(
                        name=member.name, role=member.role or "ekip", domain=member.domain
                    ),
                    messages=[ChatMessage("user", facts.text())],
                    max_tokens=200,
                    cache=False,
                ),
                purpose="standup",
                tier="fast",
                agent_id=member.id,
                model=member.model,
            )
            line = _line(response.text) or fallback
        except Exception:
            logger.exception("Standup line of %s failed", member.id)
            line = fallback
        lines.append((member.name, line))
    return lines


def standup_section(lines: list[tuple[str, str]]) -> str:
    return "**Standup**\n" + "\n".join(f"- **{name}**: {line}" for name, line in lines)


async def day_report(
    session: AsyncSession, team: Team, llm: Any, now: dt.datetime, tz: ZoneInfo
) -> str | None:
    """Today's notebooks and inboxes, summed up by Yaver; None when nothing happened."""
    since = day_start(now, tz)
    names = {m.id: m.name for m in (team.coordinator, *team.agents)}
    notes = (
        await session.scalars(
            select(EmployeeNote).where(EmployeeNote.created_at >= since).order_by(EmployeeNote.id)
        )
    ).all()
    tasks = (
        await session.scalars(
            select(EmployeeTask).where(EmployeeTask.created_at >= since).order_by(EmployeeTask.id)
        )
    ).all()
    records: dict[str, list[str]] = {}
    for note in notes:
        records.setdefault(note.employee_id, []).append(f"not: {note.content}")
    for task in tasks:
        if task.employee_id == team.coordinator.id:
            continue  # Yaver's own inbox is every message: the others say what was done
        result = f" -> {task.result[:120]}" if task.result else ""
        records.setdefault(task.employee_id, []).append(f"iş: {task.instruction[:100]}{result}")
    records = {k: v for k, v in records.items() if k in names}
    if not records:
        return None
    body = "\n".join(f"{names[k]}: " + " | ".join(v[:6]) for k, v in records.items())
    title = f"**Gün sonu raporu** · {now.astimezone(tz):%d.%m}"
    try:
        response = await llm.complete(
            LLMRequest(
                system=DAY_REPORT_PROMPT,
                messages=[ChatMessage("user", body)],
                max_tokens=600,
                cache=False,
            ),
            purpose="day_report",
            tier="fast",
            agent_id=team.coordinator.id,
            model=team.coordinator.model,
        )
        summary = response.text.strip()
    except Exception:
        logger.exception("Day report summary failed")
        summary = ""
    if not summary:
        summary = "\n".join(
            f"- **{names[k]}**: {v[0].split(': ', 1)[-1]}" for k, v in records.items()
        )
    return f"{title}\n{summary}"
