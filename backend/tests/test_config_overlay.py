"""agents.yaml / providers.yaml are laid over their example files: capabilities (tools,
shift jobs, routing purposes) come from the example, the personal file changes names,
colours, personas, hours and which model a tier uses. Live: a personal agents.yaml copied
before the GitHub tools existed left Venture saying "aracım yok"."""

import logging
from pathlib import Path

import pytest

from app.agent.team import TeamConfig, overlay_agents
from app.core import config_problems, yaml_config
from app.core.yaml_config import load_validated
from app.llm.config import ProvidersConfig, overlay_providers

EXAMPLE_AGENTS = """
office: {daily_budget_usd: 0.20, open_at: "08:00", close_at: "23:00"}
coordinator:
  id: yaver
  name: Yaver
  persona: koordinatör
  shift: gün boyu
  tools: [delegate, get_day_plan]
agents:
  - id: academic
    name: Scholar
    role: Akademik
    color: "#4cbcff"
    domain: Dersler
    persona: düzenli
    tools: [search_materials, get_syllabus, get_exam_scope]
    shift_jobs:
      - {job: source_watch, at: "08:20", title: Ders notları}
  - id: startup
    name: Venture
    domain: Startup
    persona: meraklı
    tools: [web_search, add_task]
    shift_jobs:
      - {job: github_watch, at: "08:15"}
      - {job: web_scan, at: "08:30", topics: [girişim haberleri]}
  - id: content
    name: Creator
    domain: İçerik
    persona: yaratıcı
    tools: [add_task]
weekly_plan: {tier: smart, order: [academic]}
"""

# made months ago: old tool lists, no source_watch, its own names / colours / topics
PERSONAL_AGENTS = """
office: {close_at: "01:00"}
coordinator:
  id: yaver
  name: Patron
  persona: kısa konuşur
  tools: [delegate]
agents:
  - id: academic
    name: Hoca
    color: "#0ea5e9"
    domain: Dersler (Yeditepe)
    persona: sert
    tools: [search_materials]
    tier: smart
  - id: startup
    name: Venture
    domain: Startup - Nexa Lab işleri
    persona: meraklı
    tools: [web_search]
    shift_jobs:
      - {job: web_scan, at: "07:00", topics: [Nexa Lab rakipleri]}
      - {job: ads_report, at: "09:00"}
    favourite_food: pizza
  - id: research
    name: Sherlock
    domain: Araştırma
    persona: meraklı
    tools: [web_search]
"""


@pytest.fixture
def no_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yaml_config, "_warned", set())  # each test sees its own warnings
    config_problems.clear_source("agents.yaml")
    config_problems.clear_source("providers.yaml")


def agents_problems() -> list[dict[str, str | None]]:
    return [p for p in config_problems.problems() if p["source"] == "agents.yaml"]


def _team(tmp_path: Path, personal: str | None) -> TeamConfig:
    (tmp_path / "agents.example.yaml").write_text(EXAMPLE_AGENTS, encoding="utf-8")
    if personal is not None:
        (tmp_path / "agents.yaml").write_text(personal, encoding="utf-8")
    return load_validated("agents", TeamConfig, tmp_path, overlay=overlay_agents)


def test_tools_and_shift_jobs_come_from_the_example(tmp_path: Path, no_problems: None) -> None:
    team = _team(tmp_path, PERSONAL_AGENTS)
    academic, startup, content = team.agents

    assert academic.tools == ["search_materials", "get_syllabus", "get_exam_scope"]
    assert [j.job for j in academic.shift_jobs] == ["source_watch"]
    assert academic.tier == "fast"  # a capability: the personal "smart" is ignored
    assert team.coordinator.tools == ["delegate", "get_day_plan"]
    # both of the example's jobs; the personal web_scan only changes its time and topics
    assert [(j.job, j.at, j.topics) for j in startup.shift_jobs] == [
        ("github_watch", "08:15", []),
        ("web_scan", "07:00", ["Nexa Lab rakipleri"]),
    ]
    assert content.name == "Creator"  # not in the personal file: the example's
    assert [a.id for a in team.agents] == ["academic", "startup", "content"]  # no "research"
    assert agents_problems() == []


def test_the_personal_file_keeps_what_is_shown(tmp_path: Path, no_problems: None) -> None:
    team = _team(tmp_path, PERSONAL_AGENTS)
    academic, startup, _ = team.agents

    assert (academic.name, academic.color, academic.persona) == ("Hoca", "#0ea5e9", "sert")
    assert academic.domain == "Dersler (Yeditepe)"
    assert academic.role == "Akademik"  # not set personally: the example's
    assert startup.domain == "Startup - Nexa Lab işleri"
    assert (team.coordinator.name, team.coordinator.persona) == ("Patron", "kısa konuşur")
    assert team.coordinator.shift == "gün boyu"
    assert (team.office.open_at, team.office.close_at) == ("08:00", "01:00")


def test_what_differs_is_logged_once(
    tmp_path: Path, no_problems: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.config"):
        _team(tmp_path, PERSONAL_AGENTS)
        _team(tmp_path, PERSONAL_AGENTS)
    lines = [r.getMessage() for r in caplog.records]
    text = "\n".join(lines)

    assert len(lines) == len(set(lines))  # the second load logs nothing new
    assert "academic: tools, tier ignored, from the example" in text
    assert "academic: role, shift_jobs not set, from the example" in text
    assert "startup.favourite_food: unknown, ignored" in text
    assert "startup: shift job ads_report is not in the example, ignored" in text
    assert "startup: shift job github_watch not set, from the example" in text
    assert "agents: research is not in the example, ignored" in text
    assert "agents: content not in the personal file, from the example" in text


def test_without_a_personal_file_the_example_is_used(tmp_path: Path) -> None:
    team = _team(tmp_path, None)

    assert team.agents[0].name == "Scholar"


def test_a_broken_personal_file_still_falls_back(tmp_path: Path, no_problems: None) -> None:
    team = _team(tmp_path, PERSONAL_AGENTS.replace('color: "#0ea5e9"', "color: blue"))

    assert team.agents[0].name == "Scholar"  # the example, whole
    [problem] = agents_problems()
    assert problem["source"] == "agents.yaml"
    assert "color" in str(problem["message"])


EXAMPLE_PROVIDERS = """
tiers:
  fast: {provider: groq, model: openai/gpt-oss-120b}
  fallback:
    provider: anthropic
    model: claude-haiku-5-5
    options: {thinking: {type: disabled}}
  smart: {provider: anthropic, model: claude-sonnet-5-5}
providers:
  groq: {type: openai_compat, base_url: "https://api.groq.com/openai/v1", api_key_env: GROQ_API_KEY}
  anthropic: {type: anthropic, api_key_env: ANTHROPIC_API_KEY}
routing:
  default: fast
  failover_chain: [fast, fallback]
  purposes: {weekly_plan: smart, material_map: smart, image_read: fallback}
budget:
  downgrade: {smart: fallback}
  allowed_at_limit: [fast]
"""

# own Claude key: Haiku first, Groq behind it; made before material_map existed
PERSONAL_PROVIDERS = """
tiers:
  fast:
    provider: anthropic
    model: claude-haiku-5-5
    options: {thinking: {type: disabled}}
  fallback: {provider: groq, model: openai/gpt-oss-120b}
routing:
  default: fast
  failover_chain: [fast, fallback]
  purposes: {weekly_plan: smart, image_read: fast}
budget:
  downgrade: {smart: fast}
  allowed_at_limit: [fallback]
"""


def test_providers_overlay(
    tmp_path: Path, no_problems: None, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "providers.example.yaml").write_text(EXAMPLE_PROVIDERS, encoding="utf-8")
    (tmp_path / "providers.yaml").write_text(PERSONAL_PROVIDERS, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="app.config"):
        config = load_validated("providers", ProvidersConfig, tmp_path, overlay=overlay_providers)

    # a tier is replaced whole: the Groq fallback does not inherit Haiku's thinking option
    assert (config.tiers["fast"].provider, config.tiers["fast"].options) == (
        "anthropic",
        {"thinking": {"type": "disabled"}},
    )
    assert (config.tiers["fallback"].provider, config.tiers["fallback"].options) == ("groq", {})
    assert config.tiers["smart"].model == "claude-sonnet-5-5"  # not set: the example's
    assert config.providers["groq"].api_key_env == "GROQ_API_KEY"
    assert config.routing.purposes == {
        "weekly_plan": "smart",
        "material_map": "smart",  # new purpose, from the example
        "image_read": "fast",  # the personal choice
    }
    assert config.budget.downgrade == {"smart": "fast"}
    assert config.budget.allowed_at_limit == ["fallback"]
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "routing.purposes: material_map not set, from the example" in text
