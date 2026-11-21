"""Which term weeks a book section / lab experiment / homework sheet belongs to.

1. In code: a section number the syllabus lists as that week's reading ("1.3, 1.4" ->
   section "1.3") - the MATH 221 kind of syllabus needs no model at all.
2. The rest by one `material_map` call per material (smart tier): the course's weekly plan +
   the numbered entries -> weeks per entry. Clear matches only; an entry may get no week.
"""

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.agent.tools import json_schema
from app.llm.types import ChatMessage, LLMRequest, ToolSpec

PURPOSE = "material_map"  # smart (providers.yaml routing.purposes)


@dataclass(frozen=True, slots=True)
class PlanWeek:
    week_no: int
    topics: str
    readings: str | None = None
    lab: str | None = None


@dataclass(frozen=True, slots=True)
class Entry:
    number: str | None
    title: str
    hint: str = ""  # a few lines of its text (sheets without a title that says much)


class EntryWeeks(BaseModel):
    index: int = Field(ge=0)
    weeks: list[int] = Field(default_factory=list, description="term weeks; empty if none fits")


class Mapping(BaseModel):
    entries: list[EntryWeeks]


TOOL = ToolSpec("map_weeks", "Give the weeks of each entry.", json_schema(Mapping))
PROMPT = (
    "You get a course's weekly plan and a numbered list of entries (book sections, lab "
    "experiments or homework / lab sheets). Call map_weeks once: for each entry the week "
    "numbers whose topics, readings or lab it clearly belongs to. A homework or lab sheet "
    "belongs to the weeks whose topics it practises. Unclear -> no weeks. Never invent weeks "
    "outside the plan."
)


def by_readings(entries: list[Entry], plan: list[PlanWeek]) -> dict[int, list[int]]:
    """Section numbers named in a week's readings ("1.1, 1.2" / "Ch. 3")."""
    found: dict[int, list[int]] = {}
    for week in plan:
        text = f"{week.readings or ''} {week.lab or ''}".lower()
        if not text.strip():
            continue
        for index, entry in enumerate(entries):
            if entry.number and re.search(
                rf"(?<![\d.]){re.escape(entry.number.lower())}(?![\d])", text
            ):
                found.setdefault(index, []).append(week.week_no)
    return found


async def map_to_weeks(
    llm: Any, course: str, plan: list[PlanWeek], entries: list[Entry]
) -> dict[int, list[int]]:
    if not plan or not entries:
        return {}
    mapped = by_readings(entries, plan)
    rest = [i for i in range(len(entries)) if i not in mapped]
    if not rest or llm is None:
        return mapped
    weeks_text = "\n".join(
        f"Hafta {w.week_no}: {w.topics}"
        + (f" | Okuma: {w.readings}" if w.readings else "")
        + (f" | Lab: {w.lab}" if w.lab else "")
        for w in plan
    )
    entries_text = "\n".join(
        f"{i}. {' '.join(p for p in (entries[i].number, entries[i].title) if p)}"
        + (f" — {entries[i].hint}" if entries[i].hint else "")
        for i in rest
    )
    response = await llm.complete(
        LLMRequest(
            system=PROMPT,
            messages=[
                ChatMessage(
                    "user", f"Ders: {course}\n\nHaftalık plan:\n{weeks_text}\n\n{entries_text}"
                )
            ],
            tools=[TOOL],
            tool_choice="required",
            max_tokens=2000,
        ),
        purpose=PURPOSE,
        agent_id="document_reader",
    )
    call = next((c for c in response.tool_calls if c.name == TOOL.name), None)
    if call is None or call.arguments is None:
        return mapped
    known = {w.week_no for w in plan}
    for item in Mapping.model_validate(call.arguments).entries:
        if item.index in rest:
            weeks = sorted({w for w in item.weeks if w in known})
            if weeks:
                mapped[item.index] = weeks
    return mapped
