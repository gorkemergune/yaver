"""Turkish date phrases -> dates. Reference day: Thursday 19 November 2026 unless noted."""

import datetime as dt

import pytest

from app.core.time_resolver import (
    CalendarDay,
    ClockConvention,
    DateSpan,
    Direction,
    PartOfDay,
    Reason,
    Resolution,
    Status,
    TimeSlot,
    build_calendar_context,
    format_calendar_context,
    normalize,
    resolve,
)

THU = dt.date(2026, 11, 19)  # Thursday; week Mon 16 - Sun 22 Nov
TERM_START = dt.date(2026, 9, 28)
TERM_END = dt.date(2027, 1, 8)
RIGHT_QUOTE = chr(0x2019)  # phone keyboards type a curly apostrophe
EN_DASH = chr(0x2013)


def d(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


def res(text: str, today: dt.date = THU) -> Resolution:
    return resolve(text, today, term_start=TERM_START, term_end=TERM_END)


def assert_day(result: Resolution, iso: str) -> None:
    assert result.status is Status.RESOLVED, result
    assert result.span == DateSpan.day(d(iso)), result


def assert_range(result: Resolution, start: str, end: str) -> None:
    assert result.status is Status.RESOLVED, result
    assert result.span == DateSpan(d(start), d(end)), result


def assert_ambiguous(result: Resolution, reason: Reason, *candidates: str) -> None:
    assert result.status is Status.AMBIGUOUS, result
    assert result.reason is reason, result
    assert result.span is None
    assert [c.start.isoformat() for c in result.candidates] == list(candidates), result


def assert_unresolved(result: Resolution, reason: Reason) -> None:
    assert result.status is Status.UNRESOLVED, result
    assert result.reason is reason, result
    assert result.span is None
    assert result.candidates == ()


def test_reference_day_is_a_thursday() -> None:
    assert THU.weekday() == 3


# --- the phrases requested for 0.3 -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "start", "end", "part"),
    [
        ("cumaya", "2026-11-20", "2026-11-20", None),
        ("pazartesiye", "2026-11-23", "2026-11-23", None),
        ("haftaya salı", "2026-11-24", "2026-11-24", None),
        ("öbür gün", "2026-11-21", "2026-11-21", None),
        ("bu akşam", "2026-11-19", "2026-11-19", PartOfDay.EVENING),
        ("yarın sabah", "2026-11-20", "2026-11-20", PartOfDay.MORNING),
        ("önümüzdeki hafta", "2026-11-23", "2026-11-29", None),
        ("ayın 28'i", "2026-11-28", "2026-11-28", None),
        ("28-29 kasım", "2026-11-28", "2026-11-29", None),
        ("3 hafta sonra", "2026-12-10", "2026-12-10", None),
        ("dönem sonu", "2027-01-08", "2027-01-08", None),
    ],
)
def test_requested_phrases(text: str, start: str, end: str, part: PartOfDay | None) -> None:
    result = res(text)

    assert_range(result, start, end)
    assert result.part_of_day is part


def test_term_end_needs_a_known_term() -> None:
    assert_unresolved(resolve("dönem sonu", THU), Reason.TERM_UNKNOWN)


# --- case, Turkish letters and suffixes ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "cuma",
        "Cuma",
        "CUMA",
        "cumaya",
        "Cuma'ya",
        f"Cuma{RIGHT_QUOTE}ya",
        "CUMA'YA",
        "CuMaYa",
        "cuma günü",
        "Cuma Günü",
        "cumadan",
        "cumaki",
        "  cuma  ",
        "cuma.",
    ],
)
def test_friday_spellings(text: str) -> None:
    assert_day(res(text), "2026-11-20")


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("pazartesi", "2026-11-23"),
        ("PAZARTESİ", "2026-11-23"),
        ("PAZARTESİYE", "2026-11-23"),
        ("Pazartesi'ye", "2026-11-23"),
        ("pazartesiden", "2026-11-23"),
        ("salı", "2026-11-24"),
        ("SALI", "2026-11-24"),
        ("sali", "2026-11-24"),
        ("Salı'ya", "2026-11-24"),
        ("salıdan", "2026-11-24"),
        ("çarşamba", "2026-11-25"),
        ("ÇARŞAMBA", "2026-11-25"),
        ("carsambaya", "2026-11-25"),
        ("cumartesi", "2026-11-21"),
        ("Cumartesiye", "2026-11-21"),
        ("pazar", "2026-11-22"),
        ("pazara", "2026-11-22"),
        ("PAZARIN", "2026-11-22"),
    ],
)
def test_weekday_spellings_and_suffixes(text: str, iso: str) -> None:
    assert_day(res(text), iso)


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("bugün", "2026-11-19"),
        ("BUGÜN", "2026-11-19"),
        ("bu gün", "2026-11-19"),
        ("yarın", "2026-11-20"),
        ("YARIN", "2026-11-20"),
        ("Yarın'a", "2026-11-20"),
        ("yarin", "2026-11-20"),
        ("öbür gün", "2026-11-21"),
        ("ÖBÜR GÜN", "2026-11-21"),
        ("öbürgün", "2026-11-21"),
        ("obur gun", "2026-11-21"),
        ("yarından sonra", "2026-11-21"),
        ("dün", "2026-11-18"),
        ("DÜN", "2026-11-18"),
        ("evvelsi gün", "2026-11-17"),
        ("haftaya bugün", "2026-11-26"),
    ],
)
def test_relative_days(text: str, iso: str) -> None:
    assert_day(res(text), iso)


def test_normalize_handles_turkish_case_and_punctuation() -> None:
    assert normalize("İKİ GÜN SONRA") == "iki gun sonra"
    assert normalize("ŞUBAT'TA") == "subatta"
    assert normalize(f"28{EN_DASH}29 KASIM") == "28-29 kasim"
    assert normalize("  Öbür   Gün. ") == "obur gun"
    assert normalize("ıIiİ") == "iiii"


# --- weekday variants ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("bu cuma", "2026-11-20"),
        ("bu pazar", "2026-11-22"),
        ("bu perşembe", "2026-11-19"),  # today counts as "this" Thursday
        ("bu haftaki cuma", "2026-11-20"),
        ("haftaya salı", "2026-11-24"),
        ("Haftaya Salı", "2026-11-24"),
        ("HAFTAYA SALI'YA", "2026-11-24"),
        ("haftaya cuma", "2026-11-27"),
        ("haftaya pazartesi", "2026-11-23"),
        ("gelecek hafta çarşamba", "2026-11-25"),
        ("önümüzdeki hafta perşembe", "2026-11-26"),
        ("önümüzdeki cuma", "2026-11-20"),
        ("önümüzdeki perşembe", "2026-11-26"),  # next one after today
        ("gelecek salı", "2026-11-24"),  # this week's Tuesday is past -> unambiguous
        ("gelecek pazartesi", "2026-11-23"),
        ("geçen cuma", "2026-11-13"),
        ("geçen perşembe", "2026-11-12"),
        ("geçen hafta salı", "2026-11-10"),
        ("geçen haftaki pazar", "2026-11-15"),
    ],
)
def test_weekday_variants(text: str, iso: str) -> None:
    assert_day(res(text), iso)


@pytest.mark.parametrize(
    ("text", "reason", "candidates"),
    [
        ("perşembe", Reason.SAME_WEEKDAY, ("2026-11-19", "2026-11-26")),
        ("PERŞEMBEYE", Reason.SAME_WEEKDAY, ("2026-11-19", "2026-11-26")),
        ("bu salı", Reason.PAST_THIS_WEEK, ("2026-11-17", "2026-11-24")),
        ("gelecek cuma", Reason.THIS_OR_NEXT_WEEK, ("2026-11-20", "2026-11-27")),
        ("gelecek cumartesi", Reason.THIS_OR_NEXT_WEEK, ("2026-11-21", "2026-11-28")),
    ],
)
def test_ambiguous_weekdays(text: str, reason: Reason, candidates: tuple[str, ...]) -> None:
    assert_ambiguous(res(text), reason, *candidates)


@pytest.mark.parametrize("today_offset", range(7))
@pytest.mark.parametrize("weekday", range(7))
def test_weekday_rules_hold_for_every_day_of_the_week(today_offset: int, weekday: int) -> None:
    today = d("2026-11-16") + dt.timedelta(days=today_offset)  # Mon..Sun
    names = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
    name = names[weekday]
    next_monday = d("2026-11-23")

    bare = resolve(name, today)
    if weekday == today.weekday():
        assert bare.status is Status.AMBIGUOUS
    else:
        assert bare.start is not None
        assert 1 <= (bare.start - today).days <= 6
        assert bare.start.weekday() == weekday

    next_week = resolve(f"haftaya {name}", today)
    assert next_week.start == next_monday + dt.timedelta(days=weekday)

    upcoming = resolve(f"önümüzdeki {name}", today)
    assert upcoming.start is not None
    assert 1 <= (upcoming.start - today).days <= 7

    last = resolve(f"geçen {name}", today)
    assert last.start is not None
    assert 1 <= (today - last.start).days <= 7


# --- weeks, weekends, months -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("bu hafta", "2026-11-16", "2026-11-22"),
        ("bu hafta içinde", "2026-11-16", "2026-11-22"),
        ("önümüzdeki hafta", "2026-11-23", "2026-11-29"),
        ("ÖNÜMÜZDEKİ HAFTA", "2026-11-23", "2026-11-29"),
        ("gelecek hafta", "2026-11-23", "2026-11-29"),
        ("haftaya", "2026-11-23", "2026-11-29"),
        ("gelecek haftaya", "2026-11-23", "2026-11-29"),
        ("geçen hafta", "2026-11-09", "2026-11-15"),
        ("hafta sonu", "2026-11-21", "2026-11-22"),
        ("bu hafta sonu", "2026-11-21", "2026-11-22"),
        ("haftasonu", "2026-11-21", "2026-11-22"),
        ("hafta sonuna", "2026-11-21", "2026-11-22"),
        ("gelecek hafta sonu", "2026-11-28", "2026-11-29"),
        ("haftaya hafta sonu", "2026-11-28", "2026-11-29"),
        ("geçen hafta sonu", "2026-11-14", "2026-11-15"),
        ("hafta içi", "2026-11-16", "2026-11-20"),
        ("bu ay", "2026-11-01", "2026-11-30"),
        ("gelecek ay", "2026-12-01", "2026-12-31"),
        ("önümüzdeki ay", "2026-12-01", "2026-12-31"),
        ("geçen ay", "2026-10-01", "2026-10-31"),
        ("kasım ayında", "2026-11-01", "2026-11-30"),
        ("aralıkta", "2026-12-01", "2026-12-31"),
        ("ocakta", "2027-01-01", "2027-01-31"),  # nearest January is next year
        ("ekimde", "2026-10-01", "2026-10-31"),  # nearest October just passed
        ("şubat 2028", "2028-02-01", "2028-02-29"),
    ],
)
def test_week_and_month_ranges(text: str, start: str, end: str) -> None:
    assert_range(res(text), start, end)


def test_month_half_a_year_away_is_ambiguous() -> None:
    result = res("mayısta")

    assert result.status is Status.AMBIGUOUS
    assert result.reason is Reason.YEAR
    assert [c.start.year for c in result.candidates] == [2026, 2027]


# --- day of month ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("ayın 28'i", "2026-11-28"),
        ("Ayın 28'i", "2026-11-28"),
        ("AYIN 28'İ", "2026-11-28"),
        ("ayın 28'inde", "2026-11-28"),
        ("ayın 28si", "2026-11-28"),
        ("28'i", "2026-11-28"),
        ("28'inde", "2026-11-28"),
        ("ayın 19'u", "2026-11-19"),  # today
        ("ayın 30'u", "2026-11-30"),
        ("bu ayın 15'i", "2026-11-15"),  # explicit "bu": past is fine
        ("gelecek ayın 5'i", "2026-12-05"),
        ("önümüzdeki ayın 2'si", "2026-12-02"),
        ("geçen ayın 3'ü", "2026-10-03"),
    ],
)
def test_day_of_month(text: str, iso: str) -> None:
    assert_day(res(text), iso)


def test_day_of_month_already_passed_is_ambiguous() -> None:
    assert_ambiguous(res("ayın 15'i"), Reason.PAST_THIS_MONTH, "2026-11-15", "2026-12-15")
    assert_ambiguous(res("15'inde"), Reason.PAST_THIS_MONTH, "2026-11-15", "2026-12-15")


def test_day_that_does_not_exist_this_month() -> None:
    assert_unresolved(res("ayın 31'i"), Reason.INVALID_DATE)


# --- explicit dates and ranges ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("28 kasım", "2026-11-28"),
        ("28 Kasım'da", "2026-11-28"),
        ("28 KASIM", "2026-11-28"),
        ("28 kasımda", "2026-11-28"),
        ("kasımın 28'i", "2026-11-28"),
        ("5 ocak", "2027-01-05"),  # nearest: next January
        ("5 Ocak'ta", "2027-01-05"),
        ("2 aralığa", "2026-12-02"),  # aralık -> aralığa (k softens to ğ)
        ("28 ekim", "2026-10-28"),  # nearest: 3 weeks ago, not next October
        ("28 kasım 2027", "2027-11-28"),
        ("28.11", "2026-11-28"),
        ("28/11/2026", "2026-11-28"),
        ("28.11.26", "2026-11-28"),
        ("2026-11-28", "2026-11-28"),
    ],
)
def test_explicit_dates(text: str, iso: str) -> None:
    assert_day(res(text), iso)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("28-29 kasım", "2026-11-28", "2026-11-29"),
        ("28 - 29 Kasım'da", "2026-11-28", "2026-11-29"),
        (f"28{EN_DASH}29 KASIM", "2026-11-28", "2026-11-29"),
        ("28 ile 29 kasım arası", "2026-11-28", "2026-11-29"),
        ("30 kasım - 2 aralık", "2026-11-30", "2026-12-02"),
        ("28 kasımdan 2 aralığa kadar", "2026-11-28", "2026-12-02"),
        ("30 aralık - 2 ocak", "2026-12-30", "2027-01-02"),
        ("30 aralık - 2 ocak 2027", "2026-12-30", "2027-01-02"),
    ],
)
def test_date_ranges(text: str, start: str, end: str) -> None:
    assert_range(res(text), start, end)


def test_day_month_half_a_year_away_is_ambiguous() -> None:
    assert_ambiguous(res("19 mayıs"), Reason.YEAR, "2026-05-19", "2027-05-19")


@pytest.mark.parametrize(
    "text", ["31 kasım", "30 şubat", "29 şubat", "2026-02-30", "13.13", "29-28 kasım"]
)
def test_impossible_dates(text: str) -> None:
    assert_unresolved(res(text), Reason.INVALID_DATE)


def test_leap_day_resolves_to_the_nearest_leap_year() -> None:
    assert_day(res("29 şubat", today=d("2027-12-01")), "2028-02-29")


# --- offsets ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("3 hafta sonra", "2026-12-10", "2026-12-10"),
        ("üç hafta sonra", "2026-12-10", "2026-12-10"),
        ("ÜÇ GÜN SONRA", "2026-11-22", "2026-11-22"),
        ("2 gün sonra", "2026-11-21", "2026-11-21"),
        ("on gün sonra", "2026-11-29", "2026-11-29"),
        ("bir hafta sonra", "2026-11-26", "2026-11-26"),
        ("2 ay sonra", "2027-01-19", "2027-01-19"),
        ("bir yıl sonra", "2027-11-19", "2027-11-19"),
        ("1 sene sonra", "2027-11-19", "2027-11-19"),
        ("2 gün önce", "2026-11-17", "2026-11-17"),
        ("iki hafta önce", "2026-11-05", "2026-11-05"),
        ("1 hafta içinde", "2026-11-19", "2026-11-26"),
        ("3 gün içerisinde", "2026-11-19", "2026-11-22"),
    ],
)
def test_offsets(text: str, start: str, end: str) -> None:
    assert_range(res(text), start, end)


def test_month_offset_clamps_to_month_end() -> None:
    assert_day(res("1 ay sonra", today=d("2027-01-31")), "2027-02-28")


# --- "kadar" (until) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("cumaya kadar", "2026-11-19", "2026-11-20"),
        ("Salı'ya kadar", "2026-11-19", "2026-11-24"),
        ("haftaya salıya kadar", "2026-11-19", "2026-11-24"),
        ("ayın 28'ine kadar", "2026-11-19", "2026-11-28"),
        ("dönem sonuna kadar", "2026-11-19", "2027-01-08"),
    ],
)
def test_until(text: str, start: str, end: str) -> None:
    assert_range(res(text), start, end)


def test_until_a_past_day_is_unresolved() -> None:
    assert_unresolved(res("düne kadar"), Reason.UNTIL_PAST)


def test_until_an_ambiguous_day_stays_ambiguous() -> None:
    result = res("perşembeye kadar")

    assert result.status is Status.AMBIGUOUS
    assert [(c.start.isoformat(), c.end.isoformat()) for c in result.candidates] == [
        ("2026-11-19", "2026-11-19"),
        ("2026-11-19", "2026-11-26"),
    ]


# --- parts of day and clock times ------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "iso", "part"),
    [
        ("bu akşam", "2026-11-19", PartOfDay.EVENING),
        ("BU AKŞAM", "2026-11-19", PartOfDay.EVENING),
        ("bu sabah", "2026-11-19", PartOfDay.MORNING),
        ("bu gece", "2026-11-19", PartOfDay.NIGHT),
        ("bu öğlen", "2026-11-19", PartOfDay.NOON),
        ("akşam", "2026-11-19", PartOfDay.EVENING),
        ("yarın sabah", "2026-11-20", PartOfDay.MORNING),
        ("Yarın Sabah", "2026-11-20", PartOfDay.MORNING),
        ("yarın sabahleyin", "2026-11-20", PartOfDay.MORNING),
        ("yarın akşam", "2026-11-20", PartOfDay.EVENING),
        ("cuma akşamı", "2026-11-20", PartOfDay.EVENING),
        ("haftaya salı öğleden sonra", "2026-11-24", PartOfDay.AFTERNOON),
        ("öbür gün gece", "2026-11-21", PartOfDay.NIGHT),
    ],
)
def test_part_of_day(text: str, iso: str, part: PartOfDay) -> None:
    result = res(text)

    assert_day(result, iso)
    assert result.part_of_day is part


def test_bare_morning_is_ambiguous() -> None:
    result = res("sabah")

    assert_ambiguous(result, Reason.MORNING_TODAY_OR_TOMORROW, "2026-11-19", "2026-11-20")
    assert result.part_of_day is PartOfDay.MORNING


@pytest.mark.parametrize(
    ("text", "iso", "clock"),
    [
        ("14:00", "2026-11-19", "14:00"),
        ("yarın 14:00", "2026-11-20", "14:00"),
        ("yarın saat 09:30", "2026-11-20", "09:30"),
        ("cuma 9:15'te", "2026-11-20", "09:15"),
        ("akşam 8:30", "2026-11-19", "20:30"),
        ("cuma akşam 7:00", "2026-11-20", "19:00"),
        ("öğleden sonra 3:00", "2026-11-19", "15:00"),
        ("gece 1:00", "2026-11-19", "01:00"),
        ("gece 11:00", "2026-11-19", "23:00"),
        ("akşam 20:30", "2026-11-19", "20:30"),
    ],
)
def test_clock_times(text: str, iso: str, clock: str) -> None:
    result = res(text)

    assert_day(result, iso)
    assert result.time == dt.time.fromisoformat(clock)


# --- vague, approximate and unrecognized: never guess ----------------------------------


@pytest.mark.parametrize(
    "text", ["yakında", "Yakında", "bir ara", "daha sonra", "ileride", "birkaç gün sonra"]
)
def test_vague_phrases(text: str) -> None:
    result = res(text)

    assert result.status is Status.AMBIGUOUS
    assert result.reason is Reason.VAGUE
    assert result.candidates == ()


def test_approximate_phrases_keep_the_candidate_but_are_not_resolved() -> None:
    assert_ambiguous(res("cuma gibi"), Reason.APPROXIMATE, "2026-11-20")
    assert_ambiguous(res("28 kasım civarı"), Reason.APPROXIMATE, "2026-11-28")


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", Reason.EMPTY),
        ("   ", Reason.EMPTY),
        ("asdf", Reason.UNRECOGNIZED),
        ("bu", Reason.UNRECOGNIZED),
        ("kadar", Reason.UNRECOGNIZED),
        ("hafta", Reason.UNRECOGNIZED),
        ("28 29 kasım", Reason.UNRECOGNIZED),
        ("3 buçukta", Reason.UNRECOGNIZED),
        ("yarın 25'te", Reason.INVALID_TIME),
        ("cumartesi 13-11", Reason.INVALID_TIME),
        ("yarın 14'te 15'te", Reason.INVALID_TIME),
        ("yarın veya cuma", Reason.UNRECOGNIZED),
        ("ertesi gün", Reason.UNRECOGNIZED),  # relative to what?
        ("25:00", Reason.INVALID_TIME),
        ("14:75", Reason.INVALID_TIME),
        ("14:00 15:00", Reason.INVALID_TIME),
        ("sabah 15:00", Reason.CONFLICTING_PARTS),
        ("yarın sabah akşam", Reason.CONFLICTING_PARTS),
    ],
)
def test_unresolved(text: str, reason: Reason) -> None:
    assert_unresolved(res(text), reason)


# --- year-end crossing -----------------------------------------------------------------

NYE_EVE = d("2026-12-30")  # Wednesday


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("yarın", "2026-12-31", "2026-12-31"),
        ("öbür gün", "2027-01-01", "2027-01-01"),
        ("3 gün sonra", "2027-01-02", "2027-01-02"),
        ("cuma", "2027-01-01", "2027-01-01"),
        ("5 ocak", "2027-01-05", "2027-01-05"),
        ("30 aralık - 2 ocak", "2026-12-30", "2027-01-02"),
        ("31 aralık - 1 ocak 2027", "2026-12-31", "2027-01-01"),
        ("haftaya pazartesi", "2027-01-04", "2027-01-04"),
        ("bu hafta", "2026-12-28", "2027-01-03"),
        ("bu hafta sonu", "2027-01-02", "2027-01-03"),
        ("önümüzdeki hafta", "2027-01-04", "2027-01-10"),
        ("gelecek ay", "2027-01-01", "2027-01-31"),
        ("3 hafta sonra", "2027-01-20", "2027-01-20"),
        ("1 ay sonra", "2027-01-30", "2027-01-30"),
    ],
)
def test_year_end_crossing(text: str, start: str, end: str) -> None:
    assert_range(res(text, today=NYE_EVE), start, end)


def test_day_of_month_after_it_passed_crosses_into_next_year() -> None:
    assert_ambiguous(
        res("ayın 2'si", today=NYE_EVE), Reason.PAST_THIS_MONTH, "2026-12-02", "2027-01-02"
    )


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("28 aralık", "2026-12-28", "2026-12-28"),  # nearest is last week, not next December
        ("dün", "2027-01-02", "2027-01-02"),
        ("geçen hafta", "2026-12-21", "2026-12-27"),
        ("geçen ay", "2026-12-01", "2026-12-31"),
        ("geçen cuma", "2027-01-01", "2027-01-01"),
    ],
)
def test_looking_back_across_new_year(text: str, start: str, end: str) -> None:
    assert_range(res(text, today=d("2027-01-03")), start, end)


# --- week starts on Monday: Sunday / Monday edge -----------------------------------------

SUN = d("2026-11-22")
MON = d("2026-11-23")


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("bugün", "2026-11-22", "2026-11-22"),
        ("bu hafta", "2026-11-16", "2026-11-22"),  # Sunday still belongs to this week
        ("haftaya", "2026-11-23", "2026-11-29"),
        ("önümüzdeki hafta", "2026-11-23", "2026-11-29"),
        ("pazartesi", "2026-11-23", "2026-11-23"),
        ("haftaya pazartesi", "2026-11-23", "2026-11-23"),
        ("hafta sonu", "2026-11-21", "2026-11-22"),
        ("gelecek hafta sonu", "2026-11-28", "2026-11-29"),
        ("gelecek salı", "2026-11-24", "2026-11-24"),
    ],
)
def test_on_a_sunday(text: str, start: str, end: str) -> None:
    assert_range(res(text, today=SUN), start, end)


def test_on_a_sunday_ambiguities() -> None:
    assert_ambiguous(
        res("bu pazartesi", today=SUN), Reason.PAST_THIS_WEEK, "2026-11-16", "2026-11-23"
    )
    assert_ambiguous(res("pazar", today=SUN), Reason.SAME_WEEKDAY, "2026-11-22", "2026-11-29")


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("bu hafta", "2026-11-23", "2026-11-29"),
        ("geçen hafta", "2026-11-16", "2026-11-22"),
        ("dün", "2026-11-22", "2026-11-22"),
        ("geçen pazar", "2026-11-22", "2026-11-22"),
        ("geçen hafta pazar", "2026-11-22", "2026-11-22"),
        ("pazar", "2026-11-29", "2026-11-29"),
        ("bu pazartesi", "2026-11-23", "2026-11-23"),
        ("haftaya pazartesi", "2026-11-30", "2026-11-30"),
    ],
)
def test_on_a_monday(text: str, start: str, end: str) -> None:
    assert_range(res(text, today=MON), start, end)


def test_on_a_monday_gelecek_is_ambiguous() -> None:
    assert_ambiguous(
        res("gelecek cuma", today=MON), Reason.THIS_OR_NEXT_WEEK, "2026-11-27", "2026-12-04"
    )


# --- serialization ---------------------------------------------------------------------


def test_to_dict_for_tool_output() -> None:
    assert res("yarın akşam 8:30").to_dict() == {
        "text": "yarın akşam 8:30",
        "status": "resolved",
        "start": "2026-11-20",
        "end": "2026-11-20",
        "part_of_day": "evening",
        "time": "20:30",
    }
    assert res("gelecek cuma").to_dict() == {
        "text": "gelecek cuma",
        "status": "ambiguous",
        "candidates": [
            {"start": "2026-11-20", "end": "2026-11-20"},
            {"start": "2026-11-27", "end": "2026-11-27"},
        ],
        "reason": "this_or_next_week",
    }
    assert res("dönem sonu", today=THU).to_dict()["status"] == "resolved"
    assert resolve("asdf", THU).to_dict() == {
        "text": "asdf",
        "status": "unresolved",
        "reason": "unrecognized",
    }


# --- calendar context for the model -----------------------------------------------------


def test_calendar_context_covers_today_plus_14_days() -> None:
    calendar = build_calendar_context(THU)

    assert len(calendar) == 15
    assert calendar[0] == CalendarDay(THU, "Perşembe", "bugün", "bu hafta")
    assert calendar[1] == CalendarDay(d("2026-11-20"), "Cuma", "yarın", "bu hafta")
    assert calendar[2] == CalendarDay(d("2026-11-21"), "Cumartesi", "öbür gün", "bu hafta")
    assert calendar[3].relative is None
    assert calendar[4] == CalendarDay(d("2026-11-23"), "Pazartesi", None, "gelecek hafta")
    assert calendar[11] == CalendarDay(d("2026-11-30"), "Pazartesi", None, "2 hafta sonra")
    assert calendar[-1].date == d("2026-12-03")


def test_calendar_context_across_new_year() -> None:
    calendar = build_calendar_context(NYE_EVE, days=7)

    assert [(c.date.isoformat(), c.weekday_name) for c in calendar[1:4]] == [
        ("2026-12-31", "Perşembe"),
        ("2027-01-01", "Cuma"),
        ("2027-01-02", "Cumartesi"),
    ]
    assert calendar[5].week == "gelecek hafta"  # Monday 4 Jan 2027


def test_calendar_context_on_sunday_next_day_is_next_week() -> None:
    calendar = build_calendar_context(SUN, days=1)

    assert [c.week for c in calendar] == ["bu hafta", "gelecek hafta"]


def test_format_calendar_context() -> None:
    text = format_calendar_context(build_calendar_context(THU))
    lines = text.splitlines()

    assert lines[:3] == ["[bu hafta]", "2026-11-19 Per bugün", "2026-11-20 Cum yarın"]
    assert lines[3] == "2026-11-21 Cmt öbür gün"
    assert lines[5:7] == ["[gelecek hafta]", "2026-11-23 Pzt"]
    assert sum(1 for line in lines if not line.startswith("[")) == 15


# --- direction: future / past ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "direction", "start", "end"),
    [
        ("bu salı", "future", "2026-11-24", "2026-11-24"),
        ("bu salı", "past", "2026-11-17", "2026-11-17"),
        ("ayın 15'i", "future", "2026-12-15", "2026-12-15"),
        ("ayın 15'i", "past", "2026-11-15", "2026-11-15"),
        ("19 mayıs", "future", "2027-05-19", "2027-05-19"),
        ("19 mayıs", "past", "2026-05-19", "2026-05-19"),
        ("mayısta", "future", "2027-05-01", "2027-05-31"),
        ("28 ekim", "future", "2027-10-28", "2027-10-28"),  # "any" picks the nearest: 2026
        ("5 ocak", "past", "2026-01-05", "2026-01-05"),
        ("cuma", "past", "2026-11-13", "2026-11-13"),  # "cuma gitmedim" -> last Friday
        ("cuma", "future", "2026-11-20", "2026-11-20"),
        ("salıya", "past", "2026-11-17", "2026-11-17"),
        ("sabah", "past", "2026-11-19", "2026-11-19"),
        ("bu hafta", "past", "2026-11-16", "2026-11-22"),  # contains today: fine both ways
        ("bu hafta", "future", "2026-11-16", "2026-11-22"),
        ("dün", "past", "2026-11-18", "2026-11-18"),
        ("yarın", "future", "2026-11-20", "2026-11-20"),
        ("bugün", "past", "2026-11-19", "2026-11-19"),
        ("bugün", "future", "2026-11-19", "2026-11-19"),
    ],
)
def test_direction_drops_readings(text: str, direction: str, start: str, end: str) -> None:
    assert_range(resolve(text, THU, direction=direction), start, end)


@pytest.mark.parametrize(
    ("text", "direction", "reason", "candidates"),
    [
        ("perşembe", "future", Reason.SAME_WEEKDAY, ("2026-11-19", "2026-11-26")),
        ("perşembe", "past", Reason.SAME_WEEKDAY, ("2026-11-12", "2026-11-19")),
        ("gelecek cuma", "future", Reason.THIS_OR_NEXT_WEEK, ("2026-11-20", "2026-11-27")),
        ("sabah", "future", Reason.MORNING_TODAY_OR_TOMORROW, ("2026-11-19", "2026-11-20")),
    ],
)
def test_direction_keeps_real_ambiguity(
    text: str, direction: str, reason: Reason, candidates: tuple[str, ...]
) -> None:
    assert_ambiguous(resolve(text, THU, direction=direction), reason, *candidates)


@pytest.mark.parametrize(
    ("text", "direction"),
    [("dün", "future"), ("geçen cuma", "future"), ("yarın", "past"), ("haftaya salı", "past")],
)
def test_direction_conflict(text: str, direction: str) -> None:
    assert_unresolved(resolve(text, THU, direction=direction), Reason.DIRECTION_CONFLICT)


def test_direction_default_is_any() -> None:
    assert res("bu salı").status is Status.AMBIGUOUS
    assert Direction("any") is Direction.ANY


def test_vague_stays_vague_in_any_direction() -> None:
    assert resolve("yakında", THU, direction="future").reason is Reason.VAGUE


# --- clock times and time ranges (Turkish: locative = time, possessive = date) --------


@pytest.mark.parametrize(
    ("text", "iso", "start", "end"),
    [
        ("yarın 14'te", "2026-11-20", "14:00", None),
        ("YARIN 14'TE", "2026-11-20", "14:00", None),
        ("cuma 14:00", "2026-11-20", "14:00", None),
        ("Cuma 14:00'te", "2026-11-20", "14:00", None),
        ("cumartesi 11-13", "2026-11-21", "11:00", "13:00"),
        ("Cumartesi 11-13 arası", "2026-11-21", "11:00", "13:00"),
        ("cumartesi 11:00-13:30", "2026-11-21", "11:00", "13:30"),
        ("cumartesi saat 11-13", "2026-11-21", "11:00", "13:00"),
        ("cumartesi 9:00-11:00", "2026-11-21", "09:00", "11:00"),  # colon = literal 24h
        ("akşam 7-9", "2026-11-19", "19:00", "21:00"),
        ("yarın sabah 9'da", "2026-11-20", "09:00", None),
        ("yarın akşam 8'de", "2026-11-20", "20:00", None),
        ("yarın saat 14", "2026-11-20", "14:00", None),
        ("yarın 12'de", "2026-11-20", "12:00", None),
        ("14'te", "2026-11-19", "14:00", None),
        ("haftaya salı 16-18", "2026-11-24", "16:00", "18:00"),
    ],
)
def test_clock_times_and_ranges(text: str, iso: str, start: str, end: str | None) -> None:
    result = res(text)

    assert_day(result, iso)
    assert result.time == dt.time.fromisoformat(start)
    assert result.end_time == (dt.time.fromisoformat(end) if end else None)


def test_date_range_is_not_mistaken_for_a_time_range() -> None:
    result = res("28-29 kasım")

    assert_range(result, "2026-11-28", "2026-11-29")
    assert result.time is None
    assert result.end_time is None


@pytest.mark.parametrize(
    ("text", "iso", "start", "end"),
    [
        ("yarın 9'da", "2026-11-20", "09:00", None),  # 8-11 -> morning
        ("yarın 11'de", "2026-11-20", "11:00", None),
        ("saat 3'te", "2026-11-19", "15:00", None),  # 1-7 -> afternoon
        ("cuma 7'de", "2026-11-20", "19:00", None),
        ("cuma 9-11", "2026-11-20", "09:00", "11:00"),
        ("cuma 2-4", "2026-11-20", "14:00", "16:00"),
        ("cuma 11-1", "2026-11-20", "11:00", "13:00"),  # "11-1" said for 11:00-13:00
        ("yarın sabah 7'de", "2026-11-20", "07:00", None),  # part of day overrides it
    ],
)
def test_bare_hours_follow_the_clock_convention(
    text: str, iso: str, start: str, end: str | None
) -> None:
    result = res(text)

    assert_day(result, iso)
    assert result.time == dt.time.fromisoformat(start)
    assert result.end_time == (dt.time.fromisoformat(end) if end else None)


@pytest.mark.parametrize(
    ("text", "iso", "slots"),
    [
        ("cuma 7-9", "2026-11-20", ["07:00-09:00", "19:00-21:00"]),  # 19-09 is no range
        ("cuma 6-8", "2026-11-20", ["06:00-08:00", "18:00-20:00"]),
    ],
)
def test_only_real_ambiguity_is_asked(text: str, iso: str, slots: list[str]) -> None:
    result = res(text)

    assert result.status is Status.AMBIGUOUS
    assert result.reason is Reason.AM_OR_PM
    assert result.span == DateSpan.day(d(iso))  # the date itself is known
    assert result.time is None
    assert [str(slot) for slot in result.time_candidates] == slots


def test_clock_convention_is_configurable() -> None:
    clock = ClockConvention(morning=(9, 11), afternoon=(1, 6))

    assert resolve("yarın 8'de", THU, clock=clock).reason is Reason.AM_OR_PM  # uncovered
    assert resolve("yarın 9'da", THU, clock=clock).time == dt.time(9)
    assert resolve("yarın 7'de", THU, clock=clock).time_candidates == (
        TimeSlot(dt.time(7)),
        TimeSlot(dt.time(19)),
    )


@pytest.mark.parametrize(
    ("morning", "afternoon"), [((0, 11), (1, 7)), ((8, 12), (1, 7)), ((5, 11), (1, 7))]
)
def test_invalid_clock_conventions(morning: tuple[int, int], afternoon: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match=r"1-11|overlap"):
        ClockConvention(morning=morning, afternoon=afternoon)


def test_clock_convention_from_settings() -> None:
    from app.config import Settings

    settings = Settings(_env_file=None, clock_morning_hours="9-11", clock_afternoon_hours="1-6")
    assert settings.clock == ClockConvention(morning=(9, 11), afternoon=(1, 6))
    # overlapping ranges don't stop the app (O1): the defaults are used and it is reported
    overlapping = Settings(_env_file=None, clock_morning_hours="5-11", clock_afternoon_hours="1-7")
    assert overlapping.clock == ClockConvention(morning=(8, 11), afternoon=(1, 7))


def test_time_with_ambiguous_date_keeps_both_ambiguities_visible() -> None:
    result = res("perşembe 14:00")

    assert result.reason is Reason.SAME_WEEKDAY
    assert result.time == dt.time(14, 0)


def test_to_dict_with_time_range_and_time_candidates() -> None:
    assert res("cumartesi 11-13").to_dict() == {
        "text": "cumartesi 11-13",
        "status": "resolved",
        "start": "2026-11-21",
        "end": "2026-11-21",
        "time": "11:00",
        "end_time": "13:00",
    }
    assert res("cuma 7-9").to_dict()["time_candidates"] == ["07:00-09:00", "19:00-21:00"]


# --- dates written with their weekday (notices, posters, messages) ----------------------


@pytest.mark.parametrize(
    "text",
    [
        "27 Kasım Cuma",
        "Cuma 27 Kasım",
        "cuma, 27 kasım",
        "27 kasım cuması",
        "cuma 27 kasımda",
        "27 Kasım 2026 Cuma",
        "27.11",
        "27/11",
        "27.11 Cuma",
        "cuma 27/11",
        "Cuma, 27.11.2026",
    ],
)
def test_day_month_with_weekday(text: str) -> None:
    assert_day(res(text), "2026-11-27")


def test_day_month_weekday_and_time() -> None:
    result = res("27 Kasım Cuma 14:00")

    assert_day(result, "2026-11-27")
    assert result.time == dt.time(14)


@pytest.mark.parametrize(
    ("text", "candidates"),
    [
        ("28 Kasım Cuma", ("2026-11-27", "2026-11-28")),  # 28 Kasım is a Saturday
        ("Perşembe 27 Kasım", ("2026-11-26", "2026-11-27")),
        ("27.11 Pazar", ("2026-11-27", "2026-11-29")),
    ],
)
def test_weekday_that_does_not_fit_is_asked_back(text: str, candidates: tuple[str, str]) -> None:
    assert_ambiguous(res(text), Reason.WEEKDAY_MISMATCH, *candidates)


def test_weekday_picks_the_year_when_it_is_open() -> None:
    # "19 mayıs" alone is half a year away either way (Reason.YEAR); the weekday decides
    assert_day(res("19 Mayıs Salı"), "2026-05-19")
    assert_day(res("19 Mayıs Çarşamba"), "2027-05-19")


def test_weekday_does_not_pull_a_date_into_another_year() -> None:
    # 28 Kasım 2025 was a Friday, but "28 Kasım" next week is the date meant
    result = resolve("28 Kasım Cuma", dt.date(2026, 11, 23), direction="future")

    assert_ambiguous(result, Reason.WEEKDAY_MISMATCH, "2026-11-27", "2026-11-28")


def test_impossible_date_with_weekday() -> None:
    assert_unresolved(res("31 Kasım Pazartesi"), Reason.INVALID_DATE)


@pytest.mark.parametrize(
    ("text", "day", "hhmm"),
    [
        ("8 ocakta 13.30da", "2027-01-08", "13:30"),
        ("yarın 9.45te", "2026-11-24", "09:45"),
        ("cuma saat 10.00", "2026-11-27", "10:00"),
    ],
)
def test_a_dot_between_hour_and_minutes(text: str, day: str, hhmm: str) -> None:
    """Live: "ee211 finali 8 ocakta 13.30da" was unresolved and Scholar asked again."""
    result = res(text, dt.date(2026, 11, 23))

    assert result.status is Status.RESOLVED
    assert result.span is not None
    assert result.span.start.isoformat() == day
    assert result.time is not None
    assert result.time.strftime("%H:%M") == hhmm


def test_a_dotted_date_is_not_a_time() -> None:
    result = res("8.12'de")

    assert result.time is None
