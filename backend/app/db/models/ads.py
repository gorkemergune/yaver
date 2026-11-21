"""Ad reports Metrics reads from a file the user sends in the chat (a Meta Ads Manager CSV
export or a screenshot of the table): one `ad_reports` row per file, one `ad_metrics` row
per campaign / ad set / ad. Written in the message's change set (undo removes them)."""

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class AdReport(CreatedAtMixin, Base):
    __tablename__ = "ad_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), default="meta", server_default="meta")
    source: Mapped[str] = mapped_column(String(10))  # csv | image
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL")
    )
    file_sha256: Mapped[str | None] = mapped_column(String(64))  # same file twice: reused
    level: Mapped[str] = mapped_column(String(10))  # campaign | adset | ad
    period_start: Mapped[dt.date | None]
    period_end: Mapped[dt.date | None]
    currency: Mapped[str | None] = mapped_column(String(8))
    # Written by the analysis (summary + exactly 3 recommendations), also in the notebook.
    summary: Mapped[str | None] = mapped_column(Text)
    recommendations: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    analysis_model: Mapped[str | None] = mapped_column(String(100))
    unclear: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (Index("ix_ad_reports_period_end", "period_end"),)


class AdMetric(Base):
    __tablename__ = "ad_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("ad_reports.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[str] = mapped_column(String(10))  # campaign | adset | ad
    name: Mapped[str] = mapped_column(String(300))
    campaign: Mapped[str | None] = mapped_column(String(300))  # for ad sets / ads
    spend: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    impressions: Mapped[int | None] = mapped_column(Integer)
    reach: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # percent (1.25 = %1,25)
    cpc: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    results: Mapped[int | None] = mapped_column(Integer)
    result_type: Mapped[str | None] = mapped_column(String(100))
    cost_per_result: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
