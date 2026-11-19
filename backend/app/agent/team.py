"""The Yaver team from config/agents(.example).yaml, validated at load time."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.tools import PLANNED_TOOLS, REGISTRY, Tool
from app.core.time_resolver import normalize
from app.core.yaml_config import load_yaml_config
from app.llm.config import ProvidersConfig, load_providers_config
from app.llm.types import ToolSpec

DELEGATE = "delegate"
# Every specialist can read dates and the plan, whatever agents.yaml lists.
COMMON_TOOLS = ("resolve_date", "get_day_plan")
PROMPTS_DIR = Path(__file__).with_name("prompts")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemberConfig(_Strict):
    id: str
    name: str
    persona: str
    tier: str = "fast"
    tools: list[str] = Field(default_factory=list)


class AgentConfig(MemberConfig):
    domain: str
    briefing_section: str | None = None


class WeeklyPlanConfig(_Strict):
    tier: str = "smart"
    order: list[str] = Field(default_factory=list)


class TeamConfig(_Strict):
    coordinator: MemberConfig
    agents: list[AgentConfig]
    weekly_plan: WeeklyPlanConfig = Field(default_factory=WeeklyPlanConfig)
    briefing_style: str = "sections"

    @model_validator(mode="after")
    def _check(self) -> "TeamConfig":
        members = [self.coordinator, *self.agents]
        ids = [m.id for m in members]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate yaver ids: {ids}")
        names = [normalize(m.name) for m in members]
        if len(set(names)) != len(names):
            raise ValueError("duplicate yaver names")
        known = set(REGISTRY) | set(PLANNED_TOOLS) | {DELEGATE}
        for member in members:
            unknown = [t for t in member.tools if t not in known]
            if unknown:
                raise ValueError(f"{member.id}: unknown tool(s) {', '.join(unknown)}")
        if any(DELEGATE in agent.tools for agent in self.agents):
            raise ValueError("only the coordinator may delegate (delegation depth is 1)")
        unknown_order = [a for a in self.weekly_plan.order if a not in ids]
        if unknown_order:
            raise ValueError(f"weekly_plan.order: unknown yaver(s) {unknown_order}")
        return self


@dataclass(frozen=True, slots=True)
class Member:
    id: str
    name: str
    tier: str
    system_prompt: str  # stable: cached by the provider
    tools: tuple[Tool, ...]
    can_delegate: bool = False
    domain: str = ""

    def tool_specs(self, delegate_spec: ToolSpec | None = None) -> list[ToolSpec]:
        specs = [tool.spec() for tool in self.tools]
        if self.can_delegate and delegate_spec is not None:
            specs.insert(0, delegate_spec)
        return specs


@dataclass(frozen=True, slots=True)
class Team:
    coordinator: Member
    agents: tuple[Member, ...]

    def get(self, agent_id: str) -> Member | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def by_name(self, word: str) -> Member | None:
        key = normalize(word)
        for member in (self.coordinator, *self.agents):
            if key in (normalize(member.name), normalize(member.id)):
                return member
        return None

    def delegate_spec(self) -> ToolSpec:
        return ToolSpec(
            DELEGATE,
            "Hand one part of the user's request to the yaver responsible for it and get "
            "their result. One call per yaver; include every detail they need, with the "
            "user's own words for dates and times.",
            {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "enum": [a.id for a in self.agents]},
                    "instruction": {
                        "type": "string",
                        "description": "what this yaver should do, in Turkish",
                    },
                },
                "required": ["agent_id", "instruction"],
                "additionalProperties": False,
            },
        )


def _tools(names: list[str], extra: tuple[str, ...]) -> tuple[Tool, ...]:
    ordered = [n for n in dict.fromkeys([*extra, *names]) if n in REGISTRY]
    return tuple(REGISTRY[n] for n in ordered)


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        autoescape=False,  # plain-text prompts, not HTML
    )


def build_team(
    config: TeamConfig, user_name: str, providers: ProvidersConfig | None = None
) -> Team:
    if providers is not None:
        tiers = [m.tier for m in (config.coordinator, *config.agents)] + [config.weekly_plan.tier]
        unknown = sorted({t for t in tiers if t not in providers.tiers})
        if unknown:
            raise ValueError(f"agents.yaml uses unknown tier(s): {', '.join(unknown)}")
    env = _environment()
    context: dict[str, Any] = {
        "user_name": user_name or "kullanıcı",
        "coordinator": config.coordinator,
        "agents": config.agents,
    }
    coordinator = Member(
        id=config.coordinator.id,
        name=config.coordinator.name,
        tier=config.coordinator.tier,
        system_prompt=env.get_template("coordinator.md.j2").render(**context).strip(),
        tools=_tools(config.coordinator.tools, ("resolve_date",)),
        can_delegate=DELEGATE in config.coordinator.tools,
    )
    agents = tuple(
        Member(
            id=agent.id,
            name=agent.name,
            tier=agent.tier,
            system_prompt=env.get_template("agent.md.j2").render(agent=agent, **context).strip(),
            tools=_tools(agent.tools, COMMON_TOOLS),
            domain=agent.domain,
        )
        for agent in config.agents
    )
    return Team(coordinator, agents)


def load_team_config() -> TeamConfig:
    return TeamConfig.model_validate(load_yaml_config("agents"))


@lru_cache
def get_team() -> Team:
    from app.config import get_settings

    return build_team(load_team_config(), get_settings().app_user_name, load_providers_config())
