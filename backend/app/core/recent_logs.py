"""The last few hundred log lines in memory, for a bug report's "log özeti": warnings and
errors from anywhere, plus the routing / handoff lines of app.agent (INFO). Nothing is
written to disk; a restart empties it. Secrets never reach it (the access log's query
parameters are masked by log_filters, and uvicorn.access is not kept here at all)."""

import datetime as dt
import logging
from collections import deque
from dataclasses import dataclass

CAPACITY = 400
LINE_CHARS = 300
KEEP_INFO_FROM = ("app.agent",)  # "intents for ...", "... handed ... back", "declined"


@dataclass(frozen=True, slots=True)
class Line:
    at: dt.datetime
    level: str
    logger: str
    text: str

    def render(self) -> str:
        return f"{self.at:%H:%M:%S} {self.level} {self.logger}: {self.text}"


_lines: deque[Line] = deque(maxlen=CAPACITY)


class RecentHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("uvicorn.access"):
            return
        if record.levelno < logging.WARNING and not record.name.startswith(KEEP_INFO_FROM):
            return
        try:
            text = record.getMessage()
        except Exception:  # a bad format string must not break logging
            text = str(record.msg)
        _lines.append(
            Line(
                dt.datetime.fromtimestamp(record.created, dt.UTC),
                record.levelname,
                record.name,
                " ".join(text.split())[:LINE_CHARS],
            )
        )


def install() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, RecentHandler) for h in root.handlers):
        root.addHandler(RecentHandler(level=logging.INFO))
    for name in KEEP_INFO_FROM:  # INFO of these must reach the root handler
        log = logging.getLogger(name)
        if log.getEffectiveLevel() > logging.INFO:
            log.setLevel(logging.INFO)


def between(start: dt.datetime, end: dt.datetime, limit: int = 30) -> list[Line]:
    return [line for line in list(_lines) if start <= line.at <= end][-limit:]


def clear() -> None:
    """Tests only."""
    _lines.clear()
