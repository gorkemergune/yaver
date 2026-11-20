"""Tool registry. One module per area; each tool = Pydantic args model + async handler.

Tools only accept ISO dates (YYYY-MM-DD) and HH:MM times. Relative expressions ("yarın")
go through `resolve_date` first, so date math never happens in the model.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.context import ToolContext
from app.llm.types import ToolSpec

ToolResult = dict[str, Any]
HHMM_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
Handler = Callable[[Any, ToolContext], Awaitable[ToolResult]]


class ToolError(Exception):
    """Expected failure the model should see and act on (ambiguous match, not found...)."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler
    mutates: bool

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, json_schema(self.args))


REGISTRY: dict[str, Tool] = {}

# Named in agents.yaml but built in a later phase: skipped (not offered), not an error.
PLANNED_TOOLS = {
    "log_workout": "Faz 1",
    "set_app_limit": "Faz 4",
    "grant_limit_extension": "Faz 4",
}


def tool(
    name: str, description: str, args: type[BaseModel], *, mutates: bool = False
) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        if name in REGISTRY:
            raise ValueError(f"tool {name!r} registered twice")
        REGISTRY[name] = Tool(name, description, args, handler, mutates)
        return handler

    return register


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Compact JSON schema: no titles, enums inlined (Literal types), no $defs."""
    schema = model.model_json_schema()

    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        # Optional fields: {"anyOf": [X, {"type": "null"}]} -> X with type [t, "null"].
        # Models often send null for unused optional fields and Groq validates the schema
        # server-side, so null must stay allowed.
        options = node.get("anyOf")
        if isinstance(options, list) and len(options) == 2 and {"type": "null"} in options:
            merged = {k: v for k, v in node.items() if k != "anyOf"}
            merged.update(next(o for o in options if o != {"type": "null"}))
            if isinstance(merged.get("type"), str):
                merged["type"] = [merged["type"], "null"]
            node = merged
        if node.get("format") == "time":
            # JSON-schema "time" is RFC 3339 (09:00:00+00:00) and providers that validate
            # server-side (Groq) reject "09:00"; we want HH:MM.
            node = {k: v for k, v in node.items() if k != "format"}
            node["pattern"] = HHMM_PATTERN
        return {
            key: clean(value)
            for key, value in node.items()
            # Drop schema annotations only: a property *named* "title" is a dict, keep it.
            if not (key in ("title", "default") and not isinstance(value, dict))
        }

    cleaned: dict[str, Any] = clean(schema)
    cleaned.setdefault("properties", {})
    cleaned["additionalProperties"] = False
    return cleaned


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        where = ".".join(str(loc) for loc in error["loc"]) or "arguments"
        parts.append(f"{where}: {error['msg']}")
    hint = ""
    if any(e["type"].startswith(("date", "time")) for e in exc.errors()):
        hint = " Dates must be YYYY-MM-DD and times HH:MM; call resolve_date for phrases."
    return "; ".join(parts) + hint


WAITS_FOR_PROPOSAL = frozenset({"add_event", "add_recurring_block"})


async def run_tool(name: str, arguments: dict[str, Any] | None, ctx: ToolContext) -> ToolResult:
    """Execute a tool call; errors come back as {"error": ...} for the model to handle."""
    tool_ = REGISTRY.get(name)
    if tool_ is None:
        return {"error": f"unknown tool {name}"}
    if name in WAITS_FOR_PROPOSAL and ctx.new_proposals:
        # What an image of this message shows is already a proposal; adding it directly
        # would skip the user's confirmation (and duplicate it after "evet").
        return {
            "error": "this message's image was turned into a proposal: show its table and "
            "ask; it is added after the user confirms (apply_proposal)"
        }
    try:
        args = tool_.args.model_validate(arguments or {})
    except ValidationError as exc:
        return {"error": _validation_message(exc)}
    try:
        result = await tool_.handler(args, ctx)
    except ToolError as exc:
        return {"error": str(exc), **exc.details}
    if tool_.mutates:
        ctx.actions.append({"agent_id": ctx.agent_id, "tool": name, "result": result})
    return result


def dump_result(result: ToolResult) -> str:
    return json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":"))


def _load_tool_modules() -> None:
    # Imported for their @tool registrations.
    from app.agent.tools import (  # noqa: F401
        attendance,
        dates,
        events,
        materials,
        memory,
        planning,
        schedule,
        screen,
        setup,
        study,
        undo,
        weeks,
    )


_load_tool_modules()
