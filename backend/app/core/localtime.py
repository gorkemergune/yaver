"""Local wall-clock times -> instants, safe across DST (QA D6).

`dt.datetime.combine(day, time, tzinfo=tz)` is not enough in a zone with daylight saving
(Europe/Istanbul has none since 2016, but APP_TIMEZONE is configurable):
- a time the clock skips (02:30 on the spring-forward night) gets a made-up offset and
  shows as 02:30, an hour that never happened;
- two aware datetimes with the same tzinfo subtract and compare by wall clock, so a
  01:00-04:00 block on that night "lasts" 3 hours instead of 2.

`local_datetime` normalizes through UTC (a skipped time becomes the time the clock jumped
to, a time that happens twice its first occurrence) and `elapsed` measures real time.
"""

import datetime as dt


def local_datetime(day: dt.date, time: dt.time, tz: dt.tzinfo) -> dt.datetime:
    """The instant `time` on `day` names in `tz`, as an aware datetime in `tz`."""
    naive = dt.datetime.combine(day, time.replace(tzinfo=None, fold=0))
    return naive.replace(tzinfo=tz).astimezone(dt.UTC).astimezone(tz)


def elapsed(start: dt.datetime, end: dt.datetime) -> dt.timedelta:
    """Real time between two aware datetimes (not wall-clock time)."""
    return end.astimezone(dt.UTC) - start.astimezone(dt.UTC)
