"""A whole syllabus -> the course's weekly plan (topics, readings, lab, exams), its books and
its exams, by Sonnet (`syllabus_parse`). Everything is taken "as written"; dates are read in
code (`day_month`) and each week's written dates are checked against the term's week numbers.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools import json_schema
from app.core.time_resolver import MONTH_NAMES_TR, normalize
from app.llm.types import ChatMessage, LLMRequest, ToolSpec

PURPOSE = "syllabus_parse"  # smart (Sonnet)
MAX_CHARS = 40_000


class BookIn(BaseModel):
    title: str
    authors: str | None = None
    edition: str | None = None
    required: bool = Field(False, description="the required / main textbook")


class WeekIn(BaseModel):
    week_no: int = Field(ge=1, le=20)
    dates: str | None = Field(None, description="the week's dates as written, if any")
    topics: str = Field(description="topics, short, in the document's language")
    readings: str | None = Field(
        None, description="book sections / texts to read that week, as written ('1.3, 1.4')"
    )
    lab: str | None = Field(None, description="lab / lab assignment of the week, as written")
    assessment: str | None = Field(
        None, description="exam / quiz / deadline in that week, with its date as written"
    )


class ExamIn(BaseModel):
    kind: Literal["midterm", "final", "quiz", "other"]
    when: str = Field(description="date and time as written ('November 27, 2026, Friday, 16:00')")
    week_no: int | None = Field(None, description="the week if the syllabus gives one")


class FullSyllabus(BaseModel):
    course_code: str | None = Field(None, description="e.g. 'MATH 221', as written")
    course_name: str | None = None
    books: list[BookIn] = Field(default_factory=list)
    weeks: list[WeekIn] = Field(default_factory=list)
    exams: list[ExamIn] = Field(default_factory=list)
    unclear: list[str] = Field(
        default_factory=list,
        description="what could not be read or contradicts itself (e.g. two midterm weeks)",
    )


TOOL = ToolSpec(
    "syllabus",
    "Return the course, its books, its week-by-week plan and its exams.",
    json_schema(FullSyllabus),
)
PROMPT = (
    "You get the text of a university course syllabus. Call `syllabus` once.\n"
    "- course_code / course_name as written.\n"
    "- books: every textbook / supplementary book named, required=true for the main one.\n"
    "- weeks: one entry per teaching week of the course plan with the syllabus's own week "
    "numbers: topics short, in the document's language; dates, readings (book sections, texts), "
    "lab and assessment (exam, quiz, debate, deadline) only when written for that week.\n"
    "- If the syllabus has no week-by-week plan (only a list of topics), return no weeks and "
    "say so in unclear.\n"
    "- exams: every midterm / final / quiz date written anywhere, as written.\n"
    "- Never invent weeks, dates, sections or books. Contradictions go into unclear."
)


async def parse(llm: Any, pages: list[str]) -> tuple[FullSyllabus, str]:
    text = "\n\n".join(f"[s. {i}]\n{p}" for i, p in enumerate(pages, start=1) if p)
    response = await llm.complete(
        LLMRequest(
            system=PROMPT,
            messages=[ChatMessage("user", text[:MAX_CHARS])],
            tools=[TOOL],
            tool_choice="required",
            max_tokens=8192,
        ),
        purpose=PURPOSE,
        agent_id="document_reader",
    )
    call = next((c for c in response.tool_calls if c.name == TOOL.name), None)
    if call is None or call.arguments is None:
        raise ValueError("the model did not call syllabus")
    parsed = FullSyllabus.model_validate(call.arguments)
    parsed.weeks = sorted({w.week_no: w for w in parsed.weeks}.values(), key=lambda w: w.week_no)
    return parsed, f"{response.provider}/{response.model}"


# ---- dates as written --------------------------------------------------------------------

MONTHS_EN = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_MONTH_WORDS = {normalize(m): i for i, m in enumerate(MONTH_NAMES_TR, start=1)} | {
    m: i for i, m in enumerate(MONTHS_EN, start=1)
}
_MONTH = "|".join(sorted(_MONTH_WORDS, key=len, reverse=True))
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s*(?:-\s*\d{{1,2}}\s*)?({_MONTH})\b")
DASHES = str.maketrans({chr(0x2013): "-", chr(0x2014): "-"})  # en / em dash
MONTH_DAY = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})\b")
SLASHED = re.compile(r"\b(\d{1,2})[/.](\d{1,2}|[a-z]+)[/.](\d{4})\b")


def day_month(text: str | None, year_of: dt.date) -> dt.date | None:
    """The first date in a written text ("5-9 Ekim", "November 27, 2026", "10/November/2026");
    a year-less date falls in the term that starts at `year_of` (autumn -> next January)."""
    if not text:
        return None
    norm = normalize(text.translate(DASHES))
    day: int | None = None
    month: int | None = None
    year: int | None = None
    slashed = SLASHED.search(norm)
    if slashed:
        day, raw_month, year = int(slashed[1]), slashed[2], int(slashed[3])
        month = int(raw_month) if raw_month.isdigit() else _MONTH_WORDS.get(raw_month)
    else:
        first = DAY_MONTH.search(norm)
        second = MONTH_DAY.search(norm)
        if first and (not second or first.start() <= second.start()):
            day, month = int(first[1]), _MONTH_WORDS[first[2]]
        elif second:
            day, month = int(second[2]), _MONTH_WORDS[second[1]]
        written_year = re.search(r"\b(20\d{2})\b", norm)
        year = int(written_year[1]) if written_year else None
    if not day or not month:
        return None
    if year is None:
        year = year_of.year + (1 if month < year_of.month - 2 else 0)
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def week_of(day: dt.date, term_start: dt.date) -> int:
    monday = term_start - dt.timedelta(days=term_start.weekday())
    return (day - monday).days // 7 + 1


@dataclass(slots=True)
class WeekCheck:
    ok: int = 0
    mismatches: list[str] = field(default_factory=list)


def check_weeks(weeks: list[WeekIn], term_start: dt.date) -> WeekCheck:
    """Does each week's written date fall in that week of the term?"""
    check = WeekCheck()
    for week in weeks:
        day = day_month(week.dates, term_start)
        if day is None:
            continue
        actual = week_of(day, term_start)
        if actual == week.week_no:
            check.ok += 1
        else:
            check.mismatches.append(
                f"hafta {week.week_no} '{week.dates}' -> dönemin {actual}. haftası"
            )
    return check
