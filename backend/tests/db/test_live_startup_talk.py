"""Live set: "who did what in week3" for the startup meeting, against a fake GitHub API
(tests/github_fake.py: week1-week3, four members - Ali, Zeynep, Mert, Deniz). The first
message is the one that failed on live, word for word; five more in the same spirit.

    docker compose exec api pytest -m live -k startup_talk -s

Real router and team (config/agents.yaml over the example), test database. Each answer
must come from Venture's GitHub tools and say, per member, what they did in week 3.
"""

import re
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.team import get_team, load_team_config
from app.agent.tools import github as github_tools
from app.config import Settings
from app.core.time_resolver import normalize
from app.llm.router import LLMRouter
from app.office.sync import sync_employees
from tests.db.test_live_regression import NOW, fresh_state, router  # noqa: F401 (fixture)
from tests.db.test_live_routing import routed_to
from tests.github_fake import MEMBERS, WEEK3_FACTS, FakeGitHub

pytestmark = pytest.mark.live
ROUNDS = 1  # more with STARTUP_TALK_ROUNDS
PASS_FLOOR = 1.0  # every answer: routed to Venture, every member with their week-3 work

MESSAGES = [
    # live, word for word: went to Creator ("alanım değil"), then "repoya erişimim yok"
    "bu akşamki NEXA toplantısında üyeler week3'te yaptığı projeleri sunacak, kim ne yapmış "
    "bana bir taslak hazırla. github/gorkemergune/startup",
    "yarınki nexa sunumunda herkes week3 projesini anlatıcak, üye üye ne yaptıklarını özetle",
    "week3'te kim ne yaptı repodan bakıp kısa bi özet çıkarır mısın",
    "nexa toplantısı için week3 teslimlerinin taslağını hazırla github/gorkemergune/startup",
    "ekip week3 klasörüne ne koymuş, kişi kişi yaz",
    "bu akşam toplantıda üyeler sunum yapcak, github reposundaki week3 çalışmalarından bana "
    "sunum taslağı çıkar",
]
GITHUB_TOOLS = {name for name in github_tools.__dict__ if name.startswith("github_")}


@dataclass
class Verdict:
    ok: bool
    why: str


def member_summaries(reply: str) -> dict[str, bool]:
    """For each member: their name appears and, in the text up to the next member's name,
    a word of their week-3 work (tests.github_fake.WEEK3_FACTS)."""
    text = normalize(reply)
    spots = {
        key: m.start()
        for key, name in MEMBERS.items()
        if (m := re.search(rf"\b{normalize(name)}", text))
    }
    found = {}
    for key in MEMBERS:
        if key not in spots:
            found[key] = False
            continue
        later = [p for p in spots.values() if p > spots[key]]
        part = text[spots[key] : min(later) if later else len(text)]
        found[key] = any(normalize(word) in part for word in WEEK3_FACTS[key])
    return found


def judge(reply: ChatReply) -> Verdict:
    got = routed_to(reply)
    if "startup" not in got:
        return Verdict(False, f"not routed to Venture: {sorted(got)}")
    used = {step["tool"] for step in reply.trace if step["tool"] in GITHUB_TOOLS}
    if not used:
        return Verdict(False, "Venture used no GitHub tool")
    if any(step.get("error") for step in reply.trace if step["tool"] in GITHUB_TOOLS):
        return Verdict(False, "a GitHub tool failed")
    summaries = member_summaries(reply.reply)
    missing = [MEMBERS[k] for k, ok in summaries.items() if not ok]
    if missing:
        return Verdict(False, f"no week-3 summary for {', '.join(missing)}")
    return Verdict(True, f"tools: {', '.join(sorted(used))}")


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    api = FakeGitHub()
    monkeypatch.setattr(github_tools, "client_factory", api.factory())
    monkeypatch.setattr(
        github_tools,
        "get_settings",
        lambda: Settings(
            _env_file=None, github_token=SecretStr("t"), github_startup_repo="acme/startup"
        ),
    )
    return api


async def test_live_startup_talk(
    session: AsyncSession,
    router: LLMRouter,  # noqa: F811
    fake_github: FakeGitHub,
    tmp_path: Path,
) -> None:
    import os

    rounds = int(os.environ.get("STARTUP_TALK_ROUNDS", ROUNDS))
    team = get_team()
    coordinator = Coordinator(router, team, Settings(upload_dir=tmp_path, app_password=None))
    cost = Decimal(0)
    results: list[tuple[str, Verdict]] = []
    started = time.monotonic()
    for round_no in range(1, rounds + 1):
        for message in MESSAGES:
            await fresh_state(session)
            await sync_employees(session, load_team_config(), NOW)
            await session.commit()
            reply = await coordinator.handle(session, message, now=NOW)
            cost += reply.cost_usd
            verdict = judge(reply)
            results.append((message, verdict))
            mark = "ok" if verdict.ok else "MISS"
            print(f"\n[{mark}] (round {round_no}) {message!r}\n   {verdict.why}")
            print("   reply: " + reply.reply.replace("\n", "\n          ")[:1500])
    passed = sum(1 for _, v in results if v.ok)
    took = time.monotonic() - started
    print(f"\n=== startup talk: {passed}/{len(results)}; LLM cost ${cost}; {took:.0f}s")
    for message, verdict in results:
        if not verdict.ok:
            print(f"  - {message!r}: {verdict.why}")
    assert passed / len(results) >= PASS_FLOOR
