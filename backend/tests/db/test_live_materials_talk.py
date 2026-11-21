"""Live: questions about the course materials in the user's own way of writing ("bu hafta
cse221de ne var", "dsa sınavına neler çalışmam lazım"). Each answer must name the right week /
section / pages and its source. Fails below 90 %.

    docker compose exec api pytest -m live -k materials_talk -s
    MATERIALS_TALK_ROUNDS=2 MATERIALS_TALK_ONLY=3,6 ...

Needs a materials bundle (personal, never in the repo): MATERIALS_BUNDLE or the newest folder
under /bundles (dev mounts data/bundles there); skipped without one. The test database gets
the regression seed (MATH221, EE211, CSE221, CSE211 by their blocks), the bundle on top (the
way live will get it), the alias DSA and three exams. "Today" is Monday 23 Nov 2026 10:00
Istanbul: week 9 of the term.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.team import get_team
from app.agent.tools import run_tool
from app.config import Settings
from app.core.time_resolver import normalize
from app.llm.router import LLMRouter
from app.materials.bundle import import_bundle
from tests.db.test_agent_tools import context
from tests.db.test_live_real_talk import EXTRA_SEED
from tests.db.test_live_regression import NOW, fresh_state, router  # noqa: F401 (fixture)

pytestmark = pytest.mark.live
PASS_FLOOR = 0.9
Check = Callable[[str], str | None]  # the reply (normalized) -> what is missing, or None


def bundle_folder() -> Path | None:
    named = os.environ.get("MATERIALS_BUNDLE")
    if named:
        return Path(named)
    root = Path("/bundles")
    found = sorted(p for p in root.glob("materials-*") if (p / "manifest.json").is_file())
    return found[-1] if found else None


def has(*groups: tuple[str, ...] | str, at_least: int = 1) -> Check:
    """Every group must appear; a tuple group = any of its words (at_least of them)."""

    def check(reply: str) -> str | None:
        for group in groups:
            words = (group,) if isinstance(group, str) else group
            need = at_least if isinstance(group, tuple) else 1
            found = [w for w in words if normalize(w) in reply]
            if len(found) < need:
                return f"missing {words if len(words) > 1 else words[0]!r}"
        return None

    return check


SYLLABUS = ("syllabus", "izlence")


@dataclass(frozen=True)
class Case:
    number: int
    text: str
    check: Check
    # the user's reply if the team asks back (an unknown course word is asked once)
    answer: str | None = None


CASES = [
    Case(
        1,
        "bu hafta cse221de ne var",
        has(
            (
                "decoder",
                "mux",
                "multiplier",
                "comparator",
                "carpici",
                "karsilastirici",
                "kod cozucu",
            ),
            "9",
            SYLLABUS,
        ),
    ),
    Case(
        2, "haftaya lineer cebirde hangi bölümleri okumam lazım", has("4.2", "4.3"), "evet math221"
    ),
    Case(
        3,
        "math221 ara sınavına hangi bölümlerden çalışayım",
        has(("1.1", "1.3", "1.5", "2.1", "2.3", "3.1", "3.3", "3.5"), at_least=4),
    ),
    Case(
        4,
        "ee211 lab kitabında thevenin deneyi hangi sayfada",
        has("39", ("lab_book", "lab book", "lab kitab")),
    ),
    Case(5, "cse221 karnaugh notları var mı", has("map", ("notlari", "not"))),
    Case(
        6,
        "dsa sınavına neler çalışmam lazım",
        has(("stack", "yigin"), ("queue", "kuyruk"), ("list", "liste")),
    ),
    Case(7, "tkl de bu hafta hangi kitap okunacak", has("yaklasan dalga")),
    Case(
        8, "uygarlık tarihi haftaya ne işlenecek", has(("feodal", "orta cag"), ("219", "bolum 9"))
    ),
    Case(9, "labwork01 part 2 hangi haftanın", has(("4. hafta", "hafta 4", "4.hafta", "4 hafta"))),
    Case(
        10,
        "geçen hafta cse 221 de ne vardı",
        has("8", ("review", "midterm", "ara sinav", "tekrar")),
    ),
    Case(11, "cse221 bool notlarında dualite ne diyo", has("dual", "bool")),
    Case(
        12,
        "lineer cebirde determinant hangi hafta",
        has(("4. hafta", "hafta 4", "4.hafta"), "2.1"),
        "evet math221",
    ),
    Case(13, "ee211 5. deney ne hakkında", has("thevenin")),
    Case(
        14,
        "cse 221 sınavına ne çalışmalıyım",
        has(
            (
                "num1",
                "compl",
                "signed",
                "codes",
                "bool",
                "func",
                "simpl",
                "canonic",
                "map",
                "comb1",
            ),
            at_least=3,
        ),
    ),
    Case(15, "hum103 bu hafta kaç sayfa okumam lazım", has("195", "217")),
]


async def seed(session: AsyncSession, folder: Path, uploads: Path) -> None:
    await fresh_state(session)
    ctx = context(session, "academic")
    for name, args in EXTRA_SEED:
        assert "error" not in await run_tool(name, args, ctx), name
    await session.commit()
    report = await import_bundle(session, folder, uploads)
    assert report.materials.new, report
    ctx = context(session, "academic")
    steps: list[tuple[str, dict[str, Any]]] = [
        ("add_course_alias", {"course": "CSE211", "alias": "DSA"}),
        (
            "add_event",
            {
                "kind": "exam",
                "title": "CSE221 Ara Sınav",
                "date": "2026-11-25",
                "start_time": "13:00",
                "course": "CSE221",
            },
        ),
        (
            "add_event",
            {
                "kind": "exam",
                "title": "MATH221 Ara Sınav",
                "date": "2026-11-27",
                "start_time": "16:00",
                "course": "MATH221",
            },
        ),
        (
            "add_event",
            {
                "kind": "exam",
                "title": "DSA Ara Sınav",
                "date": "2026-11-30",
                "start_time": "10:00",
                "course": "CSE211",
                "topics": ["stack", "queue", "lists"],
            },
        ),
    ]
    for name, args in steps:
        result = await run_tool(name, args, ctx)
        assert "error" not in result, (name, result)
    await session.commit()


async def test_live_materials_talk(
    session: AsyncSession,
    router: LLMRouter,  # noqa: F811
    tmp_path: Path,
) -> None:
    folder = bundle_folder()
    if folder is None or not (folder / "manifest.json").is_file():
        pytest.skip("no materials bundle (MATERIALS_BUNDLE or /bundles/materials-*)")
    rounds = int(os.environ.get("MATERIALS_TALK_ROUNDS", "1"))
    only = {int(n) for n in os.environ.get("MATERIALS_TALK_ONLY", "").split(",") if n}
    cases = [c for c in CASES if not only or c.number in only]
    await seed(session, folder, tmp_path / "uploads")
    coordinator = Coordinator(router, get_team(), Settings(upload_dir=tmp_path, app_password=None))
    cost = Decimal(0)
    started = time.monotonic()
    results: list[tuple[int, Case, str | None]] = []
    for round_no in range(1, rounds + 1):
        for case in cases:
            try:
                reply: ChatReply = await coordinator.handle(session, case.text, now=NOW)
                cost += reply.cost_usd
                if case.answer and "?" in reply.reply:
                    reply = await coordinator.handle(
                        session, case.answer, conversation_id=reply.conversation_id, now=NOW
                    )
                    cost += reply.cost_usd
                problem = case.check(normalize(reply.reply))
                steps = [f"{e['agent_id']}:{e['tool']}" for e in reply.trace]
                text = reply.reply
            except Exception as exc:  # a crash is a result too
                problem, steps, text = f"exception {exc!r}"[:300], [], ""
            results.append((round_no, case, problem))
            status = "ok" if problem is None else f"FAIL {problem}"
            print(f"\n[r{round_no} #{case.number}] {case.text!r} -> {status}")
            print(f"   {steps}")
            print(f"   reply: {text[:600]!r}")
    print("\n=== materials talk ===")
    for round_no in range(1, rounds + 1):
        mine = [r for r in results if r[0] == round_no]
        ok = sum(1 for r in mine if r[2] is None)
        print(f"round {round_no}: {ok}/{len(mine)} ({ok / len(mine):.0%})")
    failures = [r for r in results if r[2] is not None]
    for round_no, case, problem in failures:
        print(f"  r{round_no} #{case.number} {case.text!r}: {problem}")
    print(f"cost ${cost:.4f}, {time.monotonic() - started:.0f} s")
    rate = 1 - len(failures) / len(results)
    assert rate >= PASS_FLOOR, f"success {rate:.0%} < {PASS_FLOOR:.0%}"
