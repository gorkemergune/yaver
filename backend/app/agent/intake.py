"""Lecture notes (a PDF, or a photo read by agent.vision) become a *pending* course material:
the team is told "materyal #M" with a suggested course and week, and Friday links it
(`save_material`) once the user said or confirmed which course / week. Only then are the
passages embedded and searchable."""

import logging
import math

from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError
from app.agent.tools.matching import find_course
from app.db.models import Course, CourseMaterial, SyllabusWeek
from app.rag.embed import embed

logger = logging.getLogger(__name__)

SAMPLE_CHARS = 1500
# Calibrated on the multilingual MiniLM (2026-11-20): right weeks scored 0.51-0.55 with a
# 0.11-0.14 lead; wrong / unrelated ones 0.35-0.39 with ~0.03. A wrong suggestion is worse
# than asking, so only clear matches are suggested.
MIN_SCORE = 0.42  # weaker similarity than this: no week is suggested
MIN_MARGIN = 0.06  # the best week must beat the second one by this much


async def pending_material(
    ctx: ToolContext,
    *,
    attachment_id: int,
    title: str,
    pages: int,
    sample: str,
    course_hint: str | None,
    source_text: str | None = None,
) -> str:
    """Creates the pending material; returns the "-> materyal #M ..." part of the block."""
    course = await _course(ctx, course_hint)
    week, topics = await suggest_week(ctx, course, sample) if course else (None, None)
    material = CourseMaterial(
        course_id=course.id if course else None,
        attachment_id=attachment_id,
        kind="notes",
        title=title,
        pages=pages,
        week_no=None,  # set by save_material
        source_text=source_text,
    )
    ctx.session.add(material)
    await ctx.session.flush()
    suggestion = []
    if course:
        suggestion.append(course.code)
    if week:
        suggestion.append(f"{week}. hafta (syllabus: {topics})")
    tail = (
        f"öneri: {', '.join(suggestion)}" if suggestion else "ders ve hafta bilinmiyor, sorulacak"
    )
    return f"-> materyal #{material.id}, henüz kaydedilmedi; {tail}"


async def _course(ctx: ToolContext, hint: str | None) -> Course | None:
    if not hint:
        return None
    try:
        return await find_course(ctx, hint)
    except ToolError:  # several courses match: leave it to the user
        return None


async def suggest_week(
    ctx: ToolContext, course: Course, sample: str
) -> tuple[int | None, str | None]:
    """The syllabus week whose topics read closest to the notes (local embeddings)."""
    weeks = (
        await ctx.session.scalars(
            select(SyllabusWeek)
            .where(SyllabusWeek.course_id == course.id)
            .order_by(SyllabusWeek.week_no)
        )
    ).all()
    if not weeks or not sample.strip():
        return None, None
    try:
        vectors = await embed([sample[:SAMPLE_CHARS], *(w.topics for w in weeks)])
    except Exception:  # no model (offline first run...): no suggestion, Friday asks
        logger.warning("week suggestion skipped", exc_info=True)
        return None, None
    doc, *topics = vectors
    scores = sorted(
        ((_cosine(doc, vector), week) for vector, week in zip(topics, weeks, strict=True)),
        key=lambda pair: -pair[0],
    )
    best_score, best = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else -1.0
    if best_score < MIN_SCORE or best_score - runner_up < MIN_MARGIN:
        return None, None
    return best.week_no, best.topics


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
