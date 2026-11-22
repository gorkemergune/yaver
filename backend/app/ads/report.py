"""Saving an ad report, comparing it with the previous period (in code) and the analysis
(one structured LLM call on the deep tier: summary + exactly 3 recommendations, written to
Metrics' notebook).

Everything is written through the message's ChangeRecorder: "Geri al" removes the report,
its rows and the notebook entry together.
"""

import datetime as dt
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.ads.parse import AdRow, ParsedAds
from app.agent.context import ToolContext
from app.agent.schema import json_schema
from app.db.models import AdMetric, AdReport
from app.llm.router import LLMUnavailableError
from app.llm.types import ChatMessage, LLMRequest, LLMResponse, ProviderError, ToolSpec
from app.office.notebook import note_event, write_note

logger = logging.getLogger(__name__)

ANALYSIS_PURPOSE = "ads_weekly_report"  # deep tier (Opus), providers.yaml
MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
DASH = "-"  # date ranges: "9-15 Kas 2026"
LEVEL_NAMES = {"campaign": "kampanya", "adset": "reklam seti", "ad": "reklam"}


# ---- saving ----------------------------------------------------------------------------


async def save_report(
    ctx: ToolContext,
    parsed: ParsedAds,
    *,
    source: str,
    attachment_id: int | None,
    sha256: str | None,
) -> tuple[AdReport, bool]:
    """(report, created). The same file sent again returns the report saved before."""
    if sha256:
        existing = await ctx.session.scalar(
            select(AdReport).where(AdReport.file_sha256 == sha256).order_by(AdReport.id)
        )
        if existing is not None:
            return existing, False
    report = AdReport(
        source=source,
        attachment_id=attachment_id,
        file_sha256=sha256,
        level=parsed.level,
        period_start=parsed.period_start,
        period_end=parsed.period_end,
        currency=parsed.currency,
        unclear=parsed.unclear or None,
        created_at=ctx.now,
    )
    ctx.session.add(report)
    await ctx.recorder.created(report)
    for row in parsed.rows:
        metric = AdMetric(
            report_id=report.id,
            level=row.level,
            name=row.name,
            campaign=row.campaign,
            spend=row.spend,
            impressions=row.impressions,
            reach=row.reach,
            clicks=row.clicks,
            ctr=row.ctr,
            cpc=row.cpc,
            results=row.results,
            result_type=row.result_type,
            cost_per_result=row.cost_per_result,
        )
        ctx.session.add(metric)
        await ctx.recorder.created(metric)
    return report, True


async def rows_of(ctx: ToolContext, report: AdReport) -> list[AdRow]:
    metrics = (
        await ctx.session.scalars(
            select(AdMetric).where(AdMetric.report_id == report.id).order_by(AdMetric.id)
        )
    ).all()
    return [
        AdRow(
            level=m.level,
            name=m.name,
            campaign=m.campaign,
            spend=m.spend,
            impressions=m.impressions,
            reach=m.reach,
            clicks=m.clicks,
            ctr=m.ctr,
            cpc=m.cpc,
            results=m.results,
            result_type=m.result_type,
            cost_per_result=m.cost_per_result,
        )
        for m in metrics
    ]


async def previous_report(ctx: ToolContext, report: AdReport) -> AdReport | None:
    """The latest report of an earlier period (same level); without dates: sent earlier."""
    query = select(AdReport).where(AdReport.id != report.id, AdReport.level == report.level)
    if report.period_start is not None:
        query = query.where(AdReport.period_end < report.period_start).order_by(
            AdReport.period_end.desc(), AdReport.id.desc()
        )
    else:
        query = query.where(AdReport.id < report.id).order_by(AdReport.id.desc())
    return await ctx.session.scalar(query.limit(1))


# ---- comparison (code) -----------------------------------------------------------------


@dataclass(slots=True)
class Totals:
    spend: Decimal
    impressions: int
    clicks: int
    results: int

    @property
    def ctr(self) -> Decimal | None:
        return Decimal(self.clicks) * 100 / self.impressions if self.impressions else None

    @property
    def cpc(self) -> Decimal | None:
        return self.spend / self.clicks if self.clicks else None

    @property
    def cost_per_result(self) -> Decimal | None:
        return self.spend / self.results if self.results else None


def totals(rows: list[AdRow]) -> Totals:
    return Totals(
        spend=sum((r.spend or Decimal(0) for r in rows), Decimal(0)),
        impressions=sum(r.impressions or 0 for r in rows),
        clicks=sum(r.clicks or 0 for r in rows),
        results=sum(r.results or 0 for r in rows),
    )


def change(now: Decimal | int | None, before: Decimal | int | None) -> str:
    """'+%12,5' / '-%3,0' / 'yeni' / '' (nothing to compare)."""
    if now is None or before is None:
        return ""
    if before == 0:
        return "" if now == 0 else "yeni"
    percent = (Decimal(now) - Decimal(before)) * 100 / Decimal(before)
    sign = "+" if percent >= 0 else "-"
    return f"{sign}%{tr_number(abs(percent), 1)}"


def tr_number(value: Decimal | int | float | None, digits: int = 2) -> str:
    """1234.5 -> '1.234,50' (Turkish separators)."""
    if value is None:
        return "-"
    text = f"{Decimal(value):,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def period_text(start: dt.date | None, end: dt.date | None) -> str:
    if start is None or end is None:
        return "dönem bilinmiyor"
    if start.year == end.year and start.month == end.month:
        return f"{start.day}{DASH}{end.day} {MONTHS[end.month - 1]} {end.year}"
    if start.year == end.year:
        first = f"{start.day} {MONTHS[start.month - 1]}"
        return f"{first} {DASH} {end.day} {MONTHS[end.month - 1]} {end.year}"
    return f"{start:%d.%m.%Y} {DASH} {end:%d.%m.%Y}"


def comparison_table(rows: list[AdRow], previous: list[AdRow] | None, currency: str | None) -> str:
    """Markdown: one line per row and a total, each metric with its change vs. the previous
    period (rows matched by name)."""
    money = currency or ""
    before = {(r.level, r.name): r for r in previous or []}
    lines = [
        "| Ad | Harcama | Gösterim | Tıklama | CTR | CPC | Sonuç | Sonuç başı maliyet |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def cells(
        name: str,
        spend: Decimal | None,
        impressions: int | None,
        clicks: int | None,
        ctr: Decimal | None,
        cpc: Decimal | None,
        results: int | None,
        result_type: str | None,
        cpr: Decimal | None,
        old: Any,
    ) -> str:
        def with_change(text: str, now: Any, attr: str) -> str:
            delta = change(now, getattr(old, attr)) if old is not None else ""
            return f"{text} ({delta})" if delta else text

        result_text = f"{results}" + (f" {result_type}" if result_type else "")
        return (
            f"| {name} | {with_change(f'{tr_number(spend)} {money}'.strip(), spend, 'spend')} "
            f"| {with_change(tr_number(impressions, 0), impressions, 'impressions')} "
            f"| {with_change(tr_number(clicks, 0), clicks, 'clicks')} "
            f"| {with_change('%' + tr_number(ctr), ctr, 'ctr')} "
            f"| {with_change(tr_number(cpc), cpc, 'cpc')} "
            f"| {with_change(result_text if results is not None else '-', results, 'results')} "
            f"| {with_change(tr_number(cpr), cpr, 'cost_per_result')} |"
        )

    for row in rows:
        lines.append(
            cells(
                row.name,
                row.spend,
                row.impressions,
                row.clicks,
                row.ctr,
                row.cpc,
                row.results,
                row.result_type,
                row.cost_per_result,
                before.get((row.level, row.name)),
            )
        )
    now_total = totals(rows)
    old_total = totals(previous) if previous else None
    lines.append(
        cells(
            "**Toplam**",
            now_total.spend,
            now_total.impressions,
            now_total.clicks,
            now_total.ctr,
            now_total.cpc,
            now_total.results,
            None,
            now_total.cost_per_result,
            old_total,
        )
    )
    current = {(x.level, x.name) for x in rows}
    gone = [r.name for r in previous or [] if (r.level, r.name) not in current]
    if gone:
        lines.append(f"Önceki dönemde olup bu dönemde olmayan: {', '.join(gone)}")
    return "\n".join(lines)


async def report_block(
    ctx: ToolContext, report: AdReport, *, created: bool | None, label: str = ""
) -> str:
    """What the team (Metrics) sees: "[Reklam raporu <label>: ...]" + comparison table
    (+ the analysis once done)."""
    rows = await rows_of(ctx, report)
    previous = await previous_report(ctx, report)
    previous_rows = await rows_of(ctx, previous) if previous else None
    level = LEVEL_NAMES.get(report.level, report.level)
    if created is None:
        saved = "kayıtlı"
    else:
        saved = "kaydedildi" if created else "bu dosya daha önce kaydedilmişti"
    if previous is not None:
        span = period_text(previous.period_start, previous.period_end)
        against = f"önceki dönem: rapor #{previous.id} ({span})"
    else:
        against = "karşılaştırılacak önceki dönem yok"
    title = f"Reklam raporu {label}".strip()
    parts = [
        f"[{title}: Meta, {period_text(report.period_start, report.period_end)}, "
        f"{len(rows)} {level} -> rapor #{report.id} {saved}; {against}]",
        comparison_table(rows, previous_rows, report.currency),
    ]
    if report.unclear:
        parts.append("Belirsiz (tahmin edilmedi): " + "; ".join(report.unclear))
    if report.summary and report.recommendations:
        parts.append(analysis_text(report))
    return "\n".join(parts)


def analysis_text(report: AdReport) -> str:
    recs = "\n".join(f"{i}. {r}" for i, r in enumerate(report.recommendations or [], start=1))
    return f"Analiz (Metrics'in defterine yazıldı):\nÖzet: {report.summary}\nÖneriler:\n{recs}"


# ---- analysis (LLM, deep tier) ---------------------------------------------------------


class AdAnalysis(BaseModel):
    summary: str = Field(
        max_length=700,
        description="2-3 Turkish sentences: total spend and the biggest changes vs. the "
        "previous period, numbers taken from the table only",
    )
    recommendations: list[str] = Field(
        min_length=3,
        max_length=3,
        description="exactly 3 concrete Turkish actions, one sentence each, naming the "
        "campaign / ad set and the metric that motivates it",
    )


ANALYSIS_TOOL = ToolSpec(
    "ad_analysis", "Return the summary and the 3 recommendations.", json_schema(AdAnalysis)
)
ANALYSIS_PROMPT = (
    "You are Metrics, the ad analyst of a Turkish user's small team. You get one period's "
    "Meta ad metrics as a table; each value may carry its change against the previous "
    "period in parentheses. Call ad_analysis exactly once.\n"
    "- summary: 2-3 Turkish sentences. Total spend, cost per result and the biggest movers. "
    "Use only numbers in the table; never invent or recompute a number that is not there.\n"
    "- recommendations: a JSON array of exactly 3 separate strings, each a concrete action "
    "the user can take this week "
    "(shift budget between named campaigns, pause or refresh a weak ad, test a new "
    "creative or audience), each tied to a metric from the table.\n"
    "- No previous period: say so in the summary and base the recommendations on how the "
    "rows compare with each other.\n"
    "- Use 'sen' (never 'siz'). Turkish number format (1.234,50)."
)


ANALYSIS_ATTEMPTS = 2  # one retry when the arguments don't fit the schema
RETRY_NOTE = (
    "Your previous ad_analysis call was rejected: recommendations must be a JSON array of "
    "exactly 3 separate strings, one recommendation per string."
)
_NUMBERED = re.compile(r"(?:^|\s)(?=[1-9][.)]\s)")


def split_recommendations(value: Any) -> Any:
    """Three recommendations written into one string ("1. ... 2. ... 3. ..." or one per
    line) become three items; anything else is left for the schema to judge."""
    if not (isinstance(value, list) and len(value) == 1 and isinstance(value[0], str)):
        return value
    text = value[0].strip()
    numbered = [re.sub(r"^[1-9][.)]\s*", "", p).strip() for p in _NUMBERED.split(text)]
    numbered = [p for p in numbered if p]
    if len(numbered) == 3:
        return numbered
    lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip(" -•\t")]
    return lines if len(lines) == 3 else value


async def analyze(ctx: ToolContext, report: AdReport, agent_id: str) -> str:
    """Summary + 3 recommendations on the report and in the notebook; returns the block
    text the employee relays (or why there is no analysis)."""
    if report.summary and report.recommendations:
        return analysis_text(report)
    if ctx.llm is None:
        return "Analiz yapılamadı: model yok."
    table = await report_block(ctx, report, created=True)
    system = ANALYSIS_PROMPT
    result: AdAnalysis | None = None
    for attempt in range(ANALYSIS_ATTEMPTS):
        try:
            response: LLMResponse = await ctx.llm.complete(
                LLMRequest(
                    system=system,
                    messages=[ChatMessage("user", table)],
                    tools=[ANALYSIS_TOOL],
                    tool_choice="required",
                    max_tokens=16000,
                ),
                purpose=ANALYSIS_PURPOSE,
                agent_id=agent_id,
            )
            call = next((c for c in response.tool_calls if c.name == ANALYSIS_TOOL.name), None)
            if call is None or call.arguments is None:
                raise ValueError("the model did not call ad_analysis")
            arguments = dict(call.arguments)
            arguments["recommendations"] = split_recommendations(arguments.get("recommendations"))
            result = AdAnalysis.model_validate(arguments)
            break
        except (LLMUnavailableError, ProviderError) as exc:
            logger.warning("Ad report %s: analysis failed: %s", report.id, exc)
            break  # no model now: asking again won't help
        except (ValidationError, ValueError) as exc:
            logger.warning("Ad report %s: analysis attempt %s: %s", report.id, attempt + 1, exc)
            system = f"{ANALYSIS_PROMPT}\n{RETRY_NOTE}"
    if result is None:
        return "Analiz şu an yapılamadı (model yanıt vermedi); tablo kaydedildi."
    before = ctx.recorder.before_update(report)
    report.summary = result.summary.strip()
    report.recommendations = [r.strip() for r in result.recommendations]
    report.analysis_model = response.model
    await ctx.recorder.updated(report, before)
    note = await write_note(
        ctx.session,
        agent_id,
        f"Reklam analizi, {period_text(report.period_start, report.period_end)} "
        f"(rapor #{report.id}): {report.summary}\n"
        + "\n".join(f"{i}. {r}" for i, r in enumerate(report.recommendations, start=1)),
        ctx.now,
        ctx.tz,
        recorder=ctx.recorder,
    )
    if note is not None:
        ctx.notes.append(note_event(note))
    return analysis_text(report)
