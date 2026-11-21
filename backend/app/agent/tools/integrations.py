"""Tools that reach outside services. A missing key is not an error the user must fix right
now: the tool says the integration is pending and the employee notes it in its notebook
(once a day), instead of raising a red dot."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolError, ToolResult, tool
from app.config import get_settings
from app.db.models import AdReport
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


NO_REPORTS = (
    "Henüz reklam raporu yok: Ads Manager'dan CSV dışa aktarıp ya da tablonun ekran "
    "görüntüsünü sohbete atabilirsin."
)


class AdReportArgs(BaseModel):
    report_id: int | None = Field(None, description="a report number; default: the latest")


@tool(
    "get_ad_report",
    "Meta (Instagram/Facebook) ad reports the user sent as a CSV or screenshot: metrics per "
    "campaign, the change against the previous period and the analysis.",
    AdReportArgs,
)
async def get_ad_report(args: AdReportArgs, ctx: ToolContext) -> ToolResult:
    # app.ads.report builds its analysis tool schema with this package: import it lazily
    from app.ads.report import period_text, report_block

    if args.report_id is not None:
        report = await ctx.session.get(AdReport, args.report_id)
        if report is None:
            raise ToolError(f"no ad report #{args.report_id}")
    else:
        report = await ctx.session.scalar(
            select(AdReport)
            .order_by(AdReport.period_end.desc().nulls_last(), AdReport.id.desc())
            .limit(1)
        )
    if report is None:
        status = ads_status(get_settings())
        return {"status": "no_reports", "message": NO_REPORTS, "account": status.note}
    others = (
        await ctx.session.scalars(
            select(AdReport).where(AdReport.id != report.id).order_by(AdReport.id.desc()).limit(5)
        )
    ).all()
    return {
        "report_id": report.id,
        "report": await report_block(ctx, report, created=None),
        "other_reports": [
            {"report_id": r.id, "period": period_text(r.period_start, r.period_end)} for r in others
        ],
    }
