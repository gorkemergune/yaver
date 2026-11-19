from typing import Literal

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.tools import ToolResult, tool
from app.agent.tools.matching import current_term
from app.core.time_resolver import WEEKDAY_NAMES_TR, resolve


class ResolveDateArgs(BaseModel):
    expression: str = Field(
        description="The user's own words for the date/time, e.g. 'yarın 14'te', "
        "'haftaya salı', 'geçen salı', '28-29 kasım', 'bu akşam'. One expression per call."
    )
    direction: Literal["future", "past", "any"] = Field(
        "any",
        description="future when adding/planning something, past when logging what "
        "happened (attendance, 'gitmedim'), any when only looking something up",
    )


@tool(
    "resolve_date",
    "Turn a Turkish date/time expression into ISO dates. ALWAYS use this instead of "
    "computing dates yourself. status=ambiguous -> ask the user to pick a candidate; "
    "status=unresolved -> ask the user to rephrase.",
    ResolveDateArgs,
)
async def resolve_date(args: ResolveDateArgs, ctx: ToolContext) -> ToolResult:
    term = await current_term(ctx)
    result = resolve(
        args.expression,
        ctx.today,
        term_start=term.start_date if term else None,
        term_end=term.end_date if term else None,
        direction=args.direction,
        clock=ctx.clock,
    )
    data = result.to_dict()
    if result.span is not None:
        data["weekday"] = WEEKDAY_NAMES_TR[result.span.start.weekday()]
    return data
