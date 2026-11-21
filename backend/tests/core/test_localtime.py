"""QA D6: local times in a zone with daylight saving (Europe/Berlin; Istanbul has none)."""

import datetime as dt
from zoneinfo import ZoneInfo

from app.core.localtime import elapsed, local_datetime
from app.db.models import RecurringBlock
from app.db.models.enums import BlockKind
from app.services.attendance import class_hours
from app.services.schedule import day_window, occurrence_interval

BERLIN = ZoneInfo("Europe/Berlin")
IST = ZoneInfo("Europe/Istanbul")
SPRING = dt.date(2027, 3, 28)  # 02:00 -> 03:00
AUTUMN = dt.date(2027, 10, 31)  # 03:00 -> 02:00


def block(start: str, end: str) -> RecurringBlock:
    return RecurringBlock(
        kind=BlockKind.OTHER,
        title="Gece vardiyası",
        weekday=6,
        start_time=dt.time.fromisoformat(start),
        end_time=dt.time.fromisoformat(end),
    )


def test_a_skipped_time_is_the_time_the_clock_jumped_to() -> None:
    at = local_datetime(SPRING, dt.time(2, 30), BERLIN)

    assert at.time() == dt.time(3, 30)
    assert at.utcoffset() == dt.timedelta(hours=2)
    assert at.astimezone(dt.UTC) == dt.datetime(2027, 3, 28, 1, 30, tzinfo=dt.UTC)


def test_a_time_that_happens_twice_is_its_first_occurrence() -> None:
    at = local_datetime(AUTUMN, dt.time(2, 30), BERLIN)

    assert at.utcoffset() == dt.timedelta(hours=2)  # still summer time
    assert at.astimezone(dt.UTC) == dt.datetime(2027, 10, 31, 0, 30, tzinfo=dt.UTC)


def test_durations_are_real_time_across_a_change() -> None:
    spring_start, spring_end = occurrence_interval(block("01:00", "04:00"), SPRING, BERLIN)
    autumn_start, autumn_end = occurrence_interval(block("01:00", "04:00"), AUTUMN, BERLIN)
    short_day = day_window(SPRING, BERLIN)

    assert elapsed(spring_start, spring_end) == dt.timedelta(hours=2)
    assert class_hours(spring_start, spring_end) == 2
    assert elapsed(autumn_start, autumn_end) == dt.timedelta(hours=4)
    assert class_hours(autumn_start, autumn_end) == 4
    assert elapsed(*short_day) == dt.timedelta(hours=23)


def test_nothing_changes_without_daylight_saving() -> None:
    day = dt.date(2027, 3, 28)
    for hour in range(24):
        time = dt.time(hour, 30)
        assert local_datetime(day, time, IST) == dt.datetime.combine(day, time, tzinfo=IST)
    start, end = occurrence_interval(block("23:00", "01:00"), day, IST)
    assert elapsed(start, end) == dt.timedelta(hours=2)
