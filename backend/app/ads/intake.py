"""Ad report files sent in the chat -> saved reports + "[Reklam raporu N ...]" blocks.

CSV exports are parsed in code. Screenshots of the Ads Manager table are read by Claude
(Sonnet, `ads_image`) into the same rows; numbers it could not read go to "unclear",
and the period is taken as written and parsed in code. Both are saved right away (the
user sent the file to be analysed; "Geri al" removes it) and listed in ctx.ad_reports, so
the coordinator hands the message to Metrics for the analysis.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.ads.parse import AdRow, AdsParseError, ParsedAds, parse_meta_csv, parse_period
from app.ads.report import report_block, save_report
from app.agent.context import ToolContext

logger = logging.getLogger(__name__)

CSV_MIME = "text/csv"
IMAGE_PURPOSE = "ads_image"  # smart (Sonnet): a table of numbers on a screenshot


@dataclass(slots=True)
class AdFileInput:
    attachment_id: int
    filename: str
    data: bytes
    sha256: str | None


async def read_ad_files(ctx: ToolContext, files: list[AdFileInput], first: int = 1) -> str:
    blocks = []
    for number, item in enumerate(files, start=first):
        try:
            parsed = parse_meta_csv(item.data)
        except AdsParseError as exc:
            blocks.append(f"[Dosya {number}: {item.filename}: okunamadı. {exc}]")
            continue
        blocks.append(
            await import_report(
                ctx,
                parsed,
                source="csv",
                attachment_id=item.attachment_id,
                sha256=item.sha256,
                label=f"{number} ({item.filename})",
            )
        )
    return "\n\n".join(blocks)


async def import_report(
    ctx: ToolContext,
    parsed: ParsedAds,
    *,
    source: str,
    attachment_id: int | None,
    sha256: str | None,
    label: str,
) -> str:
    report, created = await save_report(
        ctx, parsed, source=source, attachment_id=attachment_id, sha256=sha256
    )
    if report.id not in ctx.ad_reports:
        ctx.ad_reports.append(report.id)
    return await report_block(ctx, report, created=created, label=label)


# ---- screenshots -----------------------------------------------------------------------


class AdImageRow(BaseModel):
    name: str = Field(description="campaign / ad set / ad name as shown")
    campaign: str | None = Field(None, description="its campaign, if the row is an ad set / ad")
    spend: float | None = Field(None, description="amount spent, as a plain number")
    impressions: int | None = None
    reach: int | None = None
    clicks: int | None = Field(None, description="link clicks if shown, else all clicks")
    ctr: float | None = Field(None, description="CTR in percent (1.25 for 1,25%)")
    cpc: float | None = None
    results: int | None = None
    result_type: str | None = Field(None, description="what a result is, as shown")
    cost_per_result: float | None = None


class AdsImage(BaseModel):
    level: Literal["campaign", "adset", "ad"]
    period_text: str | None = Field(
        None, description="the date range exactly as written ('9 Kas 2026 - 15 Kas 2026')"
    )
    currency: str | None = Field(None, description="ISO code if visible (TRY, USD, EUR)")
    rows: list[AdImageRow]
    unclear: list[str] = Field(default_factory=list)


ADS_IMAGE_PROMPT = (
    "You read a screenshot of an ads dashboard table (Meta Ads Manager) for a Turkish user. "
    "Call ads_table exactly once.\n"
    "- One row per campaign / ad set / ad line; skip the total line.\n"
    "- Numbers as plain numbers: '₺1.234,56' -> 1234.56, '%1,25' -> 1.25. A cell you "
    "cannot read with certainty is left out (null) and quoted in unclear; never guess.\n"
    "- period_text: the date range exactly as written; never compute or complete a date."
)


def parsed_from_image(reading: AdsImage) -> ParsedAds:
    def money(value: float | None) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    rows = [
        AdRow(
            level=reading.level,
            name=row.name.strip()[:300],
            campaign=row.campaign if reading.level != "campaign" else None,
            spend=money(row.spend),
            impressions=row.impressions,
            reach=row.reach,
            clicks=row.clicks,
            ctr=money(row.ctr),
            cpc=money(row.cpc),
            results=row.results,
            result_type=row.result_type,
            cost_per_result=money(row.cost_per_result),
        ).complete()
        for row in reading.rows
        if row.name.strip()
    ]
    unclear = list(reading.unclear)
    period = parse_period(reading.period_text)
    if period is None and reading.period_text:
        unclear.append(f"Tarih aralığı: {reading.period_text}")
    return ParsedAds(
        level=reading.level,
        rows=rows,
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
        currency=(reading.currency or "").upper()[:8] or None,
        unclear=unclear,
    )
