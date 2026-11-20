"""Course materials (Phase 3): search the uploaded notes / syllabi, read a course's weekly
topics, and save a confirmed syllabus (called from apply_proposal)."""

import asyncio
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.agent.tools.matching import find_or_create_course, require_course
from app.config import get_settings
from app.db.models import Attachment, CourseMaterial, Proposal, SyllabusWeek
from app.rag.pdf import page_texts
from app.rag.store import index_material, search
from app.services.images import resolve_stored
from app.services.weeks import week_facts

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
    if not hits:
        return {"results": [], "note": "nothing uploaded matches; say so, do not make it up"}
    return {
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
        ]
    }


class GetSyllabusArgs(BaseModel):
    course: str = Field(description="course code or name")
    week: int | None = Field(None, ge=1, le=30, description="one week; omit for all weeks")


@tool(
    "get_syllabus",
    "A course's topics per week from its syllabus ('bu hafta ne işlendi?'). Also says which "
    "week of the term it is now. Read-only.",
    GetSyllabusArgs,
)
async def get_syllabus(args: GetSyllabusArgs, ctx: ToolContext) -> ToolResult:
    course = await require_course(ctx, args.course)
    query = select(SyllabusWeek).where(SyllabusWeek.course_id == course.id)
    if args.week is not None:
        query = query.where(SyllabusWeek.week_no == args.week)
    weeks = (await ctx.session.scalars(query.order_by(SyllabusWeek.week_no))).all()
    current = await week_facts(ctx.session, ctx.today, ctx.tz)
    result: dict[str, Any] = {
        "course": course.code,
        "current_term_week": current.week_no,
        "weeks": [{"week": w.week_no, "topics": w.topics} for w in weeks],
    }
    if not weeks:
        result["note"] = "no syllabus uploaded for this course (or no such week)"
    return result


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
