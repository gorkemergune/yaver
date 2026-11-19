import uuid
from collections import Counter

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.core.change_log import NothingToUndoError, latest_change_set, undo_change_set


class UndoArgs(BaseModel):
    change_set_id: str | None = Field(
        None, description="omit to undo the most recent change ('son değişikliği geri al')"
    )


@tool(
    "undo",
    "Undo every change made for one earlier user message (all yavers together).",
    UndoArgs,
    mutates=True,
)
async def undo(args: UndoArgs, ctx: ToolContext) -> ToolResult:
    if args.change_set_id:
        try:
            target = uuid.UUID(args.change_set_id)
        except ValueError as exc:
            raise ToolError("change_set_id is not a valid id") from exc
    else:
        latest = await latest_change_set(ctx.session, exclude=ctx.change_set_id)
        if latest is None:
            raise ToolError("there is nothing to undo")
        target = latest
    try:
        entries = await undo_change_set(ctx.session, target, ctx.now)
    except NothingToUndoError as exc:
        raise ToolError("that change was already undone or does not exist") from exc
    counts = Counter(f"{entry.op.value} {entry.entity}" for entry in entries)
    return {"undone_change_set": str(target), "reverted": dict(counts)}
