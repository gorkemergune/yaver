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
from app.agent.schema import HHMM_PATTERN, json_schema
from app.llm.types import ToolSpec

ToolResult = dict[str, Any]
__all__ = ["HHMM_PATTERN", "json_schema"]  # re-exported for the tool modules
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
        github,
        integrations,
        materials,
        memory,
        notes,
        planning,
        routing,
        schedule,
        screen,
        setup,
        study,
        undo,
        weeks,
    )


_load_tool_modules()
