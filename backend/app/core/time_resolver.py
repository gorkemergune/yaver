"""Turkish relative date expressions -> concrete dates, resolved in code (never by the model).

`resolve("haftaya salı akşam", today)` returns a `Resolution`:

- RESOLVED   -> `span` (single day or inclusive range), optional `part_of_day` / `time`
- AMBIGUOUS  -> several readings in `candidates` (or none, for vague words like "yakında");
                the agent must ask the user instead of picking one
- UNRESOLVED -> not understood or not computable (`reason` says why)

Input is a short date phrase extracted by the agent ("yarın sabah", "28-29 kasım"), not a
whole sentence. Unknown words make the phrase UNRESOLVED; nothing is guessed.

Conventions:
- Weeks run Monday-Sunday.
- "cuma" (bare weekday) = the next Friday; said on a Friday it is AMBIGUOUS (today / +7).
- "bu cuma" = Friday of this week; if already past -> AMBIGUOUS (that day / next week's).
- "önümüzdeki cuma" = next Friday after today.
- "gelecek cuma" = AMBIGUOUS while this week's Friday is still ahead (this / next week),
  otherwise next week's Friday. "haftaya cuma" / "gelecek hafta cuma" = next week's Friday.
- A day-month without a year ("5 ocak") takes the nearest occurrence; AMBIGUOUS when the
  past and future occurrences are about equally far (~6 months away).
- "ayın 15'i" after the 15th has passed -> AMBIGUOUS (this month's / next month's).
- Clock times are only accepted as HH:MM; "14'te" is UNRESOLVED (day 14 or 14:00?).
"""

import datetime as dt
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# --------------------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------------------


class Status(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class Reason(StrEnum):
    EMPTY = "empty"
    UNRECOGNIZED = "unrecognized"
    INVALID_DATE = "invalid_date"
    INVALID_TIME = "invalid_time"
    CONFLICTING_PARTS = "conflicting_parts"
    TERM_UNKNOWN = "term_unknown"
    UNTIL_PAST = "until_past"
    VAGUE = "vague"
    APPROXIMATE = "approximate"
    SAME_WEEKDAY = "same_weekday"  # "cuma" said on a Friday
    PAST_THIS_WEEK = "past_this_week"  # "bu salı" on Thursday
    THIS_OR_NEXT_WEEK = "this_or_next_week"  # "gelecek cuma" on Monday
    PAST_THIS_MONTH = "past_this_month"  # "ayın 15'i" on the 19th
    YEAR = "year"  # "19 mayıs" in November
    MORNING_TODAY_OR_TOMORROW = "morning_today_or_tomorrow"  # bare "sabah"


class PartOfDay(StrEnum):
    MORNING = "morning"
    NOON = "noon"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


# Approximate local hours for each part of day (start inclusive, end exclusive).
PART_OF_DAY_HOURS: dict[PartOfDay, tuple[dt.time, dt.time]] = {
    PartOfDay.MORNING: (dt.time(6), dt.time(12)),
    PartOfDay.NOON: (dt.time(12), dt.time(14)),
    PartOfDay.AFTERNOON: (dt.time(12), dt.time(18)),
    PartOfDay.EVENING: (dt.time(18), dt.time(22)),
    PartOfDay.NIGHT: (dt.time(22), dt.time(23, 59)),
}


@dataclass(frozen=True, slots=True)
class DateSpan:
    """Inclusive date range; start == end for a single day."""

    start: dt.date
    end: dt.date

    @classmethod
    def day(cls, value: dt.date) -> "DateSpan":
        return cls(value, value)

    @property
    def is_single_day(self) -> bool:
        return self.start == self.end

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True, slots=True)
class Resolution:
    text: str
    status: Status
    span: DateSpan | None = None
    part_of_day: PartOfDay | None = None
    time: dt.time | None = None
    candidates: tuple[DateSpan, ...] = ()
    reason: Reason | None = None

    @property
    def start(self) -> dt.date | None:
        return self.span.start if self.span else None

    @property
    def end(self) -> dt.date | None:
        return self.span.end if self.span else None

    def to_dict(self) -> dict[str, Any]:
        """Compact JSON-friendly form for tool outputs."""
        data: dict[str, Any] = {"text": self.text, "status": self.status.value}
        if self.span:
            data.update(self.span.to_dict())
        if self.part_of_day:
            data["part_of_day"] = self.part_of_day.value
        if self.time:
            data["time"] = self.time.strftime("%H:%M")
        if self.candidates:
            data["candidates"] = [c.to_dict() for c in self.candidates]
        if self.reason:
            data["reason"] = self.reason.value
        return data


@dataclass(frozen=True, slots=True)
class CalendarDay:
    date: dt.date
    weekday_name: str
    relative: str | None  # "bugün" / "yarın" / "öbür gün"
    week: str  # "bu hafta" / "gelecek hafta" / "2 hafta sonra"


# --------------------------------------------------------------------------------------
# Turkish vocabulary (folded to ASCII: ç->c, ğ->g, ı->i, ö->o, ş->s, ü->u)
# --------------------------------------------------------------------------------------

WEEKDAY_NAMES_TR = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
MONTH_NAMES_TR = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)  # fmt: skip

_WEEKDAYS = {
    "pazartesi": 0,
    "sali": 1,
    "carsamba": 2,
    "persembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
}
# Stems incl. consonant softening before a vowel suffix (ocak -> ocağa, aralık -> aralığın).
_MONTHS = {
    "ocak": 1, "ocag": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
    "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12, "aralig": 12,
}  # fmt: skip
_NUMBER_WORDS = {
    "bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5,
    "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
}  # fmt: skip


def _alternation(words: dict[str, int]) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


# Case suffixes after a name: dative (cumaya), accusative (cumayı), locative (cumada),
# ablative (cumadan), genitive (cumanın), -ki (cumaki), possessive (cuması).
_SFX = r"(?:y?[aeiu]|n?[iu]n|[dt][ae]n?|ki|s[iu]|n[ae]|n[dt][ae]n?)?"
_WD = rf"(?P<wd>{_alternation(_WEEKDAYS)}){_SFX}(?:\s+gun\w*)?"
_MON_BARE = rf"(?P<mon>{_alternation(_MONTHS)}){_SFX}"
_MON = rf"{_MON_BARE}(?:\s+ay\w*)?"  # "kasım ayında"
_NUM = rf"(?:\d{{1,3}}|{_alternation(_NUMBER_WORDS)})"
# Possessive suffix on a day number: 28'i, 2'si, 3'ü, 28'inde, 15'ine ... (not 14'te = time)
_DAY_POSS = r"(?:s?[iu](?:n[dt][ae]n?|n[ae])?)"

_PARTS: tuple[tuple[PartOfDay, str], ...] = (
    (PartOfDay.AFTERNOON, r"ogleden\s+sonra(?:ki|ya|s[iu]na)?|ikindi\w*"),
    (PartOfDay.NOON, r"ogle\s+aras[i]\w*|oglen(?:de|e|i)?|ogle(?:ye|de|nde|ne)?"),
    (PartOfDay.MORNING, r"sabah(?:i|a|leyin|tan|ki|in|lari)?"),
    (PartOfDay.EVENING, r"aksam(?:i|a|leyin|ustu|ki|da|in|lari)?"),
    (PartOfDay.NIGHT, r"gece\s+yarisi\w*|gece(?:si|ye|leyin|ki|de)?"),
)
_VAGUE = frozenset(
    {
        "yakinda", "ileride", "ilerde", "bir ara", "biraz sonra", "daha sonra", "sonra",
        "bir gun", "birgun", "en kisa zamanda", "musait olunca", "zamani gelince",
    }
)  # fmt: skip
_APPROX = re.compile(r"\s+(?:gibi|civari\w*|sular\w*|falan|filan|veya\s+sonrasi)$")
_UNTIL = re.compile(r"(?:^|\s+)(?:kadar|dek|degin)$")
_TIME = re.compile(r"(?<![\d.:/])(?:saat\s+)?(?P<h>\d{1,2}):(?P<mi>\d{2})[a-z]*(?![\d:])")
_SAME_WEEK_DAYS = dt.timedelta(days=7)
# Past/future candidates closer than this to each other's distance are ambiguous.
_NEAREST_MARGIN_DAYS = 31


# --------------------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------------------

# Built from code points so the source stays free of look-alike characters.
_APOSTROPHES = re.compile(
    "[" + re.escape("'`" + "".join(map(chr, (0xB4, 0x2BC, 0x2018, 0x2019)))) + "]"
)
_DASHES = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")  # en / em dash


def normalize(text: str) -> str:
    """Turkish-aware lowercase, folded to ASCII, apostrophes dropped, spaces collapsed."""
    # No Turkish-specific casing needed: everything is folded to ASCII anyway, so
    # "İ".lower() -> "i" + combining dot -> "i", and "I" / "ı" both end up as "i".
    decomposed = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).replace("ı", "i")
    folded = _APOSTROPHES.sub("", folded)  # Cuma'ya -> cumaya
    folded = _DASHES.sub("-", folded)
    folded = re.sub(r"[,;!?()\"]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip(" .")


# --------------------------------------------------------------------------------------
# Date arithmetic
# --------------------------------------------------------------------------------------


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def add_months(day: dt.date, months: int) -> dt.date:
    """Calendar month arithmetic, clamping to the month's last day (31 Jan + 1 -> 28 Feb)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return dt.date(year, month, min(day.day, _days_in_month(year, month)))


def _days_in_month(year: int, month: int) -> int:
    first_of_next = dt.date(year + month // 12, month % 12 + 1, 1)
    return (first_of_next - dt.timedelta(days=1)).day


def _safe_date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _month_span(year: int, month: int) -> DateSpan:
    return DateSpan(dt.date(year, month, 1), dt.date(year, month, _days_in_month(year, month)))


# --------------------------------------------------------------------------------------
# Rule outcomes
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Ambiguous:
    reason: Reason
    candidates: tuple[DateSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class _Unresolved:
    reason: Reason


_Outcome = DateSpan | _Ambiguous | _Unresolved


def _day(value: dt.date) -> DateSpan:
    return DateSpan.day(value)


def _ambiguous(reason: Reason, *days: dt.date | DateSpan) -> _Ambiguous:
    spans = tuple(d if isinstance(d, DateSpan) else DateSpan.day(d) for d in days)
    return _Ambiguous(reason, spans)


def _distance(span: DateSpan, today: dt.date) -> int:
    if span.start <= today <= span.end:
        return 0
    return min(abs((span.start - today).days), abs((span.end - today).days))


def _nearest(candidates: list[DateSpan], today: dt.date) -> _Outcome:
    """Pick the occurrence closest to today; ambiguous if two are about equally close."""
    if not candidates:
        return _Unresolved(Reason.INVALID_DATE)
    ranked = sorted(candidates, key=lambda span: _distance(span, today))
    if (
        len(ranked) > 1
        and _distance(ranked[1], today) - _distance(ranked[0], today) < _NEAREST_MARGIN_DAYS
    ):
        return _Ambiguous(Reason.YEAR, tuple(sorted(ranked[:2], key=lambda s: s.start)))
    return ranked[0]


@dataclass(frozen=True, slots=True)
class _Context:
    today: dt.date
    term_start: dt.date | None
    term_end: dt.date | None


# --------------------------------------------------------------------------------------
# Rules: each is a full-match regex over the normalized phrase + a handler
# --------------------------------------------------------------------------------------

_Handler = Callable[[re.Match[str], _Context], _Outcome]
_RULES: list[tuple[re.Pattern[str], _Handler]] = []


def _rule(pattern: str) -> Callable[[_Handler], _Handler]:
    def register(handler: _Handler) -> _Handler:
        _RULES.append((re.compile(pattern), handler))
        return handler

    return register


def _number(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def _weekday(match: re.Match[str]) -> int:
    return _WEEKDAYS[match["wd"]]


# --- single relative days -------------------------------------------------------------


@_rule(r"bu\s*gun\w*|simdi\w*")
def _today(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.today)


@_rule(r"yarin(?:a|dan|in|ki|da)?")
def _tomorrow(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.today + dt.timedelta(days=1))


@_rule(r"obur\s*gun\w*|obir\s*gun\w*|yarindan\s+sonra(?:ki(?:\s+gun\w*)?)?")
def _day_after_tomorrow(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.today + dt.timedelta(days=2))


@_rule(r"dun(?:ku|den|e|u)?")
def _yesterday(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.today - dt.timedelta(days=1))


@_rule(r"evvelsi\s*gun\w*|dunden\s+onceki(?:\s+gun\w*)?")
def _day_before_yesterday(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.today - dt.timedelta(days=2))


@_rule(r"haftaya\s+bugun\w*|gelecek\s+hafta\s+bugun\w*")
def _a_week_from_today(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.today + _SAME_WEEK_DAYS)


# --- weekdays -------------------------------------------------------------------------


@_rule(_WD)
def _bare_weekday(match: re.Match[str], ctx: _Context) -> _Outcome:
    delta = (_weekday(match) - ctx.today.weekday()) % 7
    if delta == 0:
        return _ambiguous(Reason.SAME_WEEKDAY, ctx.today, ctx.today + _SAME_WEEK_DAYS)
    return _day(ctx.today + dt.timedelta(days=delta))


@_rule(rf"bu\s+(?:haftaki\s+|hafta\s+)?{_WD}")
def _this_weekday(match: re.Match[str], ctx: _Context) -> _Outcome:
    target = week_start(ctx.today) + dt.timedelta(days=_weekday(match))
    if target >= ctx.today:
        return _day(target)
    return _ambiguous(Reason.PAST_THIS_WEEK, target, target + _SAME_WEEK_DAYS)


@_rule(rf"(?:haftaya|(?:gelecek|onumuzdeki)\s+hafta(?:ki|ya|nin)?)\s+{_WD}")
def _next_week_weekday(match: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(week_start(ctx.today) + dt.timedelta(days=7 + _weekday(match)))


@_rule(rf"onumuzdeki\s+{_WD}")
def _upcoming_weekday(match: re.Match[str], ctx: _Context) -> _Outcome:
    delta = (_weekday(match) - ctx.today.weekday()) % 7 or 7
    return _day(ctx.today + dt.timedelta(days=delta))


@_rule(rf"gelecek\s+{_WD}")
def _gelecek_weekday(match: re.Match[str], ctx: _Context) -> _Outcome:
    this_week = week_start(ctx.today) + dt.timedelta(days=_weekday(match))
    next_week = this_week + _SAME_WEEK_DAYS
    if this_week > ctx.today:
        return _ambiguous(Reason.THIS_OR_NEXT_WEEK, this_week, next_week)
    return _day(next_week)


@_rule(rf"gecen\s+{_WD}")
def _last_weekday(match: re.Match[str], ctx: _Context) -> _Outcome:
    delta = (ctx.today.weekday() - _weekday(match)) % 7 or 7
    return _day(ctx.today - dt.timedelta(days=delta))


@_rule(rf"gecen\s+hafta(?:ki|nin)?\s+{_WD}")
def _last_week_weekday(match: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(week_start(ctx.today) - dt.timedelta(days=7 - _weekday(match)))


# --- weeks and weekends ---------------------------------------------------------------


def _week(ctx: _Context, offset: int) -> DateSpan:
    monday = week_start(ctx.today) + dt.timedelta(weeks=offset)
    return DateSpan(monday, monday + dt.timedelta(days=6))


def _weekend(ctx: _Context, offset: int) -> DateSpan:
    monday = week_start(ctx.today) + dt.timedelta(weeks=offset)
    return DateSpan(monday + dt.timedelta(days=5), monday + dt.timedelta(days=6))


def _weekdays_span(ctx: _Context, offset: int) -> DateSpan:
    monday = week_start(ctx.today) + dt.timedelta(weeks=offset)
    return DateSpan(monday, monday + dt.timedelta(days=4))


_NEXT = r"(?:gelecek|onumuzdeki|haftaya)"


@_rule(r"bu\s+hafta(?:ya|nin|da|ki|icinde|\s+icinde)?")
def _this_week(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _week(ctx, 0)


@_rule(r"(?:gelecek|onumuzdeki)\s+hafta(?:ya|nin|da|ki)?|haftaya")
def _next_week(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _week(ctx, 1)


@_rule(r"gecen\s+hafta(?:ya|nin|da|ki)?")
def _last_week(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _week(ctx, -1)


@_rule(r"(?:bu\s+)?hafta\s*sonu\w*")
def _this_weekend(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _weekend(ctx, 0)


@_rule(rf"{_NEXT}\s+hafta\s*sonu\w*")
def _next_weekend(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _weekend(ctx, 1)


@_rule(r"gecen\s+hafta\s*sonu\w*")
def _last_weekend(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _weekend(ctx, -1)


@_rule(r"(?:bu\s+)?hafta\s*ici\w*")
def _this_weekdays(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _weekdays_span(ctx, 0)


@_rule(rf"{_NEXT}\s+hafta\s*ici\w*")
def _next_weekdays(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _weekdays_span(ctx, 1)


# --- offsets: "3 hafta sonra", "iki gün önce", "1 ay içinde" --------------------------

_UNIT_DAYS = {"gun": 1, "hafta": 7}


@_rule(
    rf"(?P<n>{_NUM})\s+(?P<unit>gun|hafta|ay|yil|sene)\s+"
    r"(?P<dir>sonra\w*|once\w*|icinde|icerisinde|zarfinda)"
)
def _offset(match: re.Match[str], ctx: _Context) -> _Outcome:
    n = _number(match["n"])
    sign = -1 if match["dir"].startswith("once") else 1
    unit = match["unit"]
    if unit in _UNIT_DAYS:
        target = ctx.today + dt.timedelta(days=sign * n * _UNIT_DAYS[unit])
    else:
        target = add_months(ctx.today, sign * n * (1 if unit == "ay" else 12))
    if match["dir"].startswith(("icinde", "icerisinde", "zarfinda")):
        return DateSpan(ctx.today, target)
    return _day(target)


@_rule(r"birkac\s+(?:gun|hafta|ay|yil|sene)\w*(?:\s+\w+)?|bir\s+kac\s+\w+(?:\s+\w+)?")
def _a_few(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _Ambiguous(Reason.VAGUE)


# --- months ---------------------------------------------------------------------------


@_rule(r"bu\s+ay(?:ki|in|da|a)?")
def _this_month(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _month_span(ctx.today.year, ctx.today.month)


@_rule(r"(?:gelecek|onumuzdeki)\s+ay(?:ki|in|da|a)?")
def _next_month(_: re.Match[str], ctx: _Context) -> _Outcome:
    first = add_months(ctx.today.replace(day=1), 1)
    return _month_span(first.year, first.month)


@_rule(r"gecen\s+ay(?:ki|in|da|a)?")
def _last_month(_: re.Match[str], ctx: _Context) -> _Outcome:
    first = add_months(ctx.today.replace(day=1), -1)
    return _month_span(first.year, first.month)


@_rule(rf"{_MON}(?:\s+(?P<year>\d{{4}}))?")
def _named_month(match: re.Match[str], ctx: _Context) -> _Outcome:
    month = _MONTHS[match["mon"]]
    if match["year"]:
        return _month_span(int(match["year"]), month)
    years = (ctx.today.year - 1, ctx.today.year, ctx.today.year + 1)
    return _nearest([_month_span(year, month) for year in years], ctx.today)


# --- day of month: "ayın 28'i", "28'inde", "gelecek ayın 5'i" -------------------------


@_rule(
    r"(?:(?P<rel>bu|gelecek|onumuzdeki|gecen)\s+)?ayin\s+(?P<d>\d{1,2})[a-z]*"
    rf"|(?P<bare>\d{{1,2}}){_DAY_POSS}"
)
def _day_of_month(match: re.Match[str], ctx: _Context) -> _Outcome:
    day = int(match["d"] or match["bare"])
    rel = match["rel"]
    offset = {"gelecek": 1, "onumuzdeki": 1, "gecen": -1}.get(rel or "", 0)
    month_first = add_months(ctx.today.replace(day=1), offset)
    target = _safe_date(month_first.year, month_first.month, day)
    if target is None:  # "ayın 31'i" in November
        return _Unresolved(Reason.INVALID_DATE)
    if rel is not None or target >= ctx.today:
        return _day(target)
    # "ayın 15'i" after the 15th: this month's (past) or next month's?
    following = add_months(month_first, 1)
    later = _safe_date(following.year, following.month, day)
    return _ambiguous(Reason.PAST_THIS_MONTH, *(d for d in (target, later) if d is not None))


# --- explicit dates: "28 kasım", "5 ocak 2027", "28.11", "2026-11-28" -----------------


def _dated(day: int, month: int, year: str | None, ctx: _Context) -> _Outcome:
    if year:
        value = _safe_date(_full_year(year), month, day)
        return _day(value) if value else _Unresolved(Reason.INVALID_DATE)
    years = (ctx.today.year - 1, ctx.today.year, ctx.today.year + 1)
    candidates = [_safe_date(y, month, day) for y in years]
    return _nearest([_day(c) for c in candidates if c is not None], ctx.today)


def _full_year(year: str) -> int:
    return int(year) + 2000 if len(year) == 2 else int(year)


@_rule(rf"(?P<d>\d{{1,2}})\s*{_MON}(?:\s+(?P<year>\d{{4}}))?")
def _day_month(match: re.Match[str], ctx: _Context) -> _Outcome:
    return _dated(int(match["d"]), _MONTHS[match["mon"]], match["year"], ctx)


@_rule(rf"{_MON_BARE}\s+(?P<d>\d{{1,2}})[a-z]*")
def _month_day(match: re.Match[str], ctx: _Context) -> _Outcome:
    # "kasımın 28'i"
    return _dated(int(match["d"]), _MONTHS[match["mon"]], None, ctx)


@_rule(r"(?P<d>\d{1,2})[./](?P<m>\d{1,2})(?:[./](?P<year>\d{4}|\d{2}))?[a-z]*")
def _numeric_date(match: re.Match[str], ctx: _Context) -> _Outcome:
    month = int(match["m"])
    if not 1 <= month <= 12:
        return _Unresolved(Reason.INVALID_DATE)
    return _dated(int(match["d"]), month, match["year"], ctx)


@_rule(r"(?P<year>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})")
def _iso_date(match: re.Match[str], ctx: _Context) -> _Outcome:
    value = _safe_date(int(match["year"]), int(match["m"]), int(match["d"]))
    return _day(value) if value else _Unresolved(Reason.INVALID_DATE)


# --- ranges: "28-29 kasım", "30 kasım - 2 aralık", "28 kasımdan 2 aralığa" ------------

_MON1 = _MON_BARE.replace("?P<mon>", "?P<mon1>")
_MON2 = _MON.replace("?P<mon>", "?P<mon2>")


@_rule(
    rf"(?P<d1>\d{{1,2}})(?:\s*{_MON1})?(?P<sep>\s*(?:-|ile|ve)\s*|\s+)"
    rf"(?P<d2>\d{{1,2}})\s*{_MON2}(?:\s+(?P<year>\d{{4}}))?(?:\s+aras\w*)?"
)
def _date_range(match: re.Match[str], ctx: _Context) -> _Outcome:
    if match["mon1"] is None and not match["sep"].strip():
        return _Unresolved(Reason.UNRECOGNIZED)  # "28 29 kasım": missing separator
    end_month = _MONTHS[match["mon2"]]
    start_month = _MONTHS[match["mon1"]] if match["mon1"] else end_month
    start_day, end_day = int(match["d1"]), int(match["d2"])

    def build(start_year: int) -> DateSpan | None:
        end_year = start_year + (1 if end_month < start_month else 0)
        start = _safe_date(start_year, start_month, start_day)
        end = _safe_date(end_year, end_month, end_day)
        if start is None or end is None or end < start:
            return None
        return DateSpan(start, end)

    if match["year"]:
        # The year belongs to the end date ("30 aralık - 2 ocak 2027").
        year = int(match["year"]) - (1 if end_month < start_month else 0)
        span = build(year)
        return span if span else _Unresolved(Reason.INVALID_DATE)
    years = (ctx.today.year - 1, ctx.today.year, ctx.today.year + 1)
    return _nearest([s for s in (build(y) for y in years) if s is not None], ctx.today)


# --- academic term --------------------------------------------------------------------


@_rule(r"donem\s*sonu\w*|final\s+donemi\w*")
def _term_end(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.term_end) if ctx.term_end else _Unresolved(Reason.TERM_UNKNOWN)


@_rule(r"donem\s*basi\w*")
def _term_start(_: re.Match[str], ctx: _Context) -> _Outcome:
    return _day(ctx.term_start) if ctx.term_start else _Unresolved(Reason.TERM_UNKNOWN)


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Parsed:
    phrase: str
    part: PartOfDay | None = None
    time: dt.time | None = None
    until: bool = False
    approximate: bool = False
    error: Reason | None = None
    parts_found: set[PartOfDay] = field(default_factory=set)


def _extract(phrase: str) -> _Parsed:
    parsed = _Parsed(phrase)

    times = list(_TIME.finditer(parsed.phrase))
    if len(times) > 1:
        parsed.error = Reason.INVALID_TIME
        return parsed
    if times:
        hour, minute = int(times[0]["h"]), int(times[0]["mi"])
        if hour > 23 or minute > 59:
            parsed.error = Reason.INVALID_TIME
            return parsed
        parsed.time = dt.time(hour, minute)
        parsed.phrase = _TIME.sub(" ", parsed.phrase)

    for part, pattern in _PARTS:
        regex = re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])")
        if regex.search(parsed.phrase):
            parsed.parts_found.add(part)
            parsed.phrase = regex.sub(" ", parsed.phrase)
    if len(parsed.parts_found) > 1:
        parsed.error = Reason.CONFLICTING_PARTS
        return parsed
    parsed.part = next(iter(parsed.parts_found), None)

    parsed.phrase = re.sub(r"\s+", " ", parsed.phrase).strip()
    if _APPROX.search(parsed.phrase):
        parsed.approximate = True
        parsed.phrase = _APPROX.sub("", parsed.phrase).strip()
    if _UNTIL.search(parsed.phrase):
        parsed.until = True
        parsed.phrase = _UNTIL.sub("", parsed.phrase).strip()
    return parsed


def _apply_part_to_time(time: dt.time, part: PartOfDay | None) -> dt.time | Reason:
    """'akşam 8:30' -> 20:30. A 24h time that contradicts the part of day is an error."""
    hour = time.hour
    if part in (PartOfDay.AFTERNOON, PartOfDay.EVENING) and 1 <= hour <= 11:
        return time.replace(hour=hour + 12)
    if part is PartOfDay.NIGHT and 6 <= hour <= 11:
        return time.replace(hour=hour + 12)
    if part is PartOfDay.MORNING and hour >= 12:
        return Reason.CONFLICTING_PARTS
    return time


def _match_date(phrase: str, ctx: _Context) -> _Outcome:
    for pattern, handler in _RULES:
        match = pattern.fullmatch(phrase)
        if match:
            return handler(match, ctx)
    return _Unresolved(Reason.UNRECOGNIZED)


def _until(outcome: _Outcome, today: dt.date) -> _Outcome:
    """'cumaya kadar' -> today..friday. Ranges ('28 kasımdan 2 aralığa kadar') stay as is."""

    def widen(span: DateSpan) -> DateSpan | None:
        if not span.is_single_day:
            return span
        return DateSpan(today, span.start) if span.start >= today else None

    if isinstance(outcome, DateSpan):
        return widen(outcome) or _Unresolved(Reason.UNTIL_PAST)
    if isinstance(outcome, _Ambiguous):
        widened = tuple(w for w in (widen(c) for c in outcome.candidates) if w is not None)
        if outcome.candidates and not widened:
            return _Unresolved(Reason.UNTIL_PAST)
        if len(widened) == 1 and outcome.reason is not Reason.VAGUE:
            return widened[0]
        return _Ambiguous(outcome.reason, widened)
    return outcome


def resolve(
    text: str,
    today: dt.date,
    *,
    term_start: dt.date | None = None,
    term_end: dt.date | None = None,
) -> Resolution:
    """Resolve a Turkish date phrase relative to `today` (a local date in APP_TIMEZONE)."""
    ctx = _Context(today, term_start, term_end)
    normalized = normalize(text)
    if not normalized:
        return Resolution(text, Status.UNRESOLVED, reason=Reason.EMPTY)
    if normalized in _VAGUE:
        return Resolution(text, Status.AMBIGUOUS, reason=Reason.VAGUE)

    parsed = _extract(normalized)
    if parsed.error:
        return Resolution(text, Status.UNRESOLVED, reason=parsed.error)

    time = parsed.time
    if time is not None:
        adjusted = _apply_part_to_time(time, parsed.part)
        if isinstance(adjusted, Reason):
            return Resolution(text, Status.UNRESOLVED, reason=adjusted)
        time = adjusted

    outcome: _Outcome
    if parsed.phrase in ("", "bu"):
        if parsed.part is None and time is None:  # "" or a lone "bu"
            outcome = _Unresolved(Reason.UNRECOGNIZED)
        elif parsed.phrase == "" and parsed.part is PartOfDay.MORNING and time is None:
            # Bare "sabah": this morning or tomorrow morning?
            outcome = _ambiguous(
                Reason.MORNING_TODAY_OR_TOMORROW, today, today + dt.timedelta(days=1)
            )
        else:
            outcome = _day(today)  # "bu akşam", "akşam", "14:00"
    else:
        outcome = _match_date(parsed.phrase, ctx)

    if parsed.until:
        outcome = _until(outcome, today)
    if parsed.approximate and isinstance(outcome, DateSpan):
        outcome = _Ambiguous(Reason.APPROXIMATE, (outcome,))

    if isinstance(outcome, DateSpan):
        return Resolution(text, Status.RESOLVED, span=outcome, part_of_day=parsed.part, time=time)
    if isinstance(outcome, _Ambiguous):
        return Resolution(
            text,
            Status.AMBIGUOUS,
            part_of_day=parsed.part,
            time=time,
            candidates=outcome.candidates,
            reason=outcome.reason,
        )
    return Resolution(text, Status.UNRESOLVED, reason=outcome.reason)


# --------------------------------------------------------------------------------------
# Calendar context for the model
# --------------------------------------------------------------------------------------

_RELATIVE_LABELS = {0: "bugün", 1: "yarın", 2: "öbür gün"}


def _week_label(offset: int) -> str:
    if offset == 0:
        return "bu hafta"
    if offset == 1:
        return "gelecek hafta"
    return f"{offset} hafta sonra"


def build_calendar_context(today: dt.date, days: int = 14) -> list[CalendarDay]:
    """Today plus the next `days` days, labelled the way the model should talk about them."""
    this_monday = week_start(today)
    calendar: list[CalendarDay] = []
    for offset in range(days + 1):
        day = today + dt.timedelta(days=offset)
        calendar.append(
            CalendarDay(
                date=day,
                weekday_name=WEEKDAY_NAMES_TR[day.weekday()],
                relative=_RELATIVE_LABELS.get(offset),
                week=_week_label((week_start(day) - this_monday).days // 7),
            )
        )
    return calendar


def format_calendar_context(calendar: list[CalendarDay]) -> str:
    """One line per day for the system prompt, e.g. '2026-11-19 Perşembe (bugün, bu hafta)'."""
    lines = []
    for day in calendar:
        labels = ", ".join(label for label in (day.relative, day.week) if label)
        lines.append(f"{day.date.isoformat()} {day.weekday_name} ({labels})")
    return "\n".join(lines)
