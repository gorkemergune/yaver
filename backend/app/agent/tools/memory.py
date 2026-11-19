from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.agent.tools.matching import matches
from app.db.models import Memory


class RememberArgs(BaseModel):
    content: str = Field(description="a lasting fact, e.g. 'Cuma günleri Medipol'deyim'")
    category: str = Field("general", description="e.g. general, work, school, health")


@tool("remember", "Store a lasting fact about the user.", RememberArgs, mutates=True)
async def remember(args: RememberArgs, ctx: ToolContext) -> ToolResult:
    memory = Memory(category=args.category, content=args.content, active=True)
    ctx.session.add(memory)
    await ctx.recorder.created(memory)
    return {"remembered": {"memory_id": memory.id, "content": memory.content}}


class ForgetArgs(BaseModel):
    memory_id: int | None = None
    about: str | None = Field(None, description="words from the fact, if the id is unknown")


@tool("forget", "Deactivate a stored fact.", ForgetArgs, mutates=True)
async def forget(args: ForgetArgs, ctx: ToolContext) -> ToolResult:
    if args.memory_id is not None:
        found = await ctx.session.get(Memory, args.memory_id)
        candidates = [found] if found and found.active else []
    else:
        active = (await ctx.session.scalars(select(Memory).where(Memory.active))).all()
        candidates = [m for m in active if args.about and matches(args.about, m.content)]
    if len(candidates) != 1:
        raise ToolError(
            "fact not found or ambiguous",
            candidates=[{"memory_id": m.id, "content": m.content} for m in candidates],
        )
    memory = candidates[0]
    before = ctx.recorder.before_update(memory)
    memory.active = False
    await ctx.recorder.updated(memory, before)
    return {"forgotten": {"memory_id": memory.id, "content": memory.content}}
