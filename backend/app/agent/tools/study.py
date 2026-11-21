"""Study sheets (Phase 3): the code picks the passages (search_materials' index), the smart
tier writes only from them with numbered citations, the code adds the "Kaynaklar" list
(file + page) so a source can never be made up."""

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, json_schema, tool
from app.agent.tools.matching import require_course
from app.db.models import SyllabusWeek
from app.db.models.study import StudySheet
from app.llm.types import ChatMessage, LLMRequest, ToolSpec
from app.materials.weekly import week_material_ids
from app.rag.store import Hit, search

PURPOSE = "study_sheet"  # smart tier
MAX_SOURCES = 10
MAX_SOURCE_CHARS = 9000


class GenerateStudySheetArgs(BaseModel):
    course: str = Field(description="course code or name")
    week: int | None = Field(
        None, ge=1, le=30, description="term week; 'bu hafta' = the current_term_week"
    )
    topic: str | None = Field(None, description="a topic to focus on, if the user named one")


class WrittenSheet(BaseModel):
    title: str = Field(description="short Turkish title, e.g. 'EE211 · 7. hafta: Thevenin'")
    markdown: str = Field(
        description="the sheet in Markdown, every fact followed by its source number like [2]"
    )


SHEET_TOOL = ToolSpec("study_sheet", "Return the study sheet.", json_schema(WrittenSheet))
SHEET_PROMPT = (
    "You write a study sheet for a university student, in Turkish, from the numbered course "
    "passages you are given and nothing else.\n"
    "Sections (Markdown, ## headings): Özet; Temel kavramlar; Formüller ve kurallar (if any); "
    'Kendini dene (4-6 questions, answers under a "Cevaplar" subheading).\n'
    "After every fact, definition or formula put the number of the passage it comes from, "
    "like [3]. Use only what the passages say; if they are thin on something, say so in one "
    'line instead of filling it in. No "Kaynaklar" section: it is added for you. '
    "Call study_sheet."
)


@tool(
    "generate_study_sheet",
    "Write a study sheet (çalışma kağıdı) from the uploaded notes of a course / week, with "
    "sources. Slow (a few seconds); reply with the link it returns.",
    GenerateStudySheetArgs,
    mutates=True,
)
async def generate_study_sheet(args: GenerateStudySheetArgs, ctx: ToolContext) -> ToolResult:
    if ctx.llm is None:
        raise ToolError("no model available for study sheets right now")
    course = await require_course(ctx, args.course)
    topics = ""
    if args.week is not None:
        row = await ctx.session.scalar(
            select(SyllabusWeek).where(
                SyllabusWeek.course_id == course.id, SyllabusWeek.week_no == args.week
            )
        )
        topics = row.topics if row else ""
    hits = await _sources(ctx, course.id, args.week, args.topic or topics or course.name)
    if not hits:
        raise ToolError(
            "no uploaded material for this course/week: ask the user to send the notes "
            "(PDF or photos) first",
            course=course.code,
        )
    numbered = "\n\n".join(
        f"[{n}] ({hit.title}, {hit.pages})\n{hit.content}" for n, hit in enumerate(hits, start=1)
    )
    focus = " · ".join(
        part
        for part in (
            f"Ders: {course.code} {course.name}",
            f"{args.week}. hafta" if args.week else "",
            f"Haftanın konuları (syllabus): {topics}" if topics else "",
            f"Odak: {args.topic}" if args.topic else "",
        )
        if part
    )
    response = await ctx.llm.complete(
        LLMRequest(
            system=SHEET_PROMPT,
            messages=[ChatMessage("user", f"{focus}\n\nPasajlar:\n\n{numbered}")],
            tools=[SHEET_TOOL],
            tool_choice="required",
            max_tokens=6000,
        ),
        purpose=PURPOSE,
        agent_id="study_sheet",
    )
    call = next((c for c in response.tool_calls if c.name == SHEET_TOOL.name), None)
    if call is None or call.arguments is None:
        raise ToolError("the study sheet could not be written; try again")
    written = WrittenSheet.model_validate(call.arguments)
    content, sources = with_sources(written.markdown, hits)
    sheet = StudySheet(
        course_id=course.id,
        week_no=args.week,
        title=written.title.strip()[:300],
        content_md=content,
        sources=sources,
        model=f"{response.provider}/{response.model}",
    )
    ctx.session.add(sheet)
    await ctx.recorder.created(sheet)
    return {
        "study_sheet": {
            "id": sheet.id,
            "title": sheet.title,
            "link": f"[{sheet.title}](#/sheet?id={sheet.id})",
            "sources": [f"{s['title']}, {s['pages']}" for s in sources],
        },
        "note": "give the user the link as is",
    }


async def _sources(ctx: ToolContext, course_id: int, week: int | None, query: str) -> list[Hit]:
    """The week's own materials first (mapped sections, notes tabs, sheets), then the
    passages closest to the topic."""
    found: list[Hit] = []
    if week is not None:
        mapped = await week_material_ids(ctx.session, course_id, week)
        if mapped:
            found += await search(ctx.session, query, material_ids=mapped, limit=8)
        found += await search(ctx.session, query, course_id=course_id, week_no=week, limit=8)
    found += await search(ctx.session, query, course_id=course_id, limit=8)
    unique: dict[tuple[int, int, str], Hit] = {}
    for hit in found:
        unique.setdefault((hit.material_id, hit.page_start, hit.content[:80]), hit)
    picked: list[Hit] = []
    size = 0
    for hit in unique.values():
        if len(picked) == MAX_SOURCES or size + len(hit.content) > MAX_SOURCE_CHARS:
            break
        picked.append(hit)
        size += len(hit.content)
    return picked


def with_sources(markdown: str, hits: list[Hit]) -> tuple[str, list[dict[str, Any]]]:
    """Appends "## Kaynaklar" built from the passages actually cited ([n]); numbers that
    point nowhere are dropped from the text."""
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", markdown) if 1 <= int(n) <= len(hits)})
    text = re.sub(
        r"\[(\d+)\]",
        lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(hits) else "",
        markdown,
    ).rstrip()
    used = cited or list(range(1, len(hits) + 1))
    sources = [
        {
            "n": n,
            "title": hits[n - 1].title,
            "pages": hits[n - 1].pages,
            "material_id": hits[n - 1].material_id,
        }
        for n in used
    ]
    lines = [f"[{s['n']}] {s['title']}, {s['pages']}" for s in sources]
    return text + "\n\n## Kaynaklar\n\n" + "\n".join(f"- {line}" for line in lines) + "\n", sources
