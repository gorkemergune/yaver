"""The Yaver team from config/agents(.example).yaml, validated at load time."""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.tools import PLANNED_TOOLS, REGISTRY, Tool
from app.core.time_resolver import normalize
from app.core.yaml_config import load_validated
from app.llm.config import ProvidersConfig, load_providers_config
from app.llm.types import ToolSpec

DELEGATE = "delegate"
ONBOARDING_TOOLS = (
    "resolve_date",
    "add_term",
    "add_holiday",
    "propose_schedule",
    "apply_proposal",
    "set_absence_limit",
    "set_attendance_baseline",
    "add_recurring_block",
    "remember",
    "get_week_plan",
    "finish_onboarding",
)
# Every specialist can read dates and the plan and keep its notebook, whatever agents.yaml
# lists; the coordinator can read any notebook ("Scholar'ın defterinde ne var?").
# A plain one-off calendar event (breakfast, appointment) any of them can add itself;
# anything else outside its area goes back with `handoff`.
COMMON_TOOLS = ("resolve_date", "get_day_plan", "add_event", "add_note", "get_notes", "handoff")
COORDINATOR_COMMON_TOOLS = ("resolve_date", "get_notes")
DESK_COLUMNS = 5  # the office has 5 desk pairs: back 0-4, front 0-4
HHMM_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"  # local wall-clock time
# Where the default team sits when agents.yaml names no desk (the approved prototype).
DEFAULT_DESKS: dict[str, tuple[str, int]] = {
    "academic": ("back", 0),
    "career": ("back", 1),
    "startup": ("back", 2),
    "ads": ("back", 3),
    "research": ("back", 4),
    "content": ("front", 0),
    "social": ("front", 1),
    "agenda": ("front", 2),
    "discipline": ("front", 3),
}
PROMPTS_DIR = Path(__file__).with_name("prompts")
COORDINATOR_COLOR = "#6366f1"
AGENT_COLORS = ("#0ea5e9", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6", "#ef4444")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeskConfig(_Strict):
    row: Literal["office", "back", "front"]
    col: int = Field(0, ge=0, lt=DESK_COLUMNS)


# Shift jobs an employee can be given in agents.yaml (implemented in app.office.shift_jobs).
SHIFT_JOB_KINDS = (
    "web_scan",  # search the web for `topics`, note the top results
    "ads_report",  # Meta ad metrics (skeleton: notes that the integration is pending)
    "social_reminders",  # birthdays / plans in the next days
    "followup_watch",  # follow-ups still waiting for an answer
    "deadline_watch",  # deadlines in the next days
    "github_watch",  # the startup repo (read only): week hand-ins, dated items, reminders
    "content_calendar",  # Creator: next week's post drafts (one LLM call; nothing is posted)
    "source_watch",  # Scholar: shared course notes (a model reads only new / changed tabs)
)


class ShiftJobConfig(_Strict):
    job: Literal[
        "web_scan",
        "ads_report",
        "social_reminders",
        "followup_watch",
        "deadline_watch",
        "github_watch",
        "content_calendar",
        "source_watch",
    ]
    at: str = Field(pattern=HHMM_PATTERN)  # local time
    weekday: int | None = Field(None, ge=0, le=6)  # 0 = Monday; None = every day
    title: str = ""  # shown while it runs ("Sabah rakip taraması")
    topics: list[str] = Field(default_factory=list)  # web_scan: what to search

    @model_validator(mode="after")
    def _topics(self) -> "ShiftJobConfig":
        if self.job == "web_scan" and not self.topics:
            raise ValueError("web_scan needs topics")
        return self


class MemberConfig(_Strict):
    id: str
    name: str
    persona: str
    role: str = ""  # office title, e.g. "Akademik"
    desk: DeskConfig | None = None  # default: DEFAULT_DESKS, then the first free desk
    shift: str = ""  # the shift plan shown in the office panel
    daily_budget_usd: Decimal | None = Field(None, ge=0)  # default: office.daily_budget_usd
    shift_jobs: list[ShiftJobConfig] = Field(default_factory=list)
    tier: str = "fast"
    # Optional, per provider: {groq: openai/gpt-oss-20b} = whenever this yaver's call runs on
    # Groq (fast or fallback tier), use that model. Other providers keep the tier's model.
    # Groq rate limits are per model, so this also spreads the load.
    model: dict[str, str] = Field(default_factory=dict)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")  # label colour in the UI
    tools: list[str] = Field(default_factory=list)
    # The user's own names for this area ("Nexa Lab" for the startup): routing reads them
    keywords: list[str] = Field(default_factory=list)

    @field_validator("model", mode="before")
    @classmethod
    def _model_per_provider(cls, value: Any) -> Any:
        if isinstance(value, str):
            raise ValueError(
                f"model must name its provider, e.g. model: {{groq: {value}}} "
                "(fast may be Claude in your providers.yaml)"
            )
        return value if value is not None else {}


class AgentConfig(MemberConfig):
    domain: str
    briefing_section: str | None = None


class CoordinatorConfig(MemberConfig):
    # fast_path: tools the coordinator may call itself for a simple one-area message,
    # saving the delegate round trip. Keep it short: every schema costs tokens per call.
    fast_path_tools: list[str] = Field(default_factory=list)


class OfficeConfig(_Strict):
    # Per employee per local day (llm_usage of its agent_id). Over it, its shift jobs stop.
    daily_budget_usd: Decimal = Field(Decimal("0.50"), ge=0)
    # Office hours (local time, O5): outside them an idle employee is "off" (gone home,
    # its desk dark) and a request brings it in for a night shift. Equal = always open.
    open_at: str = Field("08:00", pattern=HHMM_PATTERN)
    close_at: str = Field("23:00", pattern=HHMM_PATTERN)


class WeeklyPlanConfig(_Strict):
    tier: str = "smart"
    order: list[str] = Field(default_factory=list)


class TeamConfig(_Strict):
    coordinator: CoordinatorConfig
    agents: list[AgentConfig]
    weekly_plan: WeeklyPlanConfig = Field(default_factory=WeeklyPlanConfig)
    briefing_style: str = "sections"
    office: OfficeConfig = Field(default_factory=OfficeConfig)

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
        bad_fast_path = [
            t for t in self.coordinator.fast_path_tools if t not in REGISTRY or t == DELEGATE
        ]
        if bad_fast_path:
            raise ValueError(f"fast_path_tools: unknown or not available {bad_fast_path}")
        if any(DELEGATE in agent.tools for agent in self.agents):
            raise ValueError("only the coordinator may delegate (delegation depth is 1)")
        unknown_order = [a for a in self.weekly_plan.order if a not in ids]
        if unknown_order:
            raise ValueError(f"weekly_plan.order: unknown yaver(s) {unknown_order}")
        if any(a.desk is not None and a.desk.row == "office" for a in self.agents):
            raise ValueError("desk row 'office' is the coordinator's room")
        desks = [(a.desk.row, a.desk.col) for a in self.agents if a.desk is not None]
        if len(set(desks)) != len(desks):
            raise ValueError(f"two employees at one desk: {desks}")
        return self

    def desks(self) -> dict[str, tuple[str, int]]:
        """Employee id -> (row, col): agents.yaml, the default layout, then free desks
        (back row first)."""
        placed: dict[str, tuple[str, int]] = {self.coordinator.id: ("office", 0)}
        for agent in self.agents:
            if agent.desk is not None:
                placed[agent.id] = (agent.desk.row, agent.desk.col)
        taken = set(placed.values())
        for agent in self.agents:
            default = DEFAULT_DESKS.get(agent.id)
            if agent.id not in placed and default is not None and default not in taken:
                placed[agent.id] = default
                taken.add(default)
        free = [
            desk
            for row in ("back", "front")
            for col in range(DESK_COLUMNS)
            if (desk := (row, col)) not in taken
        ]
        for agent in self.agents:
            if agent.id not in placed:
                if not free:
                    raise ValueError("more employees than desks")
                placed[agent.id] = free.pop(0)
        return placed


@dataclass(frozen=True, slots=True)
class Member:
    id: str
    name: str
    tier: str
    system_prompt: str  # stable: cached by the provider
    tools: tuple[Tool, ...]
    can_delegate: bool = False
    domain: str = ""
    model: Mapping[str, str] = field(default_factory=dict)  # provider -> model
    color: str = "#6366f1"
    role: str = ""  # office title ("Akademik")
    keywords: tuple[str, ...] = ()  # the user's names for its area (routing)

    def tool_specs(self, delegate_spec: ToolSpec | None = None) -> list[ToolSpec]:
        specs = [tool.spec() for tool in self.tools]
        if self.can_delegate and delegate_spec is not None:
            specs.insert(0, delegate_spec)
        return specs


@dataclass(frozen=True, slots=True)
class Team:
    coordinator: Member
    agents: tuple[Member, ...]
    onboarding: Member | None = None  # first-run setup assistant (speaks as the coordinator)

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
    by_id = {agent.id: agent.name for agent in config.agents}
    first = config.agents[0].name if config.agents else config.coordinator.name
    context: dict[str, Any] = {
        "user_name": user_name,
        "coordinator": config.coordinator,
        "agents": config.agents,
        # names for the answer examples, by area (the list order changes as the team grows)
        "example": {
            "classes": by_id.get("academic", first),
            "meetings": by_id.get(
                "agenda", config.agents[1].name if len(config.agents) > 1 else first
            ),
            "sport": by_id.get("discipline", config.agents[-1].name if config.agents else first),
            "sport_id": "discipline" if "discipline" in by_id else "",
        },
    }
    coordinator = Member(
        id=config.coordinator.id,
        name=config.coordinator.name,
        tier=config.coordinator.tier,
        system_prompt=env.get_template("coordinator.md.j2").render(**context).strip(),
        tools=_tools(
            [*config.coordinator.tools, *config.coordinator.fast_path_tools],
            COORDINATOR_COMMON_TOOLS,
        ),
        can_delegate=DELEGATE in config.coordinator.tools,
        model=config.coordinator.model,
        color=config.coordinator.color or COORDINATOR_COLOR,
    )
    agents = tuple(
        Member(
            id=agent.id,
            name=agent.name,
            tier=agent.tier,
            system_prompt=env.get_template("agent.md.j2").render(agent=agent, **context).strip(),
            tools=_tools(agent.tools, COMMON_TOOLS),
            domain=agent.domain,
            model=agent.model,
            color=agent.color or AGENT_COLORS[index % len(AGENT_COLORS)],
            role=agent.role or (agent.briefing_section or ""),
            keywords=tuple(agent.keywords),
        )
        for index, agent in enumerate(config.agents)
    )
    onboarding = Member(
        id="onboarding",
        name=config.coordinator.name,
        tier=config.coordinator.tier,
        system_prompt=env.get_template("onboarding.md.j2").render(**context).strip(),
        tools=_tools(list(ONBOARDING_TOOLS), ()),
        model=config.coordinator.model,
        color=coordinator.color,
    )
    return Team(coordinator, agents, onboarding)


def model_overrides(config: TeamConfig, providers: ProvidersConfig) -> list[tuple[str, str, str]]:
    """(target, provider, model) for every yaver with its own model, for model checks."""
    return [
        (f"{member.id} model", provider, model)
        for member in (config.coordinator, *config.agents)
        for provider, model in member.model.items()
        if provider in providers.providers
    ]


# What a personal agents.yaml may change: how an employee looks and talks, its desk, its
# area text and budget; office hours and the briefing style. Capabilities - tools, which
# shift jobs run, tier / model, the weekly plan - always come from agents.example.yaml, so
# an old personal copy never hides a new tool (live: Venture without its GitHub tools).
MEMBER_OWN = (
    "name",
    "role",
    "color",
    "persona",
    "shift",
    "desk",
    "domain",
    "daily_budget_usd",
    "keywords",
)
SHIFT_JOB_OWN = ("at", "weekday", "title", "topics")  # of a shift job the example has
TOP_OWN = ("office", "briefing_style")


def overlay_agents(base: dict[str, Any], local: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    """agents.yaml laid over agents.example.yaml (load_validated overlay)."""
    merged = copy.deepcopy(base)
    for key, value in local.items():
        if key in ("coordinator", "agents"):
            continue
        if key in TOP_OWN:
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merged[key] = {**base[key], **value}
            else:
                merged[key] = value
        elif key not in TeamConfig.model_fields:
            notes.append(f"{key}: unknown, ignored")
        elif value != base.get(key):
            notes.append(f"{key}: ignored, it comes from the example")
    if isinstance(local.get("coordinator"), dict):
        merged["coordinator"] = _overlay_member(
            base["coordinator"], local["coordinator"], notes, "coordinator"
        )
    mine = {a.get("id"): a for a in local.get("agents") or [] if isinstance(a, dict)}
    if "agents" in local:
        known = {a["id"] for a in base.get("agents", [])}
        for agent_id in mine:
            if agent_id not in known:
                notes.append(f"agents: {agent_id} is not in the example, ignored")
        merged["agents"] = []
        for agent in base.get("agents", []):
            if agent["id"] in mine:
                merged["agents"].append(
                    _overlay_member(agent, mine[agent["id"]], notes, agent["id"])
                )
            else:
                notes.append(f"agents: {agent['id']} not in the personal file, from the example")
                merged["agents"].append(copy.deepcopy(agent))
    return merged


def _overlay_member(
    base: dict[str, Any], local: dict[str, Any], notes: list[str], who: str
) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    fields = AgentConfig.model_fields.keys() | CoordinatorConfig.model_fields.keys()
    ignored = []
    for key, value in local.items():
        if key == "id":
            continue
        if key in MEMBER_OWN:
            merged[key] = value
        elif key == "shift_jobs":
            merged[key] = _overlay_jobs(base.get(key) or [], value or [], notes, who)
        elif key not in fields:
            notes.append(f"{who}.{key}: unknown, ignored")
        elif value != base.get(key):
            ignored.append(key)
    if ignored:
        notes.append(f"{who}: {', '.join(ignored)} ignored, from the example")
    missing = [key for key in MEMBER_OWN if key in base and key not in local]
    if base.get("shift_jobs") and "shift_jobs" not in local:
        missing.append("shift_jobs")
    if missing:
        notes.append(f"{who}: {', '.join(missing)} not set, from the example")
    return merged


def _overlay_jobs(
    base: list[dict[str, Any]], local: list[Any], notes: list[str], who: str
) -> list[dict[str, Any]]:
    """The example's shift jobs; a personal entry of the same kind (the n-th web_scan to the
    n-th web_scan) changes its time, day, title and topics."""
    mine: dict[str, list[dict[str, Any]]] = {}
    for job in local:
        if isinstance(job, dict):
            mine.setdefault(str(job.get("job")), []).append(job)
    merged = []
    for job in base:
        own = mine.get(job["job"]) or []
        if own:
            change = own.pop(0)
            merged.append({**job, **{k: v for k, v in change.items() if k in SHIFT_JOB_OWN}})
        else:
            notes.append(f"{who}: shift job {job['job']} not set, from the example")
            merged.append(dict(job))
    for kind, extra in mine.items():
        if extra:
            notes.append(f"{who}: shift job {kind} is not in the example, ignored")
    return merged


def load_team_config() -> TeamConfig:
    return load_validated("agents", TeamConfig, overlay=overlay_agents)


@lru_cache
def get_team() -> Team:
    from app.config import get_settings

    return build_team(load_team_config(), get_settings().app_user_name, load_providers_config())
