"""`handoff`: a yaver got something outside its area. It never answers "bu benim işim değil"
and stops: it hands the message back and the coordinator gives it to the right one, in the
same message (app.agent.coordinator)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.intent_map import AREAS, OWNERS
from app.agent.tools import ToolError, ToolResult, tool

Area = Literal[AREAS]  # type: ignore[valid-type]


class HandoffArgs(BaseModel):
    reason: str = Field(max_length=200, description="why it is not yours, in a few words")
    area: Area = Field(
        description="whose it is: event (one-off calendar thing), exam, class, attendance, "
        "course_note, task, followup, sport, content, ads, startup, career, social"
    )


@tool(
    "handoff",
    "The request (or this part of it) is outside your area: hand it back to the "
    "coordinator, who gives it to the right yaver now. Call it instead of answering that "
    "it is not your job. A plain one-off calendar event you can add yourself (add_event).",
    HandoffArgs,
)
async def handoff(args: HandoffArgs, ctx: ToolContext) -> ToolResult:
    if OWNERS.get(args.area) == ctx.agent_id:
        # live: Chrono handed "market alışverişi yapmam lazım" (a task) back, nobody did it
        raise ToolError(f"'{args.area}' is your own area: do it yourself with your tools now")
    return {"handed_off": True, "area": args.area}
