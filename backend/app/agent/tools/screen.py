import datetime as dt

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.tools import ToolResult, tool
from app.services.screen_time import day_summary, fmt_minutes

TOP_APPS = 8


class GetScreenTimeArgs(BaseModel):
    date: dt.date | None = Field(None, description="last day, YYYY-MM-DD; default today")
    days: int = Field(1, ge=1, le=14, description="how many days up to `date`, e.g. 7 = a week")


@tool(
    "get_screen_time",
    "Screen time on the user's PC per day (sent by the desktop app): total, top apps, "
    "app limits (e.g. VALORANT 90 dk). Read-only.",
    GetScreenTimeArgs,
)
async def get_screen_time(args: GetScreenTimeArgs, ctx: ToolContext) -> ToolResult:
    last = args.date or ctx.today
    out: list[dict[str, object]] = []
    for offset in range(args.days - 1, -1, -1):
        day = last - dt.timedelta(days=offset)
        summary = await day_summary(ctx.session, day, top=TOP_APPS)
        if summary is None:
            out.append({"date": day.isoformat(), "data": "none (desktop app not running?)"})
            continue
        out.append(
            {
                "date": summary["date"],
                "total": fmt_minutes(summary["total_seconds"]),
                "apps": [f"{a['name']}: {fmt_minutes(a['seconds'])}" for a in summary["apps"]],
                "limits": [
                    f"{lim['name']}: {fmt_minutes(lim['used_seconds'])} / "
                    f"{fmt_minutes(lim['limit_seconds'])}"
                    for lim in summary["limits"]
                ],
                "last_sync": summary["updated_at"].astimezone(ctx.tz).strftime("%H:%M"),
            }
        )
    return {"screen_time": out}
