import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any
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
    conversation_id: int | None = None
    llm: Any = None  # LLM client for tools that need a model themselves (schedule parsing)
    # Proposals created while answering this message: the user has not seen their table
    # yet, so they cannot be applied before the next message (the user's "evet").
    new_proposals: set[int] = field(default_factory=set)
    # Action log for the reply ("Friday: EE211 lab eklendi"), filled by the tool runner.
    actions: list[dict[str, object]] = field(default_factory=list)
    # Every tool call (reads too) with its arguments, for debugging and prompt tuning.
    trace: list[dict[str, object]] = field(default_factory=list)

    @property
    def today(self) -> dt.date:
        return self.now.astimezone(self.tz).date()

    def local(self, day: dt.date, time: dt.time) -> dt.datetime:
        return dt.datetime.combine(day, time, tzinfo=self.tz)
