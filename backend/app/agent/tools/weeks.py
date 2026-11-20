import datetime as dt

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import ToolContext
from app.agent.tools import ToolResult, tool
from app.core.time_resolver import week_start
from app.db.models import WeekLabel
from app.services.weeks import week_facts


class SetWeekLabelArgs(BaseModel):
    date: dt.date = Field(description="any day of the week, YYYY-MM-DD (resolve 'bu hafta' first)")
    label: str | None = Field(
        None,
        max_length=100,
        description="the week's name, e.g. 'Hackathon Haftası'; null = back to the automatic one",
    )


@tool(
    "set_week_label",
    "Name a week (shown in the week view: '2025-26 Güz · 8. Hafta · Hackathon Haftası'). "
    "Without a name, weeks get an automatic one (Vize/Final/Proje/Tatil Haftası).",
    SetWeekLabelArgs,
    mutates=True,
)
async def set_week_label(args: SetWeekLabelArgs, ctx: ToolContext) -> ToolResult:
    monday = week_start(args.date)
    label = (args.label or "").strip()
    row = await ctx.session.scalar(select(WeekLabel).where(WeekLabel.week_start == monday))
    if not label:
        if row is not None:
            await ctx.recorder.deleted(row)
    elif row is None:
        row = WeekLabel(week_start=monday, label=label)
        ctx.session.add(row)
        await ctx.recorder.created(row)
    elif row.label != label:
        before = ctx.recorder.before_update(row)
        row.label = label
        await ctx.recorder.updated(row, before)
    facts = await week_facts(ctx.session, monday, ctx.tz)
    return {
        "week": {
            "week_start": monday.isoformat(),
            "title": facts.title,
            "label": facts.label,
            "automatic": facts.user_label is None,
        }
    }
