"""The employee's notebook (defter): short dated notes the office panel shows."""

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.core.time_resolver import normalize
from app.db.models import Employee, EmployeeNote

NOTE_MAX_CHARS = 500


class AddNoteArgs(BaseModel):
    content: str = Field(min_length=1, max_length=NOTE_MAX_CHARS, description="short, Turkish")


@tool(
    "add_note",
    "Write in your notebook (defter). Only when the user asks you to note something.",
    AddNoteArgs,
    mutates=True,
)
async def add_note(args: AddNoteArgs, ctx: ToolContext) -> ToolResult:
    if await ctx.session.get(Employee, ctx.agent_id) is None:
        raise ToolError("no notebook for this yaver yet")
    note = EmployeeNote(employee_id=ctx.agent_id, content=args.content.strip(), source="agent")
    ctx.session.add(note)
    await ctx.recorder.created(note)
    ctx.notes.append(
        {
            "id": note.id,
            "employee_id": note.employee_id,
            "content": note.content,
            "created_at": note.created_at,
        }
    )
    return {"noted": {"note_id": note.id, "content": note.content}}


class GetNotesArgs(BaseModel):
    employee: str | None = Field(None, description="name; empty = yours")
    limit: int = Field(10, ge=1, le=30)


@tool("get_notes", "Read a notebook (defter), newest first.", GetNotesArgs)
async def get_notes(args: GetNotesArgs, ctx: ToolContext) -> ToolResult:
    employees = (await ctx.session.scalars(select(Employee).where(Employee.active))).all()
    if args.employee:
        key = normalize(args.employee)
        found = [e for e in employees if key in (normalize(e.name), normalize(e.id))]
        if not found:
            raise ToolError(
                "unknown employee", candidates=[{"id": e.id, "name": e.name} for e in employees]
            )
        employee = found[0]
    else:
        own = [e for e in employees if e.id == ctx.agent_id]
        if not own:
            raise ToolError("no notebook for this yaver yet")
        employee = own[0]
    rows = (
        await ctx.session.scalars(
            select(EmployeeNote)
            .where(EmployeeNote.employee_id == employee.id)
            .order_by(EmployeeNote.id.desc())
            .limit(args.limit)
        )
    ).all()
    return {
        "employee": employee.name,
        "notes": [
            {
                "date": row.created_at.astimezone(ctx.tz).strftime("%Y-%m-%d %H:%M"),
                "note": row.content,
            }
            for row in rows
        ],
    }
