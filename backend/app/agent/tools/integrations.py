"""Tools that reach outside services. A missing key is not an error the user must fix right
now: the tool says the integration is pending and the employee notes it in its notebook
(once a day), instead of raising a red dot."""

from typing import Any

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.config import get_settings
from app.integrations import web_search as search
from app.integrations.meta_ads import ads_status
from app.office.notebook import note_event, write_note


async def _pending(ctx: ToolContext, integration: str, note: str) -> ToolResult:
    written = await write_note(
        ctx.session, ctx.agent_id, note, ctx.now, ctx.tz, recorder=ctx.recorder, once_a_day=True
    )
    if written is not None:
        ctx.notes.append(note_event(written))
    return {
        "status": "integration_pending",
        "integration": integration,
        "message": note,  # in the notebook: tell the user in one sentence, don't ask them
    }


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    max_results: int = Field(5, ge=1, le=8)


@tool("web_search", "Search the web; results with title, url and snippet.", WebSearchArgs)
async def web_search(args: WebSearchArgs, ctx: ToolContext) -> ToolResult:
    provider = search.get_web_search()
    if provider is None:
        return await _pending(ctx, "web_search", search.PENDING_NOTE)
    try:
        results = await provider.search(args.query, args.max_results)
    except search.SearchError as exc:
        raise ToolError(str(exc)) from exc
    found: list[dict[str, Any]] = [r.as_dict() for r in results]
    return {"query": args.query, "results": found}


class AdReportArgs(BaseModel):
    days: int = Field(7, ge=1, le=90, description="the last N days")


@tool(
    "get_ad_report", "Ad performance from the Meta (Instagram/Facebook) ad account.", AdReportArgs
)
async def get_ad_report(args: AdReportArgs, ctx: ToolContext) -> ToolResult:
    status = ads_status(get_settings())
    return await _pending(ctx, "meta_ads", status.note)
