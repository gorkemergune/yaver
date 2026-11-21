import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.tools import ToolResult, tool
from app.agent.tools.matching import current_term
from app.core.time_resolver import WEEKDAY_NAMES_TR, PartOfDay, Status, normalize, resolve


class ResolveDateArgs(BaseModel):
    expression: str = Field(
        description="The user's own words for the date/time, e.g. 'yarın 14'te', "
        "'haftaya salı', 'geçen salı', '28-29 kasım', 'bu akşam'; a list of days of one month "
        "('5 12 17 19 kasım') comes back as `dates`. One expression per call."
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
    days = day_list(args.expression, args.direction)
    if days is not None:
        return await _resolve_list(days, args, ctx)
    return await _resolve_one(args.expression, args, ctx)


async def _resolve_one(expression: str, args: ResolveDateArgs, ctx: ToolContext) -> ToolResult:
    term = await current_term(ctx)
    result = resolve(
        expression,
        ctx.today,
        term_start=term.start_date if term else None,
        term_end=term.end_date if term else None,
        direction=args.direction,
        clock=ctx.clock,
    )
    data = result.to_dict()
    if result.span is not None:
        data["weekday"] = WEEKDAY_NAMES_TR[result.span.start.weekday()]
    if result.part_of_day is not None and result.time is None:
        # "yarın sabah kahvaltı": an event needs an hour, the user gave a part of the day
        data["default_start_time"] = DEFAULT_TIMES[result.part_of_day].strftime("%H:%M")
        data["note"] = "no hour given: add_event uses default_start_time, nothing to ask"
    return data


# The hour an event gets when only the part of the day was said.
DEFAULT_TIMES = {
    PartOfDay.MORNING: dt.time(9, 0),
    PartOfDay.NOON: dt.time(12, 0),
    PartOfDay.AFTERNOON: dt.time(15, 0),
    PartOfDay.EVENING: dt.time(19, 0),
    PartOfDay.NIGHT: dt.time(21, 0),
}


async def _resolve_list(days: list[str], args: ResolveDateArgs, ctx: ToolContext) -> ToolResult:
    """ "5 12 17 19 kasım" -> each day on its own; resolved only if every one is."""
    results = [await _resolve_one(day, args, ctx) for day in days]
    if all(r["status"] == Status.RESOLVED.value and r["start"] == r["end"] for r in results):
        return {
            "status": Status.RESOLVED.value,
            "expression": args.expression,
            "dates": [r["start"] for r in results],
            "weekdays": [r["weekday"] for r in results],
            "note": "the user named these separate days: use all of them, nothing to ask",
        }
    return {"status": "partly_resolved", "expression": args.expression, "items": results}


# "5 12 17 19 kasım", "12, 19 kasımda", "12 ve 19 kasım": separate days of one month.
_DAY_LIST = re.compile(r"(?P<days>\d{1,2}(?:\s+(?:ve\s+)?\d{1,2})+)\s+(?P<month>[a-z].*)")


def day_list(expression: str, direction: str) -> list[str] | None:
    """The single-day phrases of a list of days, or None. Two days ("12 19 kasım") are a
    list only for things that happened (direction past); planning keeps it a range."""
    match = _DAY_LIST.fullmatch(normalize(expression))
    if match is None:
        return None
    numbers = re.findall(r"\d{1,2}", match["days"])
    if len(numbers) < 3 and direction != "past":
        return None
    return [f"{number} {match['month']}" for number in numbers]
