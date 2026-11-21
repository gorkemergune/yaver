"""Find the course / block the user means ("linear", "EE211 lab"). Never guesses between
several matches: the tool returns the candidates and the agent asks."""

import datetime as dt
import re
from collections.abc import Sequence

from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError
from app.core.time_resolver import WEEKDAY_NAMES_TR, normalize
from app.db.models import Course, RecurringBlock, Term

WEEKDAYS_EN = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _words(text: str) -> set[str]:
    return set(normalize(text).replace("-", " ").split())


def _compact(text: str) -> str:
    return normalize(text).replace(" ", "").replace("-", "")


def matches(query: str, *names: str | None) -> bool:
    """Every word of the query appears (as a prefix) in one of the names; a code typed with
    spaces ("ee 211") also matches its compact form ("EE211")."""
    query_words = _words(query)
    if not query_words:
        return False
    present = [name for name in names if name]
    compact_query = _compact(query)
    if any(_compact(name).startswith(compact_query) for name in present):
        return True
    name_words: set[str] = set()
    for name in present:
        name_words |= _words(name)
    return all(
        any(word.startswith(q) or q.startswith(word) for word in name_words if len(word) >= 2)
        for q in query_words
    )


async def current_term(ctx: ToolContext) -> Term | None:
    terms = (await ctx.session.scalars(select(Term).order_by(Term.start_date))).all()
    containing = [t for t in terms if t.contains(ctx.today)]
    if containing:
        return containing[-1]
    upcoming = [t for t in terms if t.start_date > ctx.today]
    return upcoming[0] if upcoming else None


async def find_course(ctx: ToolContext, query: str) -> Course | None:
    """By code, name or one of the aliases the user taught ("DSA" -> CSE 211)."""
    courses = (await ctx.session.scalars(select(Course))).all()
    wanted = _compact(query)
    exact = [
        c for c in courses if wanted in (_compact(c.code), *(_compact(a) for a in c.aliases or []))
    ]
    found = exact or [c for c in courses if matches(query, c.code, c.name, *(c.aliases or []))]
    if len(found) > 1:
        raise ToolError(
            f"'{query}' matches several courses; ask the user which one",
            candidates=[{"code": c.code, "name": c.name} for c in found],
        )
    return found[0] if found else None


async def require_course(ctx: ToolContext, query: str) -> Course:
    course = await find_course(ctx, query)
    if course is None:
        known = (await ctx.session.scalars(select(Course).order_by(Course.code))).all()
        raise ToolError(
            f"no course matches '{query}': ask the user once which of known_courses it is; "
            "with the answer call add_course_alias(course, alias) and then do the job",
            known_courses=[
                c.code if c.name in (c.code, "") else f"{c.code} ({c.name})" for c in known
            ],
        )
    return course


async def find_or_create_course(
    ctx: ToolContext, code: str | None, name: str | None
) -> tuple[Course, bool]:
    for query in (code, name):
        if query:
            course = await find_course(ctx, query)
            if course is not None:
                return course, False
    term = await current_term(ctx)
    course = Course(
        code=(code or name or "?").strip()[:20],
        name=(name or code or "?").strip(),
        term_id=term.id if term else None,
    )
    ctx.session.add(course)
    await ctx.recorder.created(course)
    return course, True


def describe_block(block: RecurringBlock) -> dict[str, object]:
    return {
        "block_id": block.id,
        "title": block.title,
        "kind": block.kind.value,
        "weekday": WEEKDAY_NAMES_TR[block.weekday],
        "start": block.start_time.strftime("%H:%M"),
        "end": block.end_time.strftime("%H:%M"),
    }


async def find_blocks(
    ctx: ToolContext, query: str, *, weekday: int | None = None
) -> Sequence[RecurringBlock]:
    blocks = (await ctx.session.scalars(select(RecurringBlock))).all()
    by_id = re.fullmatch(r"#(\d+)", query.strip())
    if by_id:  # a candidate the user picked (app.agent.pending)
        return [b for b in blocks if b.id == int(by_id.group(1))]
    courses = {c.id: c for c in (await ctx.session.scalars(select(Course))).all()}
    found = []
    for block in blocks:
        course = courses.get(block.course_id) if block.course_id else None
        names = (
            block.title,
            block.kind.value,
            course.code if course else None,
            course.name if course else None,
        )
        if matches(query, *names) and (weekday is None or block.weekday == weekday):
            found.append(block)
    return found


def single_block(
    found: Sequence[RecurringBlock], query: str, day: dt.date | None
) -> RecurringBlock:
    when = f" on {day.isoformat()}" if day else ""
    if not found:
        raise ToolError(f"no block matches '{query}'{when}")
    if len(found) > 1:
        raise ToolError(
            f"'{query}' matches several blocks{when}; ask the user which one",
            candidates=[describe_block(b) for b in found],
        )
    return found[0]
