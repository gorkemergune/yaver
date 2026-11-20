"""Live regression set: 25 realistic Turkish messages, each on a fresh copy of the same
state (seeded in code, no LLM), through the real router. Prints the success rate and the
errors by type; fails only below a floor, so it is a measurement first.

    docker compose exec api pytest -m live -k regression -s
    REGRESSION_ONLY=7,16 ...   # just those cases

"Today" is Monday 23 Nov 2026 10:00 Istanbul (week 9 of the term).
"""

import datetime as dt
import os
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.team import get_team
from app.agent.tools import run_tool
from app.config import Settings, get_settings
from app.core.time_resolver import normalize
from app.db.models import (
    Attachment,
    Attendance,
    BlockOverride,
    Course,
    Event,
    Followup,
    Proposal,
    RecurringBlock,
    Task,
    WeekLabel,
)
from app.db.models.enums import FollowupStatus, OverrideAction, ProposalKind, TaskStatus
from app.llm.config import load_providers_config
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.usage import DbUsageStore
from app.services.images import process_image, store_image
from tests.db.conftest import RESET_SQL
from tests.db.test_agent_tools import context
from tests.db.test_live_scenarios import _reply_problems

pytestmark = pytest.mark.live

NOW = dt.datetime(2026, 11, 23, 7, 0, tzinfo=dt.UTC)  # Monday 10:00 Istanbul
IST = dt.timezone(dt.timedelta(hours=3))
SHOTS = Path(__file__).resolve().parents[3] / "examples" / "screenshots"
PASS_FLOOR = 0.6
SEEDED_BLOCKS = 8  # one per weekday of each SEED block

SEED: list[tuple[str, dict[str, Any]]] = [
    ("add_term", {"name": "2026-27 Güz", "start_date": "2026-09-28", "end_date": "2027-01-15"}),
    (
        "add_recurring_block",
        {
            "kind": "class",
            "title": "Linear Algebra",
            "course": "MATH221",
            "weekdays": ["monday", "thursday"],
            "start_time": "09:00",
            "end_time": "11:00",
        },
    ),
    (
        "add_recurring_block",
        {
            "kind": "class",
            "title": "Devre Teorisi",
            "course": "EE211",
            "weekdays": ["tuesday"],
            "start_time": "14:00",
            "end_time": "16:00",
        },
    ),
    (
        "add_recurring_block",
        {
            "kind": "class",
            "title": "Devre Teorisi",
            "course": "EE211",
            "weekdays": ["thursday"],
            "start_time": "13:00",
            "end_time": "14:00",
        },
    ),
    (
        "add_recurring_block",
        {
            "kind": "lab",
            "title": "EE211 Lab",
            "course": "EE211",
            "weekdays": ["wednesday"],
            "start_time": "13:00",
            "end_time": "15:00",
        },
    ),
    (
        "add_recurring_block",
        {
            "kind": "class",
            "title": "Logic Design",
            "course": "CSE221",
            "weekdays": ["wednesday"],
            "start_time": "16:00",
            "end_time": "18:00",
        },
    ),
    (
        "add_recurring_block",
        {
            "kind": "sport",
            "title": "Spor",
            "weekdays": ["tuesday", "thursday"],
            "start_time": "19:00",
            "end_time": "20:00",
        },
    ),
    ("add_followup", {"title": "Hackathon başvurusu", "check_rule": "daily"}),
    ("add_task", {"title": "Rapor yaz", "date": "2026-11-23"}),
]

Check = Callable[[AsyncSession, list[ChatReply]], Awaitable[tuple[str, str] | None]]


@dataclass
class Case:
    name: str
    area: str
    messages: list[str]
    check: Check
    image: str | None = None  # examples/screenshots/<name> with the first message
    results: list[ChatReply] = field(default_factory=list)


def local(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=IST)


async def rows(session: AsyncSession, model: Any, *where: Any) -> list[Any]:
    return list((await session.scalars(select(model).where(*where))).all())


async def count(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def tools(replies: list[ChatReply]) -> list[str]:
    return [entry["tool"] for reply in replies for entry in reply.trace]


def asked(reply: ChatReply) -> bool:
    """A question, or a relayed one ("Friday hangi gün olduğunu soruyor.")."""
    return "?" in reply.reply or "soruyor" in normalize(reply.reply)


# --- checks: None = pass, (kind, detail) = failure ------------------------------------


def absent(course: str, *days: str, not_on: tuple[str, ...] = ()) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
        found = await session.execute(
            select(Attendance.date, Course.code).join(Course, Course.id == Attendance.course_id)
        )
        dates = {(d.isoformat(), c) for d, c in found.all()}
        missing = [d for d in days if (d, course) not in dates]
        wrong = [d for d in not_on if any(x == d for x, _ in dates)]
        if missing:
            return (
                "missing_change" if not tools(replies) else "wrong_date",
                f"no absence {missing}; have {sorted(dates)}",
            )
        if wrong:
            return ("wrong_date", f"absence on {wrong}")
        return None

    return check


def override(
    action: OverrideAction, date: str, title: str, new_start: dt.datetime | None = None
) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
        found = await session.execute(
            select(BlockOverride, RecurringBlock.title).join(
                RecurringBlock, RecurringBlock.id == BlockOverride.block_id
            )
        )
        items = [(o.action, o.date.isoformat(), t, o.new_start_at) for o, t in found.all()]
        hit = [
            i
            for i in items
            if i[0] is action and i[1] == date and normalize(title) in normalize(i[2])
        ]
        if not hit:
            kind = "missing_change" if not items else "wrong_target"
            return (kind, f"want {action.value} {title} {date}; have {items}")
        if new_start and hit[0][3] != new_start:
            return ("wrong_time", f"moved to {hit[0][3]}, want {new_start}")
        if len(items) > len(hit):
            return ("extra_change", f"also {items}")
        return None

    return check


def event(kind: str, start: dt.datetime, words: str, all_day: bool = False) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
        events = await rows(session, Event)
        if not events:
            return ("missing_change", "no event")
        match = [
            e for e in events if e.kind.value == kind and normalize(words) in normalize(e.title)
        ]
        if not match:
            return ("wrong_args", f"{[(e.kind.value, e.title) for e in events]}")
        got = match[0].start_at
        if not all_day and got != start:
            return (
                "wrong_time" if got.date() == start.date() else "wrong_date",
                f"{got} != {start}",
            )
        return None

    return check


def nothing_written_and_asked(*models: Any) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
        for model in models:
            if await count(session, model):
                return ("guessed", f"wrote a {model.__name__} instead of asking")
        if not asked(replies[-1]):
            return ("no_question", "should ask")
        return None

    return check


def read_only(tool: str) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
        if any(r.change_set_id for r in replies):
            return ("extra_change", "a read-only question changed something")
        if tool not in tools(replies):
            return ("wrong_tool", f"{tool} not called: {tools(replies)}")
        return None

    return check


async def limit_8(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    course = await session.scalar(select(Course).where(Course.code == "MATH221"))
    if course is None or course.absence_limit != 8:
        return ("missing_change", f"limit {course.absence_limit if course else None}")
    return None


async def followup_daily(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    items = [f for f in await rows(session, Followup) if "iceberg" in normalize(f.title)]
    if not items:
        return ("missing_change", "no Iceberg follow-up")
    return None


async def hackathon_accepted(
    session: AsyncSession, replies: list[ChatReply]
) -> tuple[str, str] | None:
    item = (await rows(session, Followup))[0]
    if item.status is not FollowupStatus.POSITIVE:
        return ("missing_change", f"status {item.status.value}")
    return None


async def mixed(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    problem = await override(OverrideAction.CANCEL, "2026-11-23", "Linear")(session, replies)
    if problem:
        return problem
    problem = await event("meeting", local("2026-11-24", "14:00"), "iceberg")(session, replies)
    if problem:
        return problem
    if "iceberg" not in normalize(replies[-1].reply):
        return ("dropped_part", "the meeting was added but the answer does not say so")
    return None


async def undone(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    if await count(session, Event):
        return ("undo_failed", "the event is still there")
    if "undo" not in tools(replies):
        return ("wrong_tool", f"no undo call: {tools(replies)}")
    return None


async def cancel_undone(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    if await count(session, BlockOverride):
        return ("undo_failed", "the cancellation is still there")
    return None


def proposal(kind: ProposalKind) -> Check:
    async def check(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
        found = await rows(session, Proposal)
        if not found or found[0].kind is not kind:
            return ("missing_change", f"no {kind.value} proposal")
        if await count(session, Event) or await count(session, RecurringBlock) > SEEDED_BLOCKS:
            return ("extra_change", "written before the user confirmed")
        return None

    return check


async def work_block(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    blocks = [b for b in await rows(session, RecurringBlock) if b.weekday == 4]
    if not blocks:
        return ("missing_change", "no Friday block")
    block = blocks[0]
    if (block.start_time, block.end_time) != (dt.time(9), dt.time(17)):
        return ("wrong_time", f"{block.start_time}-{block.end_time}")
    return None


async def task_tomorrow(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    tasks = [t for t in await rows(session, Task) if "sunum" in normalize(t.title)]
    if not tasks:
        return ("missing_change", "no task")
    if tasks[0].date != dt.date(2026, 11, 24):
        return ("wrong_date", f"{tasks[0].date}")
    return None


async def task_done(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    task = (await rows(session, Task))[0]
    if task.status is not TaskStatus.DONE:
        return ("missing_change", f"status {task.status.value}")
    return None


async def week_named(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    labels = await rows(session, WeekLabel)
    if not labels:
        return ("missing_change", "no week label")
    if labels[0].week_start != dt.date(2026, 11, 23) or "hackathon" not in normalize(
        labels[0].label
    ):
        return ("wrong_args", f"{labels[0].week_start} {labels[0].label}")
    return None


async def summary_asked(session: AsyncSession, replies: list[ChatReply]) -> tuple[str, str] | None:
    if "get_attendance_summary" not in tools(replies):
        return ("wrong_tool", f"{tools(replies)}")
    if any(r.change_set_id for r in replies):
        return ("extra_change", "changed something")
    return None


CASES = [
    Case(
        "1 bugün devamsızlık",
        "devamsızlık",
        ["bugün linear'a gitmedim"],
        absent("MATH221", "2026-11-23"),
    ),
    Case(
        "2 iki gün, biri derssiz",
        "devamsızlık",
        ["geçen perşembe ve cuma EE211'e gitmedim"],
        absent("EE211", "2026-11-19", not_on=("2026-11-20",)),
    ),
    Case("3 limit", "devamsızlık", ["MATH221 devamsızlık sınırım 8 saat"], limit_8),
    Case("4 özet", "devamsızlık", ["kaç saat devamsızlığım var?"], summary_asked),
    Case(
        "5 yarın iptal",
        "iptal",
        ["yarınki EE211 dersi iptal"],
        override(OverrideAction.CANCEL, "2026-11-24", "Devre"),
    ),
    Case(
        "6 spor iptal",
        "iptal",
        ["bu perşembe sporu iptal et"],
        override(OverrideAction.CANCEL, "2026-11-26", "Spor"),
    ),
    Case(
        "7 lab taşıma",
        "taşıma",
        ["çarşamba lab cuma 14-16'ya alındı"],
        override(OverrideAction.MOVE, "2026-11-25", "Lab", local("2026-11-27", "14:00")),
    ),
    Case(
        "8 ders taşıma",
        "taşıma",
        ["bu hafta perşembe linear yerine cumartesi 10-12'de"],
        override(OverrideAction.MOVE, "2026-11-26", "Linear", local("2026-11-28", "10:00")),
    ),
    Case(
        "9 vize",
        "sınav",
        ["27 Kasım Cuma 10:00'da MATH221 vizesi var"],
        event("exam", local("2026-11-27", "10:00"), "math221"),
    ),
    Case(
        "10 final",
        "sınav",
        ["EE211 finali 8 ocak 13:30'da"],
        event("exam", local("2027-01-08", "13:30"), "ee211"),
    ),
    Case(
        "11 quiz haftaya",
        "sınav",
        ["haftaya salı 10'da CSE221 quiz var"],
        event("quiz", local("2026-12-01", "10:00"), "cse221"),
    ),
    Case(
        "12 takip ekle",
        "takip",
        ["Iceberg'e staj başvurusu yaptım, her gün dönüş geldi mi diye sor"],
        followup_daily,
    ),
    Case("13 takip kapat", "takip", ["hackathon kabul geldi!"], hackathon_accepted),
    Case(
        "14 karışık", "karışık", ["bugün linear iptal, yarın 14'te Iceberg toplantısı var"], mixed
    ),
    Case("15 yaver adıyla", "okuma", ["Friday, yarın ne var?"], read_only("get_day_plan")),
    Case(
        "16 gün adı tutmuyor",
        "belirsiz tarih",
        ["27 Kasım Perşembe'ye toplantı ekle"],
        nothing_written_and_asked(Event),
    ),
    Case(
        "17 belirsiz gün",
        "belirsiz tarih",
        ["geçen hafta bir gün EE211'e gitmedim"],
        nothing_written_and_asked(Attendance),
    ),
    Case(
        "18 ekle + geri al",
        "geri al",
        ["perşembe 15:00'e Medipol toplantısı ekle", "geri al"],
        undone,
    ),
    Case(
        "19 iptal + geri al",
        "geri al",
        ["yarınki spor iptal", "az önceki değişikliği geri al"],
        cancel_undone,
    ),
    Case(
        "20 program görseli",
        "görsel",
        ["programım bu"],
        proposal(ProposalKind.SCHEDULE),
        image="schedule.png",
    ),
    Case(
        "21 duyuru görseli",
        "görsel",
        ["şunu ekler misin"],
        proposal(ProposalKind.EVENTS),
        image="exam_notice.png",
    ),
    Case("22 iş bloğu", "program", ["her cuma 9-17 Medipol'de çalışıyorum"], work_block),
    Case("23 görev", "görev", ["yarın için 'sunum hazırla' görevi ekle"], task_tomorrow),
    Case("24 görev bitti", "görev", ["rapor yaz görevini bitirdim"], task_done),
    Case("25 hafta adı", "hafta", ["bu haftanın adı Hackathon Haftası olsun"], week_named),
]


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    config = load_providers_config()
    fast = config.providers[config.tiers["fast"].provider]
    if fast.api_key_env and not env_value(get_settings(), fast.api_key_env):
        pytest.skip(f"{fast.api_key_env} not set")
    router = build_router(config=config, store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


async def fresh_state(session: AsyncSession) -> None:
    await session.rollback()
    async with session.bind.connect() as conn:  # type: ignore[union-attr]
        await conn.exec_driver_sql(RESET_SQL)
        await conn.commit()
    session.expunge_all()  # ids restart: forget the objects of the previous case
    ctx = context(session, "academic")
    for name, args in SEED:
        result = await run_tool(name, args, ctx)
        assert "error" not in result, (name, result)
    await session.commit()


async def attach(session: AsyncSession, upload_dir: Path, name: str) -> int:
    image = process_image((SHOTS / name).read_bytes(), max_bytes=20 * 1024 * 1024, max_edge=1600)
    attachment = Attachment(
        path=store_image(image, upload_dir, NOW),
        mime=image.mime,
        width=image.width,
        height=image.height,
        size_bytes=len(image.data),
        sha256=image.sha256,
        filename=name,
    )
    session.add(attachment)
    await session.commit()
    return attachment.id


async def test_live_regression(session: AsyncSession, router: LLMRouter, tmp_path: Path) -> None:
    only = {int(n) for n in os.environ.get("REGRESSION_ONLY", "").split(",") if n}
    settings = Settings(upload_dir=tmp_path, app_password=None)
    coordinator = Coordinator(router, get_team(), settings)
    failures: list[tuple[Case, str, str]] = []
    cost = Decimal(0)
    ran = 0
    started = time.monotonic()
    for case in CASES:
        number = int(case.name.split()[0])
        if only and number not in only:
            continue
        ran += 1
        await fresh_state(session)
        conversation: int | None = None
        try:
            for index, text in enumerate(case.messages):
                attachments = (
                    [await attach(session, tmp_path, case.image)]
                    if case.image and index == 0
                    else []
                )
                reply = await coordinator.handle(
                    session, text, conversation_id=conversation, now=NOW, attachment_ids=attachments
                )
                conversation = reply.conversation_id
                case.results.append(reply)
                cost += reply.cost_usd
            problem = await case.check(session, case.results)
            quality = [p for r in case.results for p in _reply_problems(r)]
            if problem is None and quality:
                problem = ("reply_quality", "; ".join(quality))
        except Exception as exc:  # a crash is a result too
            problem = ("exception", repr(exc)[:300])
        status = "ok" if problem is None else f"FAIL {problem[0]}: {problem[1]}"
        print(f"\n[{case.name}] {case.messages} -> {status}")
        for reply in case.results:
            print(f"   reply: {reply.reply[:300]}")
            print(f"   tools: {[e['tool'] for e in reply.trace]}")
        if problem is not None:
            failures.append((case, *problem))

    passed = ran - len(failures)
    kinds = Counter(kind for _, kind, _ in failures)
    by_area = Counter(case.area for case, _, _ in failures)
    print("\n=== regression summary")
    print(
        f"passed {passed}/{ran} = {passed / ran:.0%}; LLM cost ${cost}; "
        f"{time.monotonic() - started:.0f}s"
    )
    print(f"errors by kind: {dict(kinds.most_common())}")
    print(f"errors by area: {dict(by_area.most_common())}")
    for case, kind, detail in failures:
        print(f"  - {case.name}: {kind}: {detail}")
    assert passed / ran >= PASS_FLOOR
