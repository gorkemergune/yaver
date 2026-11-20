"""Team config validation, prompts, tool schemas (no database, no LLM)."""

import datetime as dt
import re
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from app.agent.context import ToolContext
from app.agent.team import COMMON_TOOLS, TeamConfig, build_team
from app.agent.tools import REGISTRY, json_schema, run_tool
from app.agent.tools.events import AddEventArgs
from app.agent.tools.matching import matches
from tests.agent_fakes import REPO_CONFIG, ScriptedLLM, coordinator, example_team
from tests.llm.fakes import make_config


def _example() -> dict[str, Any]:
    with (REPO_CONFIG / "agents.example.yaml").open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def test_example_team_loads() -> None:
    team = example_team()

    assert team.coordinator.can_delegate
    assert [a.id for a in team.agents] == ["academic", "agenda", "discipline"]
    assert [a.name for a in team.agents] == ["Atlas", "Nova", "Coach"]


def test_every_yaver_gets_the_common_tools_and_planned_ones_are_skipped() -> None:
    team = example_team()
    academic = team.get("academic")
    assert academic is not None

    names = [tool.name for tool in academic.tools]
    assert names[: len(COMMON_TOOLS)] == list(COMMON_TOOLS)
    assert "log_attendance" in names
    assert "search_materials" not in names  # Faz 3
    assert "resolve_date" in [t.name for t in team.coordinator.tools]


def test_unknown_tool_fails_at_load_time() -> None:
    data = _example()
    data["agents"][0]["tools"].append("launch_rockets")

    with pytest.raises(ValidationError, match=r"unknown tool.*launch_rockets"):
        TeamConfig.model_validate(data)


def test_only_the_coordinator_may_delegate() -> None:
    data = _example()
    data["agents"][1]["tools"].append("delegate")

    with pytest.raises(ValidationError, match="only the coordinator"):
        TeamConfig.model_validate(data)


def test_duplicate_names_rejected_case_insensitively() -> None:
    data = _example()
    data["agents"][1]["name"] = data["agents"][0]["name"].upper()

    with pytest.raises(ValidationError, match="duplicate yaver names"):
        TeamConfig.model_validate(data)


def test_unknown_tier_rejected_against_provider_config() -> None:
    data = _example()
    data["agents"][0]["tier"] = "turbo"

    with pytest.raises(ValueError, match="unknown tier"):
        build_team(TeamConfig.model_validate(data), "Görkem", make_config())


def test_prompts_list_the_team_and_stay_free_of_dates() -> None:
    team = example_team()

    prompt = team.coordinator.system_prompt
    assert 'agent_id "academic" = Atlas' in prompt
    assert "Görkem" in prompt
    assert "2026" not in prompt  # per-day context goes into the uncached suffix
    agent_prompt = team.agents[0].system_prompt
    assert "Atlas" in agent_prompt
    assert "resolve_date" in agent_prompt


def test_delegate_spec_lists_agent_ids() -> None:
    spec = example_team().delegate_spec()

    assert spec.parameters["properties"]["agent_id"]["enum"] == ["academic", "agenda", "discipline"]


@pytest.mark.parametrize(
    ("text", "addressed"),
    [
        ("Atlas, yarın ne var?", ("academic", "yarın ne var?")),
        ("atlas: yarın ne var?", ("academic", "yarın ne var?")),
        ("ATLAS,yarın ne var?", ("academic", "yarın ne var?")),
        ("Coach! bugün spora gidemem", ("discipline", "bugün spora gidemem")),
        ("Yaver, yarın ne var?", None),  # the coordinator itself: normal flow
        ("Yarın ne var?", None),
        ("Bugün, linear iptal", None),  # "Bugün" is not a yaver
    ],
)
def test_addressing_a_yaver_by_name(text: str, addressed: tuple[str, str] | None) -> None:
    result = coordinator(ScriptedLLM()).addressed_member(text)

    assert (None if result is None else (result[0].id, result[1])) == addressed


def test_tool_schema_keeps_fields_named_title_and_flattens_optionals() -> None:
    schema = json_schema(AddEventArgs)

    assert schema["properties"]["title"] == {"type": "string"}
    start_time = schema["properties"]["start_time"]
    assert start_time["type"] == ["string", "null"]  # models send null for unused fields
    assert "anyOf" not in start_time
    # Not format=time: Groq validates that as RFC 3339 and rejects "09:00".
    assert "format" not in start_time
    assert re.fullmatch(start_time["pattern"], "09:00")
    assert not re.fullmatch(start_time["pattern"], "9:00")
    assert schema["properties"]["date"]["format"] == "date"
    assert schema["required"] == ["kind", "title", "date"]
    assert schema["additionalProperties"] is False


def test_every_registered_tool_has_a_valid_schema() -> None:
    for tool in REGISTRY.values():
        params = tool.spec().parameters
        assert params["type"] == "object", tool.name
        assert "$defs" not in str(params), tool.name


async def test_relative_dates_are_rejected_by_tools() -> None:
    ctx = ToolContext(
        session=MagicMock(),
        now=dt.datetime(2026, 11, 23, tzinfo=dt.UTC),
        tz=dt.UTC,  # type: ignore[arg-type]
        change_set_id=uuid.uuid4(),
        recorder=MagicMock(),
    )

    result = await run_tool("get_day_plan", {"date": "yarın"}, ctx)

    assert "error" in result
    assert "resolve_date" in result["error"]


async def test_unknown_tool_is_an_error_result() -> None:
    result = await run_tool("format_disk", {}, MagicMock())

    assert result == {"error": "unknown tool format_disk"}


@pytest.mark.parametrize(
    ("query", "names", "expected"),
    [
        ("linear", ("Linear Algebra",), True),
        ("Linear", ("linear algebra",), True),
        ("EE211", ("EE211 Lab",), True),
        ("ee 211", ("EE211",), True),
        ("ee211 lab", ("EE211 Lab", "lab"), True),
        ("spor", ("Spor", "sport"), True),
        ("spora", ("Spor",), True),  # Turkish dative suffix
        ("linear", ("EE211 Lab",), False),
        ("", ("Spor",), False),
    ],
)
def test_matching(query: str, names: tuple[str, ...], expected: bool) -> None:
    assert matches(query, *names) is expected


def test_a_model_without_its_provider_is_rejected() -> None:
    data = _example()
    data["agents"][0]["model"] = "openai/gpt-oss-20b"  # old format: provider unknown

    with pytest.raises(ValidationError, match=r"model: \{groq: openai/gpt-oss-20b\}"):
        TeamConfig.model_validate(data)


def test_per_yaver_model_override() -> None:
    from app.agent.team import model_overrides

    data = _example()
    config = TeamConfig.model_validate(data)
    team = build_team(config, "Görkem")
    providers = make_config(
        tiers={
            "fast": {"provider": "groq", "model": "big"},
            "fallback": {"provider": "claude", "model": "haiku"},
            "smart": {"provider": "claude", "model": "sonnet"},
            "local": {"provider": "ollama", "model": "local-model"},
        }
    )

    assert team.coordinator.model == {}
    assert [dict(a.model) for a in team.agents] == [{"groq": "openai/gpt-oss-20b"}] * 3
    assert model_overrides(config, providers) == [
        ("academic model", "groq", "openai/gpt-oss-20b"),
        ("agenda model", "groq", "openai/gpt-oss-20b"),
        ("discipline model", "groq", "openai/gpt-oss-20b"),
    ]


def test_fast_path_tools_go_to_the_coordinator() -> None:
    team = example_team()

    names = [tool.name for tool in team.coordinator.tools]
    assert {"cancel_block_on", "add_event", "add_task"} <= set(names)
    assert "log_attendance" not in names  # attendance goes to the classes yaver (hour rules)
    assert "Fast path" in team.coordinator.system_prompt


def test_unknown_fast_path_tool_is_rejected() -> None:
    data = _example()
    data["coordinator"]["fast_path_tools"] = ["search_materials"]  # planned, not built

    with pytest.raises(ValidationError, match="fast_path_tools"):
        TeamConfig.model_validate(data)


def test_no_fast_path_means_no_fast_path_rule() -> None:
    data = _example()
    data["coordinator"]["fast_path_tools"] = []

    team = build_team(TeamConfig.model_validate(data), "Görkem")

    assert "Fast path" not in team.coordinator.system_prompt
    assert "cancel_block_on" not in [t.name for t in team.coordinator.tools]


def test_prompts_allow_only_today_and_tomorrow_from_the_calendar() -> None:
    team = example_team()

    for prompt in (team.coordinator.system_prompt, team.agents[0].system_prompt):
        assert '"bugün"' in prompt
        assert '"yarın"' in prompt
        assert "resolve_date" in prompt
