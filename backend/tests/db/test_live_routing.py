"""Live routing set for the ten-person office: does the coordinator hand each message to
the right employee? Real router, the team from config/agents(.example).yaml, the
regression set's seeded state on the test database.

    docker compose exec api pytest -m live -k routing -s

Prints who got each message and the cost; fails only below a floor (a measurement first).
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import ChatReply, Coordinator
from app.agent.team import get_team, load_team_config
from app.config import Settings
from app.llm.router import LLMRouter
from app.office.sync import sync_employees
from tests.db.test_live_regression import NOW, fresh_state, router  # noqa: F401 (fixture)

pytestmark = pytest.mark.live
PASS_FLOOR = 0.7


@dataclass
class Route:
    message: str
    expected: str  # employee id that must get it
    # a one-area request the coordinator may do itself (fast_path_tools in agents.yaml)
    fast_path: bool = False
    replies: list[ChatReply] = field(default_factory=list)


ROUTES = [
    Route("Nexa için bu hafta 3 post fikri bul", "content"),
    Route("Nexa Lab'in rakiplerini araştır", "startup"),
    Route("Ali'nin doğum günü 28 Kasım, unutmayayım", "social"),
    Route("Iceberg staj başvuruma dönüş bekliyorum, her gün sor", "career"),
    Route("Bu haftaki reklam performansı nasıl?", "ads"),
    Route("Geçen salı EE211'e gitmedim", "academic"),
    Route("Cuma 15:00'te proje toplantısı ekle", "agenda", fast_path=True),
    Route("Bugün spora gidemeyeceğim", "discipline"),
    # sport, workouts, screen time: always the discipline employee (coordinator rule 2a)
    Route("Bu akşam antrenmanı atlıyorum", "discipline"),
    Route("Yarınki spor seansını iptal et", "discipline"),
    Route("Bugün 45 dakika koştum", "discipline"),
    Route("Salı ve perşembe 19:00-20:00 spor ekle", "discipline"),
    Route("Bugün ne kadar Valorant oynadım?", "discipline"),
    Route("Ekran sürem bugün ne kadar?", "discipline"),
    Route("Bu haftaki sporu cumartesiye al", "discipline"),
    Route("Dizim ağrıyor, bu hafta spor yapamam", "discipline"),
    Route("Spora gittim, check-in'e yaz", "discipline"),
    Route("Spor salonuna yarın sabah gideceğim", "discipline"),
]


def routed_to(reply: ChatReply) -> set[str]:
    delegated = {
        str((step.get("arguments") or {}).get("agent_id"))
        for step in reply.trace
        if step["tool"] == "delegate"
    }
    return delegated | {agent["agent_id"] for agent in reply.agents} | {reply.speaker}


async def test_live_routing(session: AsyncSession, router: LLMRouter, tmp_path: Path) -> None:  # noqa: F811
    team = get_team()
    names = {m.id: m.name for m in (team.coordinator, *team.agents)}
    coordinator = Coordinator(router, team, Settings(upload_dir=tmp_path, app_password=None))
    fast_path_tools = set(load_team_config().coordinator.fast_path_tools)
    cost = Decimal(0)
    misses: list[str] = []
    started = time.monotonic()
    for route in ROUTES:
        await fresh_state(session)
        await sync_employees(session, load_team_config(), NOW)  # notebooks exist
        await session.commit()
        reply = await coordinator.handle(session, route.message, now=NOW)
        cost += reply.cost_usd
        got = routed_to(reply)
        fast = route.fast_path and any(
            step["tool"] in fast_path_tools for step in reply.trace if step["agent_id"] == "yaver"
        )
        ok = route.expected in got or fast
        who = ", ".join(sorted(names.get(g, g) for g in got))
        mark = "ok" if ok else "MISS"
        print(f"\n[{mark}] {route.message!r} -> {who} (want {names[route.expected]})")
        print(f"   reply: {reply.reply[:200]}")
        if not ok:
            misses.append(f"{route.message!r} -> {who}")
    passed = len(ROUTES) - len(misses)
    took = time.monotonic() - started
    print(f"\n=== routing: {passed}/{len(ROUTES)}; LLM cost ${cost}; {took:.0f}s")
    for miss in misses:
        print(f"  - {miss}")
    assert passed / len(ROUTES) >= PASS_FLOOR
