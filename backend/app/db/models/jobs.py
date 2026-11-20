"""Scheduled jobs that ran: one row per job and local day, so a job that fires twice
(misfire catch-up + the regular trigger, two API processes) writes its message once."""

import datetime as dt

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class JobRun(CreatedAtMixin, Base):
    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job_id", "run_on", name="uq_job_runs_job_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(50))  # "briefing", "checkin", "followups"
    run_on: Mapped[dt.date]  # local day it ran for
    status: Mapped[str] = mapped_column(String(20))  # "sent" | "skipped"
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
