"""What Yaver says on its own: the morning briefing, the evening check-in, follow-up
questions. Built from the plan with templates (no LLM call: free, instant, works offline
and is never rate-limited). Each section speaks for the yaver of its area."""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intent_map import followup_owner
from app.agent.team import Team
from app.core.time_resolver import MONTH_NAMES_TR, WEEKDAY_NAMES_TR
from app.db.models import Course, Event, Followup
from app.db.models.enums import EventKind, FollowupStatus, TaskStatus
from app.services.attendance import course_summary
from app.services.schedule import DayPlan, PlanItem, get_day_plan
from app.services.screen_time import checkin_line, day_summary

# Which yaver speaks for which kind of item (ids of the default / example team).
ACADEMIC_KINDS = frozenset({"class", "lab", "exam", "quiz", "makeup"})
SPORT_KINDS = frozenset({"sport"})
EXAM_KINDS = frozenset({EventKind.EXAM, EventKind.QUIZ})
EXAM_HORIZON_DAYS = 14
FOLLOWUP_TOPICS = {"career": "Başvurular", "startup": "Startup"}  # else "Takip"
ABSENCE_WARNING_HOURS = 2  # "limitine 2 saat kaldı"


def day_name(day: dt.date) -> str:
    return f"{day.day} {MONTH_NAMES_TR[day.month - 1]} {WEEKDAY_NAMES_TR[day.weekday()]}"


def _time(item: PlanItem) -> str:
    if item.all_day:
        return "tüm gün"
    end = f"-{item.end:%H:%M}" if item.end else ""
    return f"{item.start:%H:%M}{end}"


def _item(item: PlanItem) -> str:
    place = f" ({item.location})" if item.location else ""
    return f"{_time(item)} {item.title}{place}"


@dataclass(slots=True)
class Voice:
    """Section labels: the yaver's name ("Friday · Dersler") or none (single voice)."""

    team: Team
    sections: bool

    def label(self, agent_id: str, topic: str) -> str:
        member = self.team.get(agent_id)
        if self.sections and member is not None:
            return f"**{member.name}** · {topic}"
        return f"**{topic}**"


def _split(plan: DayPlan) -> tuple[list[PlanItem], list[PlanItem], list[PlanItem]]:
    classes = [i for i in plan.items if i.kind in ACADEMIC_KINDS]
    sport = [i for i in plan.items if i.kind in SPORT_KINDS]
    agenda = [i for i in plan.items if i.kind not in ACADEMIC_KINDS | SPORT_KINDS]
    return classes, agenda, sport


async def build_briefing(
    session: AsyncSession,
    today: dt.date,
    tz: ZoneInfo,
    voice: Voice,
    user_name: str,
    unanswered_checkin: bool = False,
) -> str:
    plan = await get_day_plan(session, today, tz)
    classes, agenda, sport = _split(plan)
    hello = f"Günaydın{', ' + user_name if user_name else ''}! Bugün {day_name(today)}."
    lines = [hello]
    if plan.holidays:
        lines.append(f"Tatil: {', '.join(plan.holidays)} 🎉")
    if classes:
        lines.append(
            f"- {voice.label('academic', 'Dersler')}: " + "; ".join(_item(i) for i in classes)
        )
    lines += [f"- {line}" for line in await _exam_countdown(session, today, tz, voice)]
    lines += [f"- {line}" for line in await _absence_warnings(session, voice)]
    if agenda:
        lines.append(f"- {voice.label('agenda', 'Ajanda')}: " + "; ".join(_item(i) for i in agenda))
    if sport:
        lines.append(
            f"- {voice.label('discipline', 'Spor')}: " + "; ".join(_item(i) for i in sport)
        )
    todo = [t.title for t in [*plan.tasks, *plan.week_tasks] if t.status is TaskStatus.TODO]
    if todo:
        lines.append("- **Görevler**: " + ", ".join(todo))
    if plan.cancelled:
        lines.append(
            "- İptal: " + ", ".join(f"{c.title} ({c.start:%H:%M})" for c in plan.cancelled)
        )
    if len(lines) == 1:
        lines.append("Bugün için planında bir şey yok; güzel bir gün geçir.")
    if unanswered_checkin:
        lines.append(
            "Dünkü akşam check-in'ine cevap vermedin; istersen şimdi yaz (ör. \"dün spor hariç "
            'hepsi tamam").'
        )
    return "\n".join(lines)


async def _exam_countdown(
    session: AsyncSession, today: dt.date, tz: ZoneInfo, voice: Voice
) -> list[str]:
    start = dt.datetime.combine(today, dt.time(), tzinfo=tz)
    end = start + dt.timedelta(days=EXAM_HORIZON_DAYS + 1)
    exams = (
        await session.scalars(
            select(Event)
            .where(Event.kind.in_(EXAM_KINDS), Event.start_at >= start, Event.start_at < end)
            .order_by(Event.start_at)
        )
    ).all()
    lines = []
    for exam in exams:
        local = exam.start_at.astimezone(tz)
        days = (local.date() - today).days
        when = "bugün" if days == 0 else "yarın" if days == 1 else f"{days} gün sonra"
        lines.append(
            f"{voice.label('academic', 'Sınav')}: {exam.title} {when} "
            f"({day_name(local.date())}{'' if exam.all_day else f' {local:%H:%M}'})"
        )
    return lines


async def _absence_warnings(session: AsyncSession, voice: Voice) -> list[str]:
    lines = []
    for course in (await session.scalars(select(Course).order_by(Course.code))).all():
        summary = await course_summary(session, course)
        remaining = summary.get("remaining_hours")
        if remaining is None or summary["absent_hours"] == 0:
            continue
        if remaining < 0:
            lines.append(f"{voice.label('academic', 'Devamsızlık')}: {course.code} limiti aşıldı")
        elif remaining <= ABSENCE_WARNING_HOURS:
            lines.append(
                f"{voice.label('academic', 'Devamsızlık')}: {course.code} için "
                f"{remaining} saat hakkın kaldı"
            )
    return lines


async def build_checkin(
    session: AsyncSession, today: dt.date, tz: ZoneInfo, voice: Voice
) -> str | None:
    """None when there is nothing to check (no class, sport or task today)."""
    plan = await get_day_plan(session, today, tz)
    classes, _, sport = _split(plan)
    classes = [i for i in classes if i.kind in ("class", "lab", "makeup")]
    tasks = [t.title for t in plan.tasks if t.status is TaskStatus.TODO]
    if not (classes or sport or tasks):
        return None
    lines = [f"Akşam check-in 🌙 Bugün ({day_name(today)}):"]
    if classes:
        lines.append(
            f"- {voice.label('academic', 'Dersler')}: "
            + "; ".join(_item(i) for i in classes)
            + " - katıldı sayıyorum, gitmediğin varsa yaz."
        )
    if sport:
        lines.append(
            f"- {voice.label('discipline', 'Spor')}: "
            + "; ".join(_item(i) for i in sport)
            + " - yaptın mı?"
        )
    if tasks:
        lines.append("- **Görevler**: " + ", ".join(tasks) + " - bitti mi?")
    screen = await day_summary(session, today)
    screen_text = checkin_line(screen) if screen else None
    if screen_text:
        lines.append(f"- {voice.label('discipline', 'Ekran')}: {screen_text}.")
    lines.append(
        'Hepsi tamamsa "✓ Hepsi tamam" demen yeter; değilse tek cümleyle yaz '
        '("spor hariç hepsi tamam").'
    )
    return "\n".join(lines)


def followup_due(followup: Followup, now: dt.datetime, today: dt.date) -> bool:
    if followup.status is not FollowupStatus.WAITING:
        return False
    if followup.next_check_at is not None and followup.next_check_at > now:
        return False
    if followup.check_on is not None and followup.check_rule.value == "on_date":
        return today >= followup.check_on
    return True


def next_check(followup: Followup, today: dt.date, at: dt.time, tz: ZoneInfo) -> dt.datetime:
    """When to ask again: tomorrow (daily, and every day after an on_date), or in N days."""
    days = followup.every_n_days if followup.check_rule.value == "every_n_days" else 1
    return dt.datetime.combine(today + dt.timedelta(days=days or 1), at, tzinfo=tz)


async def build_followups(
    session: AsyncSession, now: dt.datetime, today: dt.date, at: dt.time, tz: ZoneInfo, voice: Voice
) -> str | None:
    """Asks about due follow-ups and moves their next check; None when nothing is due."""
    rows = (
        await session.scalars(
            select(Followup).where(Followup.status == FollowupStatus.WAITING).order_by(Followup.id)
        )
    ).all()
    due = [f for f in rows if followup_due(f, now, today)]
    if not due:
        return None
    for followup in due:
        followup.next_check_at = next_check(followup, today, at, tz)
    # each owner asks about its own: Mentor the applications, Chrono the rest
    by_owner: dict[str, list[Followup]] = {}
    for followup in due:
        by_owner.setdefault(followup_owner(followup.owner_id), []).append(followup)
    lines: list[str] = []
    for owner, items in by_owner.items():
        lines.append(f"{voice.label(owner, FOLLOWUP_TOPICS.get(owner, 'Takip'))}: haber var mı?")
        lines += [f"- {f.title}" for f in items]
    lines.append('Cevap verirsen işlerim ("hackathon kabul geldi", "henüz yok").')
    return "\n".join(lines)
