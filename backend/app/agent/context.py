import datetime as dt
import uuid
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.change_log import ChangeRecorder
from app.core.time_resolver import DEFAULT_CLOCK, ClockConvention


@dataclass(slots=True)
class ToolContext:
    """Everything a tool needs. One per user message; shared by all yavers it involves."""

    session: AsyncSession
    now: dt.datetime  # aware
    tz: ZoneInfo
    change_set_id: uuid.UUID
    recorder: ChangeRecorder
    clock: ClockConvention = DEFAULT_CLOCK
    agent_id: str = "yaver"
    # Action log for the reply ("Friday: EE211 lab eklendi"), filled by the tool runner.
    actions: list[dict[str, object]] = field(default_factory=list)

    @property
    def today(self) -> dt.date:
        return self.now.astimezone(self.tz).date()

    def local(self, day: dt.date, time: dt.time) -> dt.datetime:
        return dt.datetime.combine(day, time, tzinfo=self.tz)
