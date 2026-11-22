"""Startup requests reach Venture: the live failure was "bu akşamki NEXA toplantısında
üyeler week3'te yaptığı projeleri sunacak, kim ne yapmış bana bir taslak hazırla.
github/gorkemergune/startup" -> classified as content -> Creator ("alanım değil") -> Yaver
gave up. Now: a repo / weekN in the words is Venture's whatever the classifier said, a
"not my area" in words counts as a handoff, and a handoff never ends in "do it yourself"."""

from typing import Any

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import intents
from app.agent.coordinator import Coordinator
from app.agent.team import TeamConfig, build_team
from app.agent.tools import github as github_tools
from app.config import Settings
from app.llm.types import LLMRequest, LLMResponse
from tests.agent.test_github_tools import settings as github_settings
from tests.agent_fakes import (
    NOW,
    REPO_CONFIG,
    ScriptedLLM,
    call,
    coordinator,
    last_result,
    route_as,
    say,
)
from tests.github_fake import FakeGitHub

LIVE = (
    "bu akşamki NEXA toplantısında üyeler week3'te yaptığı projeleri sunacak, kim ne yapmış "
    "bana bir taslak hazırla. github/gorkemergune/startup"
)
DRAFT = (
    "Taslak: Ali - öneri API'si; Zeynep - landing page; Mert - rakip analizi; Deniz - segmentler."
)


@pytest.fixture(autouse=True)
def fake_github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    api = FakeGitHub()  # never the real GitHub from a test
    monkeypatch.setattr(github_tools, "client_factory", api.factory())
    monkeypatch.setattr(github_tools, "get_settings", github_settings)
    return api


@pytest.mark.parametrize(
    "text",
    [
        LIVE,
        "week3 klasöründe kim ne yapmış",
        "repoda bu hafta kim commit atmış",
        "github.com/acme/startup issue'larına bak",
    ],
)
def test_startup_signals(text: str) -> None:
    assert intents.startup_signal(text)


@pytest.mark.parametrize(
    "text", ["bu hafta cse221de ne var", "3. hafta konuları", "instagram için post taslağı"]
)
def test_no_startup_signal(text: str) -> None:
    assert not intents.startup_signal(text)


@pytest.mark.parametrize(
    ("reply", "declined"),
    [
        ("Bu benim alanımın dışında, Venture'a sorman lazım.", True),
        ("Bu alanım değil.", True),
        ("Üzgünüm, bu iş benim görevim değil.", True),
        ("Taslağı hazırladım: ...", False),
        ("Bu hafta 3 post önerim var.", False),
    ],
)
def test_declines(reply: str, declined: bool) -> None:
    assert intents.declines(reply) is declined


async def test_the_live_sentence_goes_to_venture_whatever_the_model_said(
    session: AsyncSession, fake_github: FakeGitHub
) -> None:
    llm = ScriptedLLM()
    llm.add("intent", route_as(("content", LIVE)))  # what happened live
    llm.add(
        "startup",
        call("github_week_summary", week=3, repo="github/gorkemergune/startup"),
        say(DRAFT),
    )
    llm.add("yaver", say(DRAFT))

    reply = await coordinator(llm).handle(session, LIVE, now=NOW)

    assert [a["agent_id"] for a in reply.agents] == ["startup"]  # Creator never got it
    assert ("GET", "/repos/gorkemergune/startup/git/trees/main") in fake_github.requests
    llm.assert_done()


async def test_not_my_area_in_words_is_a_handoff_and_yaver_routes_it(
    session: AsyncSession,
) -> None:
    text = "NEXA sunumu için bir taslak hazırla"  # no repo, no weekN: the model's guess stands
    seen: dict[str, Any] = {}

    def coordinator_routes(request: LLMRequest) -> LLMResponse:
        seen.update(last_result(request))
        return call("delegate", agent_id="startup", instruction=text)

    llm = ScriptedLLM()
    llm.add("intent", route_as(("content", text)))
    llm.add("content", say("Bu benim alanımın dışında, startup işi."))  # no handoff call
    llm.add("startup", say(DRAFT))
    llm.add("yaver", coordinator_routes, say(DRAFT))

    reply = await coordinator(llm).handle(session, text, now=NOW)

    assert "delegate this request now" in seen["note"]  # not "do it yourself or ask"
    assert "never tell the user it can't be done" in seen["note"]
    assert [a["agent_id"] for a in reply.agents] == ["startup"]
    assert reply.reply == DRAFT
    llm.assert_done()


async def test_a_declined_repo_request_goes_straight_to_venture(session: AsyncSession) -> None:
    text = "week3 klasöründe kim ne yapmış"
    llm = ScriptedLLM()
    llm.add("intent", route_as(("course_note", text)))  # weeks sound like a course
    llm.add("academic", say("Bu benim alanım değil."))
    llm.add("startup", call("github_week_summary", week=3), say(DRAFT))
    llm.add("yaver", say(DRAFT))

    reply = await coordinator(llm).handle(session, text, now=NOW)

    assert [a["agent_id"] for a in reply.agents] == ["startup"]
    llm.assert_done()


async def test_the_users_names_reach_the_classifier(session: AsyncSession) -> None:
    with (REPO_CONFIG / "agents.example.yaml").open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    next(a for a in raw["agents"] if a["id"] == "startup")["keywords"] = ["Nexa", "Nexa Lab"]
    team = build_team(TeamConfig.model_validate(raw), "Görkem")
    seen: list[LLMRequest] = []

    def classify(request: LLMRequest) -> LLMResponse:
        seen.append(request)
        return route_as(("startup", "NEXA toplantısı için taslak"))

    llm = ScriptedLLM()
    llm.add("intent", classify)
    llm.add("startup", say(DRAFT))
    llm.add("yaver", say(DRAFT))

    await Coordinator(llm, team, Settings(_env_file=None)).handle(
        session, "NEXA toplantısı için taslak", now=NOW
    )

    assert "- Nexa, Nexa Lab: startup" in seen[0].system
    llm.assert_done()
