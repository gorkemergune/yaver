"""No "yapamam" untried: an answer that says it can't (no access, no tool, "paste it to me")
without any tool run is run once more, told to try its tools and to name a missing setting.
Naming the setting (GITHUB_STARTUP_REPO, TAVILY_API_KEY) is the right answer, not a give-up."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import intents
from app.agent.tools import github as github_tools
from app.llm.types import LLMRequest, LLMResponse
from tests.agent.test_github_tools import settings as github_settings
from tests.agent_fakes import NOW, ScriptedLLM, call, coordinator, route_as, say
from tests.github_fake import FakeGitHub

TEXT = "week3 klasöründe kim ne yapmış"


@pytest.fixture(autouse=True)
def fake_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github_tools, "client_factory", FakeGitHub().factory())
    monkeypatch.setattr(github_tools, "get_settings", github_settings)


@pytest.mark.parametrize(
    ("reply", "gave_up"),
    [
        ("Repoya erişimim yok, aracım yok.", True),
        ("Bunu yapamıyorum, metni bana yapıştırır mısın?", True),
        ("Ders notunu kopyalayıp buraya atarsan özetlerim.", True),
        # live set #48: no get_ad_report call at all
        ("Metrics: geçen ayın harcamasını doğrudan sorgulayamıyor; rapor gönderirsen bakar.", True),
        ("Bu dosyaya bakamıyorum.", True),
        ("Geçen ay için kayıtlı rapor yok; Ads Manager'dan CSV atarsan eklerim.", False),
        ("GITHUB_STARTUP_REPO ayarlı değil, o yüzden depoya bakamıyorum.", False),
        ("Web arama anahtarı yok (TAVILY_API_KEY ya da BRAVE_API_KEY).", False),
        ("Week3'te dört kişi var: Ali, Zeynep, Mert, Deniz.", False),
    ],
)
def test_gives_up(reply: str, gave_up: bool) -> None:
    assert intents.gives_up(reply) is gave_up


async def test_a_delegated_give_up_is_tried_again(session: AsyncSession) -> None:
    suffixes: list[str] = []

    def tries(request: LLMRequest) -> LLMResponse:
        suffixes.append(request.system_suffix or "")
        return call("github_week_summary", week=3)

    llm = ScriptedLLM()
    llm.add("intent", route_as(("startup", TEXT)))
    llm.add(
        "startup",
        say("Repoya erişimim yok, aracım yok."),
        tries,
        say("Ali, Zeynep, Mert, Deniz..."),
    )
    llm.add("yaver", say("Venture: Ali, Zeynep, Mert, Deniz..."))

    reply = await coordinator(llm).handle(session, TEXT, now=NOW)

    assert "hiçbir aracı denemedin" in suffixes[0]
    assert [s["tool"] for s in reply.trace][:2] == ["gave_up", "github_week_summary"]
    llm.assert_done()


async def test_naming_the_setting_is_not_a_give_up(session: AsyncSession) -> None:
    llm = ScriptedLLM()
    llm.add("intent", route_as(("startup", TEXT)))
    llm.add("startup", say("GITHUB_STARTUP_REPO ayarlı değil; .env'de owner/name olarak yaz."))
    llm.add("yaver", say("Venture: GITHUB_STARTUP_REPO ayarlı değil."))

    reply = await coordinator(llm).handle(session, TEXT, now=NOW)

    assert "gave_up" not in [s["tool"] for s in reply.trace]
    llm.assert_done()


async def test_a_give_up_after_trying_stays(session: AsyncSession) -> None:
    """A tool ran and failed: saying so is fine (no loop)."""
    llm = ScriptedLLM()
    llm.add("intent", route_as(("startup", TEXT)))
    llm.add(
        "startup", call("github_week_summary", week=99), say("Week 99 klasörü yok, yapamıyorum.")
    )
    llm.add("yaver", say("Venture: week99 yok."))

    reply = await coordinator(llm).handle(session, TEXT, now=NOW)

    assert "gave_up" not in [s["tool"] for s in reply.trace]
    llm.assert_done()
