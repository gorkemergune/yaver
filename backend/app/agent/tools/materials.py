"""Course materials (Phase 3): search the uploaded notes / syllabi, read a course's weekly
topics, and save a confirmed syllabus (called from apply_proposal)."""

import asyncio
import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.agent.tools.matching import find_or_create_course, require_course
from app.config import get_settings
from app.core.time_resolver import MONTH_NAMES_TR, WEEKDAY_NAMES_TR
from app.db.models import Attachment, CourseMaterial, Event, Proposal, SyllabusWeek
from app.db.models.enums import EventKind
from app.materials.weekly import (
    compact,
    course_weeks,
    covered_weeks,
    match_topics,
    sections_numbered,
    syllabus_files,
    term_week,
    titles_like,
    topics_of,
)
from app.rag.pdf import page_texts
from app.rag.store import index_material, search
from app.services.images import resolve_stored

SNIPPET_CHARS = 800  # passages are ~500 characters (rag.chunk): whole ones go to the model


class SearchMaterialsArgs(BaseModel):
    query: str = Field(description="what to look for, in the user's words or the topic")
    course: str | None = Field(None, description="course code or name to search in")
    week: int | None = Field(None, ge=1, le=30, description="term week number")
    limit: int = Field(5, ge=1, le=10)


@tool(
    "search_materials",
    "Search the uploaded course materials (syllabi, notes, slides). Returns passages with "
    "file name and pages: cite them as (dosya, s. N). Read-only.",
    SearchMaterialsArgs,
)
async def search_materials(args: SearchMaterialsArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course) if args.course else None
    hits = await search(
        ctx.session,
        args.query,
        course_id=course.id if course else None,
        week_no=args.week,
        limit=args.limit,
    )
    titled = await titles_like(ctx.session, args.query, course.id if course else None)
    numbered = await sections_numbered(ctx.session, args.query, course.id if course else None)
    if not hits and not titled and not numbered:
        return {"results": [], "note": "nothing uploaded matches; say so, do not make it up"}
    found: dict[str, Any] = {"files_named": titled} if titled else {}
    if numbered:
        found["sections_named"] = numbered
    return {
        **found,
        "results": [
            {
                "source": f"{hit.title}, {hit.pages}",
                "course": hit.course,
                "week": hit.week_no,
                "kind": hit.kind,
                "score": hit.score,
                "text": hit.content[:SNIPPET_CHARS],
            }
            for hit in hits
        ],
    }


class GetSyllabusArgs(BaseModel):
    course: str = Field(description="course code or name")
    week: int | None = Field(None, ge=1, le=30, description="one term week; omit for all weeks")
    relative: Literal["last_week", "this_week", "next_week"] | None = Field(
        None,
        description="'geçen hafta' / 'bu hafta' / 'haftaya' instead of a week number (in code)",
    )


MATERIAL_WEEKS = 3  # up to this many weeks come with their sections / notes / sheets


@tool(
    "get_syllabus",
    "A course's weeks from its syllabus: topics, readings, lab, exam; for one week (or "
    "relative=this_week / next_week) also the book / lab-book sections with pages, the shared "
    "notes and the homework / lab sheets of that week. Cite them by name and pages. Read-only.",
    GetSyllabusArgs,
)
async def get_syllabus(args: GetSyllabusArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    current = await term_week(ctx.session, ctx.today, ctx.tz)
    week = args.week
    if args.relative is not None:
        if current is None:
            raise ToolError("today is outside the term: give a week number")
        week = current + {"last_week": -1, "this_week": 0, "next_week": 1}[args.relative]
    refs = await course_weeks(ctx.session, course, [week] if week is not None else None)
    detailed = len(refs) <= MATERIAL_WEEKS
    result: dict[str, Any] = {
        "course": course.code,
        "current_term_week": current,
        "syllabus_file": ", ".join(await syllabus_files(ctx.session, course.id)) or None,
        "weeks": [r.as_dict(materials=detailed) for r in refs],
    }
    if not refs:
        files = (
            await ctx.session.scalars(
                select(CourseMaterial.title)
                .where(CourseMaterial.course_id == course.id)
                .order_by(CourseMaterial.id)
            )
        ).all()
        if files:  # EE211: a syllabus without a weekly plan, a lab book
            result["materials"] = list(files)[:10]
            result["note"] = (
                "the syllabus has no week-by-week plan (or no such week); the course's "
                "materials are listed: use search_materials for their content"
            )
        else:
            result["note"] = "no syllabus uploaded for this course (or no such week)"
    elif not detailed:
        result["note"] = "ask for one week to see its sections, notes and sheets"
    else:
        result["note"] = "say the week number; cite the syllabus_file and pages as given"
    return result


class GetExamScopeArgs(BaseModel):
    course: str = Field(description="course code or name")


@tool(
    "get_exam_scope",
    "What the course's next exam covers ('DSA sınavı için ne çalışmalıyım?'): the exam, its "
    "syllabus weeks (only those matching the topics the user gave, if any) with readings, "
    "book sections and pages, shared notes and sheets. Read-only.",
    GetExamScopeArgs,
)
async def get_exam_scope(args: GetExamScopeArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    exams = (
        await ctx.session.scalars(
            select(Event)
            .where(
                Event.kind.in_((EventKind.EXAM, EventKind.QUIZ)),
                Event.start_at >= ctx.now - dt.timedelta(hours=3),
            )
            .order_by(Event.start_at)
        )
    ).all()
    code = compact(course.code)
    exam = next(
        (
            e
            for e in exams
            if e.course_id == course.id or (e.course_id is None and code in compact(e.title))
        ),
        None,
    )
    every = await course_weeks(ctx.session, course)
    if exam is None:
        planned = [r.as_dict(materials=False) for r in every if r.assessment]
        return {
            "course": course.code,
            "exam": None,
            "note": "no exam of this course is in the calendar; the syllabus says (if anything):",
            "syllabus_exams": planned,
        }
    day = exam.start_at.astimezone(ctx.tz).date()
    covered = {w.week_no for w in await covered_weeks(ctx.session, exam, course, ctx.tz)}
    told = topics_of(exam.notes)
    chosen = [r for r in every if r.week_no in covered] or every
    match = match_topics(told, chosen) if told else None
    if match is not None and match.complete:
        chosen = [r for r in chosen if r.week_no in match.weeks]
    weeks = []
    for ref in chosen:
        item = ref.as_dict()
        if match is not None and not match.complete and ref.week_no in match.weeks:
            item["matches_your_topics"] = True
        weeks.append(item)
    return {
        "course": course.code,
        "exam": {
            "title": exam.title,
            "date": day.isoformat(),
            "when": (
                f"{day.day} {MONTH_NAMES_TR[day.month - 1]} {WEEKDAY_NAMES_TR[day.weekday()]}"
                + ("" if exam.all_day else exam.start_at.astimezone(ctx.tz).strftime(" %H:%M"))
            ),
            "days_left": (day - ctx.today).days,
            "topics_you_gave": told,
        },
        "basis": (
            "your topics matched to the syllabus"
            if match is not None and match.complete
            else "syllabus weeks since the previous exam"
        ),
        "topics_not_in_syllabus": match.missing if match else [],
        "syllabus_file": ", ".join(await syllabus_files(ctx.session, course.id)) or None,
        "weeks": weeks,
        "note": (
            "say the date as 'when'; for each week its topics and, by name, its readings, "
            "sections (pages), notes and sheets; cite the syllabus_file; add nothing unlisted"
        ),
    }


class SaveMaterialArgs(BaseModel):
    material_id: int = Field(description="the N of 'materyal #N'")
    course: str = Field(description="course code or name")
    week: int | None = Field(None, ge=1, le=30, description="term week; omit if it spans weeks")
    kind: Literal["notes", "slides", "other"] = "notes"


@tool(
    "save_material",
    "Link uploaded notes ('materyal #N') to a course and week and make them searchable. "
    "Only after the user said or confirmed the course (and week).",
    SaveMaterialArgs,
    mutates=True,
)
async def save_material(args: SaveMaterialArgs, ctx: ToolContext) -> ToolResult:
    material = await ctx.session.get(CourseMaterial, args.material_id)
    if material is None:
        raise ToolError(f"no material #{args.material_id}")
    course = await require_course(ctx, args.course)
    if material.indexed_at is not None:  # already saved: move it to another course / week
        before = ctx.recorder.before_update(material)
        material.course_id, material.week_no, material.kind = course.id, args.week, args.kind
        await ctx.recorder.updated(material, before)
    else:
        material.course_id, material.week_no, material.kind = course.id, args.week, args.kind
        # recorded as created now: "Geri al" removes it (and its passages)
        await ctx.recorder.created(material)
    pages = await _material_pages(ctx, material)
    passages = await index_material(ctx.session, material, pages, ctx.now)
    return {
        "material_saved": {
            "title": material.title,
            "course": course.code,
            "week": args.week,
            "searchable_passages": passages,
        }
    }


async def _material_pages(ctx: ToolContext, material: CourseMaterial) -> list[str]:
    if material.source_text:  # a photo, read when it was sent
        return [material.source_text]
    attachment = (
        await ctx.session.get(Attachment, material.attachment_id)
        if material.attachment_id
        else None
    )
    if attachment is None:
        raise ToolError("the file of this material is gone; ask the user to send it again")
    path = resolve_stored(get_settings().upload_dir, attachment.path)
    data = await asyncio.to_thread(path.read_bytes)
    return await asyncio.to_thread(page_texts, data)


async def apply_syllabus(proposal: Proposal, ctx: ToolContext) -> ToolResult:
    """The confirmed table: course (created if new), weekly topics, the PDF as a material
    with searchable passages."""
    first = proposal.entries[0]
    course, created = await find_or_create_course(
        ctx, first.get("course"), first.get("course_name")
    )
    attachment = await ctx.session.get(Attachment, int(first["attachment_id"]))
    if attachment is None:
        raise ToolError("the PDF of this proposal is gone; ask the user to send it again")
    settings = get_settings()
    data = await asyncio.to_thread(resolve_stored(settings.upload_dir, attachment.path).read_bytes)
    pages = await asyncio.to_thread(page_texts, data)

    material = CourseMaterial(
        course_id=course.id,
        attachment_id=attachment.id,
        kind="syllabus",
        title=str(first.get("filename") or attachment.filename or "syllabus.pdf"),
        pages=len(pages),
        week_no=None,
    )
    ctx.session.add(material)
    await ctx.recorder.created(material)

    saved, updated = 0, 0
    for entry in proposal.entries:
        row = await ctx.session.scalar(
            select(SyllabusWeek).where(
                SyllabusWeek.course_id == course.id, SyllabusWeek.week_no == entry["week_no"]
            )
        )
        if row is None:
            row = SyllabusWeek(
                course_id=course.id,
                material_id=material.id,
                week_no=entry["week_no"],
                topics=entry["topics"],
            )
            ctx.session.add(row)
            await ctx.recorder.created(row)
            saved += 1
        elif row.topics != entry["topics"]:
            before = ctx.recorder.before_update(row)
            row.topics = entry["topics"]
            row.material_id = material.id
            await ctx.recorder.updated(row, before)
            updated += 1
    passages = await index_material(ctx.session, material, pages, ctx.now)
    return {
        "syllabus_saved": {
            "course": course.code,
            "course_created": created,
            "weeks": saved,
            "weeks_updated": updated,
            "searchable_passages": passages,
        }
    }
