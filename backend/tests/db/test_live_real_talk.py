"""Live: the user's own way of writing - lower case, missing suffixes, abbreviations,
"gidicem" / "çıkcakmış", events without an hour, Medipol / Iceberg in things that are not
classes, two jobs in one message. Each case is checked against the database (which row, which
date and hour), not only who got the message. Cases A and B are the two real failures.

    docker compose exec api pytest -m live -k real_talk -s
    REAL_TALK_ROUNDS=1 REAL_TALK_ONLY=1,2 ...

Two rounds by default; prints the success rate per round and every failure; fails below
95 %. Test database only; "today" is Monday 23 Nov 2026 10:00 Istanbul (as in the
regression set, whose seed it extends with CSE 211, a course with no name: "DSA" is unknown).
"""

import datetime as dt
import os
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.intent_map import followup_owner
from app.agent.team import get_team
from app.agent.tools import run_tool
from app.config import Settings
from app.core.time_resolver import normalize
from app.db.models import Course, Event, Followup, Memory, Task
from app.db.models.enums import FollowupStatus, OverrideAction, TaskStatus
from app.llm.router import LLMRouter
from tests.db.test_agent_tools import context
from tests.db.test_live_regression import (  # noqa: F401 (router fixture)
    NOW,
    absent,
    asked,
    fresh_state,
    override,
    read_only,
    router,
    rows,
    tools,
)

pytestmark = pytest.mark.live
PASS_FLOOR = 0.95
IST = dt.timezone(dt.timedelta(hours=3))
Problem = tuple[str, str] | None
Check = Callable[[AsyncSession, list[ChatReply]], Awaitable[Problem]]

EXTRA_SEED: list[tuple[str, dict[str, Any]]] = [
    (
        "add_recurring_block",
        {
            "kind": "class",
            "title": "CSE 211",
            "course": "CSE211",
            "weekdays": ["tuesday"],
            "start_time": "10:00",
            "end_time": "12:00",
        },
    ),
]


@dataclass
class Case:
    number: int
    text: str
    check: Check
    before: str | None = None  # sent first (e.g. to leave an open question)
    answer: str | None = None  # sent only if the team asked something back
    now: dt.datetime = NOW  # Monday 23 Nov 10:00; B was written on a Saturday


def day(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


def local(event: Event) -> dt.datetime:
    return event.start_at.astimezone(IST)


def text_of(event: Event) -> str:
    return normalize(" ".join(filter(None, [event.title, event.location, event.notes])))


def event_on(
    on: str,
    *words: str,
    hours: tuple[int, int] | None = None,
    at: str | None = None,
    kinds: tuple[str, ...] = (),
) -> Check:
    """An event on that local day (any of `words` in its title / place / notes), at `at`
    or within [hours) when given; `kinds` limits its kind."""

    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        events = await rows(session, Event)
        if not events:
            return ("missing_change", f"no event; tools {tools(replies)}")
        hits = [e for e in events if not words or any(normalize(w) in text_of(e) for w in words)]
        if not hits:
            return ("wrong_args", f"{[(e.kind.value, e.title) for e in events]}")
        dated = [e for e in hits if local(e).date() == day(on)]
        if not dated:
            return ("wrong_date", f"{[local(e).isoformat() for e in hits]} != {on}")
        event = dated[0]
        if kinds and event.kind.value not in kinds:
            return ("wrong_kind", f"{event.kind.value} not in {kinds}")
        if at is not None and (event.all_day or local(event).strftime("%H:%M") != at):
            return ("wrong_time", f"{'all day' if event.all_day else local(event):%H:%M} != {at}")
        if hours is not None and (event.all_day or not hours[0] <= local(event).hour < hours[1]):
            return ("wrong_time", f"{'all day' if event.all_day else local(event)} not in {hours}")
        return None

    return check


def exam(kind: str, on: str, course: str, at: str | None = None, topic: str | None = None) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        found = [e for e in await rows(session, Event) if e.kind.value == kind]
        if not found:
            return ("missing_change", f"no {kind}; tools {tools(replies)}")
        event = found[0]
        if local(event).date() != day(on):
            return ("wrong_date", f"{local(event).date()} != {on}")
        if at is not None and (event.all_day or local(event).strftime("%H:%M") != at):
            return ("wrong_time", f"{local(event)} != {at}")
        code = await session.scalar(select(Course.code).where(Course.id == event.course_id))
        if code is None or normalize(code).replace(" ", "") != normalize(course):
            return ("wrong_course", f"course {code} != {course}")
        if topic and normalize(topic) not in normalize(event.notes or ""):
            return ("missing_topics", f"notes {event.notes!r}")
        return None

    return check


def dsa_exam(session_check: Check) -> Check:
    """B: the exam on CSE 211 with its topics, and DSA remembered as its alias."""

    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        problem = await session_check(session, replies)
        if problem is not None:
            return problem
        course = await session.scalar(select(Course).where(Course.code == "CSE211"))
        if course is None or "dsa" not in [a.casefold() for a in course.aliases]:
            return ("no_alias", f"aliases {course.aliases if course else None}")
        return None

    return check


def task(on: str | None, word: str, done: bool = False) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        found = [t for t in await rows(session, Task) if normalize(word) in normalize(t.title)]
        if not found:
            return ("missing_change", f"no task {word}; tools {tools(replies)}")
        if on is not None and found[0].date != day(on):
            return ("wrong_date", f"{found[0].date} != {on}")
        if done and found[0].status is not TaskStatus.DONE:
            return ("missing_change", f"status {found[0].status.value}")
        return None

    return check


def followup(
    word: str, status: FollowupStatus = FollowupStatus.WAITING, owner: str | None = None
) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        found = [f for f in await rows(session, Followup) if normalize(word) in normalize(f.title)]
        if not found:
            return ("missing_change", f"no follow-up {word}; tools {tools(replies)}")
        if found[0].status is not status:
            return ("wrong_status", f"{found[0].status.value} != {status.value}")
        if owner is not None and followup_owner(found[0].owner_id) != owner:
            return ("wrong_owner", f"{found[0].owner_id} != {owner}")
        return None

    return check


def remembered(word: str) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        memories = [
            m for m in await rows(session, Memory) if normalize(word) in normalize(m.content)
        ]
        if not memories:
            return ("missing_change", f"no memory; tools {tools(replies)}")
        if await rows(session, Event):
            return ("extra_change", "an event was added for a lasting fact")
        return None

    return check


def no_event_and_asked() -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        if not asked(replies[-1]):
            return ("no_question", replies[-1].reply[:120])
        return None

    return check


def both(*checks: Check) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        for one in checks:
            problem = await one(session, replies)
            if problem is not None:
                return problem
        return None

    return check


def either(first: Check, second: Check) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> Problem:
        problem = await first(session, replies)
        return None if problem is None else await second(session, replies)

    return check


MORNING, NOON, AFTERNOON, EVENING = (6, 12), (11, 14), (12, 18), (17, 23)
CANCEL, MOVE = OverrideAction.CANCEL, OverrideAction.MOVE
MOVED_LAB = dt.datetime(2026, 11, 27, 14, 0, tzinfo=IST)
SATURDAY = dt.datetime(2026, 11, 21, 7, 0, tzinfo=dt.UTC)  # 10:00 Istanbul
DSA = "pazartesi dsa sınavında linked list, stack, queue çıkcakmış"

CASES = [
    # A, B: the two real failures
    Case(
        1,
        "yarın sabah Medipoldeki kahvaltıya gidicem",
        event_on("2026-11-24", "kahvalt", hours=MORNING),
    ),
    Case(
        2,
        DSA,
        dsa_exam(exam("exam", "2026-11-23", "cse211", topic="linked list")),
        answer="cse 211",
        now=SATURDAY,  # as in real use: on a Monday "pazartesi" is today or next week
    ),
    # A after a question of Scholar: the new request is not its answer
    Case(
        3,
        "yarın sabah Medipoldeki kahvaltıya gidicem",
        event_on("2026-11-24", "kahvalt", hours=MORNING),
        before="geçen hafta bir gün ee211e gitmedim",
    ),
    # events, often without an hour
    Case(4, "perşembe 15te iceberg toplantısı var", event_on("2026-11-26", "iceberg", at="15:00")),
    Case(
        5, "cuma akşam ali ile yemeğe çıkcam", event_on("2026-11-27", "yemek", "ali", hours=EVENING)
    ),
    Case(6, "yarın öğlen dişçi randevum var", event_on("2026-11-24", "dis", hours=NOON)),
    Case(
        7, "cumartesi medipolde etkinlik var gidicem", event_on("2026-11-28", "medipol", "etkinlik")
    ),
    Case(8, "haftaya salı 14 te proje sunumu", event_on("2026-12-01", "sunum", at="14:00")),
    Case(9, "28 kasımda hackathon var tüm gün", event_on("2026-11-28", "hackathon")),
    Case(
        10,
        "çarşamba 18:30 da iceberg ekibiyle online toplantı",
        event_on("2026-11-25", "iceberg", at="18:30"),
    ),
    Case(11, "pazar sabah annemlerle kahvaltı", event_on("2026-11-29", "kahvalt", hours=MORNING)),
    Case(
        12, "medipolde akşam 7de konser var gidicem", event_on("2026-11-23", "konser", at="19:00")
    ),
    Case(
        13,
        "iceberg ofisine perşembe öğleden sonra uğrıycam",
        event_on("2026-11-26", "iceberg", hours=AFTERNOON),
    ),
    Case(
        14,
        "medipol hastanesinde yarın 11de tahlil var",
        event_on("2026-11-24", "tahlil", at="11:00"),
    ),
    Case(15, "cuma alinin doğum günü partisi var", event_on("2026-11-27", "dogum", "parti")),
    Case(16, "haftaya çarşamba kariyer fuarı var", event_on("2026-12-02", "fuar")),
    # exams and quizzes, some with topics
    Case(
        17,
        "27 kasım cuma 10da math221 vizesi var",
        exam("exam", "2026-11-27", "math221", at="10:00"),
    ),
    Case(
        18, "haftaya salı cse221 quiz var saat 10", exam("quiz", "2026-12-01", "cse221", at="10:00")
    ),
    Case(19, "ee211 finali 8 ocakta 13.30da", exam("exam", "2027-01-08", "ee211", at="13:30")),
    Case(20, "linear vizesi 4 aralıkta", exam("exam", "2026-12-04", "math221")),
    Case(
        21,
        "cse221 quizinde karnaugh map ve flip flop çıkcakmış perşembe",
        exam("quiz", "2026-11-26", "cse221", topic="karnaugh"),
    ),
    Case(
        22,
        "math221 vizesinde determinant ve eigenvalue çıkıcakmış vize 4 aralık",
        exam("exam", "2026-12-04", "math221", topic="determinant"),
    ),
    # attendance
    Case(23, "bugün linear a gitmedim", absent("MATH221", "2026-11-23")),
    Case(24, "geçen salı devre teorisine gidemedim", absent("EE211", "2026-11-17")),
    Case(25, "geçen çarşamba logic designa girmedim", absent("CSE221", "2026-11-18")),
    # class changes
    Case(26, "yarınki ee211 dersi iptal olmuş", override(CANCEL, "2026-11-24", "Devre")),
    Case(27, "çarşamba labı cuma 14-16ya almışlar", override(MOVE, "2026-11-25", "Lab", MOVED_LAB)),
    # sport
    Case(28, "bu perşembe spora gidemicem", override(CANCEL, "2026-11-26", "Spor")),
    Case(29, "yarınki sporu iptal et", override(CANCEL, "2026-11-24", "Spor")),
    # tasks
    Case(30, "yarın için sunum hazırla görevi ekle", task("2026-11-24", "sunum")),
    Case(31, "rapor yaz görevini bitirdim", task(None, "rapor", done=True)),
    Case(32, "bugün market alışverişi yapmam lazım", task("2026-11-23", "market")),
    # follow-ups
    Case(
        33,
        "iceberge staj başvurusu yaptım her gün dönüş geldi mi diye sor",
        followup("iceberg", owner="career"),  # Mentor's, not Chrono's
    ),
    Case(34, "hackathon kabul geldi", followup("hackathon", FollowupStatus.POSITIVE)),
    # a lasting fact with Medipol: no event, no class
    Case(35, "bu dönem cuma günleri medipoldeyim", remembered("medipol")),
    # questions: nothing changes
    Case(36, "yarın ne var", read_only("get_day_plan")),
    Case(37, "bu hafta neler var", either(read_only("get_week_plan"), read_only("get_day_plan"))),
    # two jobs in one message
    Case(
        38,
        "bugün linear iptal, yarın 14te iceberg toplantısı var",
        both(
            override(CANCEL, "2026-11-23", "Linear"), event_on("2026-11-24", "iceberg", at="14:00")
        ),
    ),
    Case(
        39,
        "perşembe sporu iptal et bi de cuma 10da dişçiye gidicem",
        both(override(CANCEL, "2026-11-26", "Spor"), event_on("2026-11-27", "dis", at="10:00")),
    ),
    Case(
        40,
        "pazartesi dsa sınavı var, bi de yarın sabah kahvaltıya gidicem",
        both(
            event_on("2026-11-22", "kahvalt", hours=MORNING),
            either(exam("exam", "2026-11-23", "cse211"), no_event_and_asked()),
        ),
        now=SATURDAY,
    ),
    Case(
        41,
        "yarın medipolde 9da toplantı var sonra da ee211e gidicem",
        event_on("2026-11-24", "toplant", at="09:00"),
    ),
]


async def seed(session: AsyncSession) -> None:
    await fresh_state(session)
    ctx = context(session, "academic")
    for name, args in EXTRA_SEED:
        result = await run_tool(name, args, ctx)
        assert "error" not in result, (name, result)
    await session.commit()


async def run_case(
    coordinator: Coordinator, session: AsyncSession, case: Case
) -> tuple[list[ChatReply], Problem]:
    await seed(session)
    replies: list[ChatReply] = []
    conversation: int | None = None
    try:
        for text in [case.before, case.text]:
            if text is None:
                continue
            reply = await coordinator.handle(
                session, text, conversation_id=conversation, now=case.now
            )
            conversation = reply.conversation_id
            replies.append(reply)
        if case.answer and asked(replies[-1]):
            replies.append(
                await coordinator.handle(
                    session, case.answer, conversation_id=conversation, now=case.now
                )
            )
        problem = await case.check(session, replies)
    except Exception as exc:  # a crash is a result too
        problem = ("exception", repr(exc)[:300])
    return replies, problem


async def test_live_real_talk(session: AsyncSession, router: LLMRouter, tmp_path: Path) -> None:  # noqa: F811
    rounds = int(os.environ.get("REAL_TALK_ROUNDS", "2"))
    only = {int(n) for n in os.environ.get("REAL_TALK_ONLY", "").split(",") if n}
    cases = [c for c in CASES if not only or c.number in only]
    coordinator = Coordinator(router, get_team(), Settings(upload_dir=tmp_path, app_password=None))
    cost = Decimal(0)
    started = time.monotonic()
    results: list[tuple[int, Case, Problem]] = []
    for round_no in range(1, rounds + 1):
        for case in cases:
            replies, problem = await run_case(coordinator, session, case)
            cost += sum((r.cost_usd for r in replies), Decimal(0))
            results.append((round_no, case, problem))
            status = "ok" if problem is None else f"FAIL {problem[0]}: {problem[1]}"
            print(f"\n[r{round_no} #{case.number}] {case.text!r} -> {status}")
            for reply in replies:
                agents = [a["agent_id"] for a in reply.agents] or [reply.speaker]
                steps = [f"{e['agent_id']}:{e['tool']}" for e in reply.trace]
                print(f"   intents {reply.intents} -> {agents} {steps}")
                print(f"   reply: {reply.reply[:220]!r}")

    print("\n=== real talk ===")
    for round_no in range(1, rounds + 1):
        mine = [r for r in results if r[0] == round_no]
        ok = sum(1 for r in mine if r[2] is None)
        print(f"round {round_no}: {ok}/{len(mine)} ({ok / len(mine):.0%})")
    failures = [r for r in results if r[2] is not None]
    kinds = Counter(problem[0] for _, _, problem in failures if problem)
    print(f"failures by kind: {dict(kinds)}")
    for round_no, case, problem in failures:
        print(f"  r{round_no} #{case.number} {case.text!r}: {problem}")
    print(f"cost ${cost:.4f}, {time.monotonic() - started:.0f} s")
    rate = 1 - len(failures) / len(results)
    assert rate >= PASS_FLOOR, f"success {rate:.0%} < {PASS_FLOOR:.0%}"
