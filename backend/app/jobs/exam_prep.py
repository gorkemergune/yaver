"""Exam preparation: a week before an exam Friday proposes a review plan - the syllabus
topics since the previous exam of the course (all of them for a final), the uploaded notes
of those weeks, and a free slot on each day before the exam. Built in code (no LLM: the
facts are all in the database). A proposal like the weekly plan: tasks after "evet"."""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.localtime import elapsed, local_datetime
from app.core.time_resolver import week_start
from app.db.models import Course, CourseMaterial, Event, Proposal, SyllabusWeek
from app.db.models.enums import EventKind, ProposalKind
from app.jobs.content import Voice, day_name
from app.jobs.weekly_plan import tasks_table
from app.services.schedule import get_day_plan
from app.services.weeks import week_facts

LEAD_DAYS = 7  # proposed this many days before (or later, if the exam was added late)
MIN_LEAD_DAYS = 2  # closer than this: no plan any more
DAY_START, DAY_END = dt.time(9, 0), dt.time(22, 0)
SLOT = dt.timedelta(minutes=90)
MIN_SLOT = dt.timedelta(minutes=60)
EVENING = dt.time(17, 0)  # free time after this is preferred (classes are done)
SOURCE = "[sınav hazırlığı event #{id}]"
TOPIC_CHARS = 110
NO_SYLLABUS_DAYS = 2  # without topics: two review sessions + the last-day review


def topics_of(notes: str | None) -> list[str]:
    """The topics add_event wrote into the exam's notes ("Konular: a, b")."""
    for line in (notes or "").splitlines():
        if line.startswith("Konular: "):
            return [t.strip() for t in line.removeprefix("Konular: ").split(",") if t.strip()]
    return []


@dataclass(slots=True)
class Slot:
    start: dt.datetime
    end: dt.datetime

    def label(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


Taken = dict[dt.date, list[tuple[dt.datetime, dt.datetime]]]


async def free_slot(
    session: AsyncSession, day: dt.date, tz: ZoneInfo, taken: Taken | None = None
) -> Slot | None:
    """A study slot on the day: the first evening gap of 90 min, else the longest gap
    (at least 60 min) between DAY_START and DAY_END. `taken`: slots already given to
    another exam's review in this run (three exams in a week must not share an hour);
    the chosen slot is added to it."""
    plan = await get_day_plan(session, day, tz)
    busy = sorted(
        [
            (item.start, item.end or item.start)
            for item in plan.items
            if not item.all_day and item.kind not in ("deadline",)
        ]
        + (taken.get(day, []) if taken is not None else [])
    )
    cursor = local_datetime(day, DAY_START, tz)
    end_of_day = local_datetime(day, DAY_END, tz)
    gaps: list[Slot] = []
    for start, end in busy:
        if start > cursor:
            gaps.append(Slot(cursor, min(start, end_of_day)))
        cursor = max(cursor, end)
    if cursor < end_of_day:
        gaps.append(Slot(cursor, end_of_day))
    gaps = [g for g in gaps if elapsed(g.start, g.end) >= MIN_SLOT]
    if not gaps:
        return None
    chosen: Slot | None = None
    evening = [g for g in gaps if g.start.time() >= EVENING or g.end.time() > EVENING]
    for gap in evening:
        start = max(gap.start, local_datetime(day, EVENING, tz))
        if elapsed(start, gap.end) >= SLOT:
            chosen = Slot(start, start + SLOT)
            break
    if chosen is None:
        best = max(gaps, key=lambda g: elapsed(g.start, g.end))
        chosen = Slot(best.start, min(best.end, best.start + SLOT))
    if taken is not None:
        taken.setdefault(day, []).append((chosen.start, chosen.end))
    return chosen


def is_final(exam: Event) -> bool:
    return "final" in exam.title.lower()


async def covered_weeks(
    session: AsyncSession, exam: Event, course: Course, tz: ZoneInfo
) -> list[SyllabusWeek]:
    """Syllabus weeks the exam covers: after the course's previous exam, up to the exam's
    own week (exam weeks themselves left out); a final covers everything."""
    weeks = (
        await session.scalars(
            select(SyllabusWeek)
            .where(SyllabusWeek.course_id == course.id)
            .order_by(SyllabusWeek.week_no)
        )
    ).all()
    teaching = [
        w for w in weeks if "sınav" not in w.topics.lower() and "exam" not in w.topics.lower()
    ]
    exam_week = (await week_facts(session, exam.start_at.astimezone(tz).date(), tz)).week_no
    if is_final(exam) or exam_week is None:
        return list(teaching)
    previous = await session.scalar(
        select(Event)
        .where(
            Event.course_id == course.id,
            Event.kind == EventKind.EXAM,
            Event.start_at < exam.start_at,
        )
        .order_by(Event.start_at.desc())
        .limit(1)
    )
    after = 0
    if previous is not None:
        after = (
            await week_facts(session, previous.start_at.astimezone(tz).date(), tz)
        ).week_no or 0
    return [w for w in teaching if after < w.week_no < exam_week] or list(teaching)


def _short(text: str) -> str:
    return text if len(text) <= TOPIC_CHARS else text[: TOPIC_CHARS - 1].rstrip() + "…"


async def plan_exam(
    session: AsyncSession, exam: Event, today: dt.date, tz: ZoneInfo, taken: Taken | None = None
) -> tuple[list[dict[str, str | None]], list[str], list[str]]:
    """(task entries, topic lines, note titles) for one exam."""
    course = await session.get(Course, exam.course_id) if exam.course_id else None
    code = course.code if course else exam.title.split()[0]
    weeks = await covered_weeks(session, exam, course, tz) if course else []
    notes: list[str] = []
    if course:
        materials = (
            await session.scalars(
                select(CourseMaterial).where(
                    CourseMaterial.course_id == course.id,
                    CourseMaterial.indexed_at.is_not(None),
                    CourseMaterial.kind != "syllabus",
                )
            )
        ).all()
        wanted = {w.week_no for w in weeks}
        notes = [m.title for m in materials if m.week_no is None or m.week_no in wanted]
    exam_day = exam.start_at.astimezone(tz).date()
    days = [
        exam_day - dt.timedelta(days=n)
        for n in range(LEAD_DAYS - 1, 0, -1)
        if exam_day - dt.timedelta(days=n) > today
    ]
    study_days, review_day = days[:-1], days[-1:] if days else []
    told = topics_of(exam.notes) if not weeks else []  # the topics the user named
    if told:  # one session per topic group, as many days as there are topics
        study_days = study_days[-min(len(told), len(study_days)) :] if study_days else []
    elif not weeks:  # no syllabus: a couple of sessions, not a task every day
        study_days = study_days[-NO_SYLLABUS_DAYS:]
    why = f"{exam.title}, {day_name(exam_day)}"
    entries: list[dict[str, str | None]] = []
    # the weeks spread over the study days, in order
    groups: list[list[SyllabusWeek]] = [[] for _ in study_days]
    for index, week in enumerate(weeks):
        if groups:
            groups[index * len(groups) // max(len(weeks), 1)].append(week)
    told_groups: list[list[str]] = [[] for _ in study_days]
    for index, topic in enumerate(told):
        if told_groups:
            told_groups[index * len(told_groups) // len(told)].append(topic)
    for day, group, told_group in zip(study_days, groups, told_groups, strict=True):
        if weeks and not group:
            continue
        slot = await free_slot(session, day, tz, taken)
        when = f" {slot.label()}" if slot else ""
        what = (
            "; ".join(f"h{w.week_no} {w.topics}" for w in group)
            if group
            else ", ".join(told_group)
            if told_group
            else "notları gözden geçir"
        )
        entries.append(
            {
                "title": _short(f"{code} tekrar{when}: {what}"),
                "date": day.isoformat(),
                "why": why,
                "week_start": week_start(day).isoformat(),
            }
        )
    for day in review_day:
        slot = await free_slot(session, day, tz, taken)
        when = f" {slot.label()}" if slot else ""
        entries.append(
            {
                "title": _short(
                    f"{code} genel tekrar{when}: "
                    + (f"{', '.join(told)} + soru çözümü" if told else "özet + soru çözümü")
                ),
                "date": day.isoformat(),
                "why": why,
                "week_start": week_start(day).isoformat(),
            }
        )
    topics = [f"{w.week_no}. hafta: {w.topics}" for w in weeks] or told
    return entries, topics, notes


async def draft_exam_prep(
    session: AsyncSession, today: dt.date, tz: ZoneInfo, voice: Voice
) -> tuple[str, str] | None:
    """(message, context) for the chat: one plan per exam 2-7 days away that has none yet."""
    start = local_datetime(today + dt.timedelta(days=MIN_LEAD_DAYS), dt.time(), tz)
    end = local_datetime(today + dt.timedelta(days=LEAD_DAYS + 1), dt.time(), tz)
    exams = (
        await session.scalars(
            select(Event)
            .where(Event.kind == EventKind.EXAM, Event.start_at >= start, Event.start_at < end)
            .order_by(Event.start_at)
        )
    ).all()
    sections, contexts = [], []
    taken: Taken = {}
    for exam in exams:
        source = SOURCE.format(id=exam.id)
        if await session.scalar(select(Proposal.id).where(Proposal.source_text == source)):
            continue  # already proposed (whatever the answer was)
        entries, topics, notes = await plan_exam(session, exam, today, tz, taken)
        if not entries:
            continue
        proposal = Proposal(
            kind=ProposalKind.TASKS, source_text=source, entries=entries, parsed_by="code"
        )
        session.add(proposal)
        await session.flush()
        exam_day = exam.start_at.astimezone(tz).date()
        days_left = (exam_day - today).days
        hour = "" if exam.all_day else exam.start_at.astimezone(tz).strftime(" %H:%M")
        lines = [
            f"{voice.label('academic', 'Sınav hazırlığı')} 📚 {exam.title}: {days_left} gün "
            f"kaldı ({day_name(exam_day)}{hour})."
        ]
        if topics and topics_of(exam.notes) == topics:
            lines.append("Konular (senin söylediğin): " + ", ".join(topics))
        elif topics:
            lines.append("Konular (syllabus): " + "; ".join(topics))
        else:
            lines.append("Syllabus yok; konuları bilmiyorum, tekrar günlerini ayırdım.")
        if notes:
            lines.append("Notların: " + ", ".join(notes))
        lines.append("")
        lines.append(tasks_table(entries))
        sections.append("\n".join(lines))
        contexts.append(
            f"[Sınav hazırlığı taslağı ({exam.title}) -> öneri #{proposal.id}, henüz kaydedilmedi]"
        )
    if not sections:
        return None
    message = (
        "\n\n".join(sections)
        + '\n\nUygun mu? "Evet" dersen görevlere yazarım; saat ya da gün değiştirmek '
        "istersen söylemen yeter."
    )
    return message, "\n".join(contexts)
