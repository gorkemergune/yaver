"""Meta Ads Manager CSV exports -> rows, in code (no LLM).

Ads Manager exports one row per campaign, ad set or ad (whichever level the table showed),
with the column names of the interface language: English ("Campaign name", "Amount spent
(TRY)", "CTR (link click-through rate)") or Turkish ("Kampanya adı", "Harcanan tutar
(TRY)", "TO (bağlantı tıklama oranı)"). Turkish Excel saves with ";" and decimal commas.
A total row (no name) is skipped; CTR / CPC / cost per result missing from the file are
computed from spend, impressions, clicks and results.
"""

import csv
import datetime as dt
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

LEVELS = ("campaign", "adset", "ad")


class AdsParseError(ValueError):
    """Not an ads export we can read (the message says why, in Turkish)."""


@dataclass(slots=True)
class AdRow:
    level: str
    name: str
    campaign: str | None = None
    spend: Decimal | None = None
    impressions: int | None = None
    reach: int | None = None
    clicks: int | None = None
    ctr: Decimal | None = None  # percent
    cpc: Decimal | None = None
    results: int | None = None
    result_type: str | None = None
    cost_per_result: Decimal | None = None

    def complete(self) -> "AdRow":
        """Fills CTR / CPC / cost per result from the raw numbers where the file had none."""
        if self.ctr is None and self.clicks is not None and self.impressions:
            self.ctr = round(Decimal(self.clicks) * 100 / self.impressions, 4)
        if self.cpc is None and self.spend is not None and self.clicks:
            self.cpc = round(self.spend / self.clicks, 4)
        if self.cost_per_result is None and self.spend is not None and self.results:
            self.cost_per_result = round(self.spend / self.results, 4)
        return self


@dataclass(slots=True)
class ParsedAds:
    level: str
    rows: list[AdRow]
    period_start: dt.date | None = None
    period_end: dt.date | None = None
    currency: str | None = None
    unclear: list[str] = field(default_factory=list)


def fold(text: str) -> str:
    """Lowercase ASCII-ish header: 'Harcanan Tutar (TRY)' -> 'harcanan tutar (try)'."""
    table = str.maketrans("İIıŞşĞğÜüÖöÇç", "iiissgguuoocc")
    return re.sub(r"\s+", " ", text.translate(table).lower()).strip()


_CURRENCY_SUFFIX = re.compile(r"\s*\(([A-Za-z]{3})\)\s*$")

Match = Callable[[str], bool]


def _starts(*prefixes: str) -> Match:
    return lambda header: any(header.startswith(p) for p in prefixes)


def _has(*parts: str) -> Match:
    return lambda header: any(p in header for p in parts)


def _is(*names: str) -> Match:
    return lambda header: header in names


# field -> matchers, best first (link clicks beat "all" clicks).
COLUMNS: dict[str, list[Match]] = {
    "ad": [_is("ad name", "reklam adi")],
    "adset": [_is("ad set name", "reklam seti adi")],
    "campaign": [_is("campaign name", "kampanya adi")],
    "start": [_starts("reporting starts", "raporlama baslangici", "raporlama baslangic")],
    "end": [_starts("reporting ends", "raporlama bitisi", "raporlama bitis")],
    "spend": [_starts("amount spent", "harcanan tutar", "harcanan miktar")],
    "impressions": [_is("impressions", "gosterim", "gosterimler")],
    "reach": [_is("reach", "erisim")],
    "clicks": [
        _starts("link clicks", "baglanti tiklamalari"),
        _starts("clicks (all)", "tiklamalar (tumu)", "clicks", "tiklamalar"),
    ],
    "ctr": [
        _has("link click-through rate", "baglanti tiklama orani"),
        _starts("ctr", "to (", "tiklama orani"),
    ],
    "cpc": [
        _has("cost per link click", "baglanti tiklamasi basina"),
        _starts("cpc", "tbm", "tiklama basina maliyet"),
    ],
    "results": [_is("results", "sonuclar", "sonuc")],
    "result_type": [_starts("result indicator", "result type", "sonuc gostergesi", "sonuc turu")],
    "cost_per_result": [_starts("cost per result", "sonuc basina maliyet")],
    "currency": [_is("currency", "para birimi")],
}


def parse_meta_csv(raw: bytes) -> ParsedAds:
    text = _decode(raw)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise AdsParseError("Dosya boş.")
    delimiter = max(";,\t", key=lambda d: lines[0].count(d))
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    header, *records = list(reader)
    columns, currency = _columns(header)
    if "spend" not in columns:
        raise AdsParseError(
            'Harcama sütunu yok ("Amount spent" / "Harcanan tutar"): bu bir Meta Ads '
            "Manager dışa aktarımı gibi görünmüyor."
        )
    level = next((lvl for lvl in ("ad", "adset", "campaign") if lvl in columns), None)
    if level is None:
        raise AdsParseError("Kampanya / reklam seti / reklam adı sütunu yok.")
    decimal_comma = delimiter == ";"

    def cell(record: list[str], name: str) -> str:
        index = columns.get(name)
        return record[index].strip() if index is not None and index < len(record) else ""

    rows: list[AdRow] = []
    starts: list[dt.date] = []
    ends: list[dt.date] = []
    unclear: list[str] = []
    for record in records:
        name = cell(record, level)
        if not name:  # the total row
            continue
        row = AdRow(
            level=level,
            name=name[:300],
            campaign=(cell(record, "campaign") or None) if level != "campaign" else None,
        )
        for attr in ("spend", "ctr", "cpc", "cost_per_result"):
            setattr(row, attr, _number(cell(record, attr), decimal_comma))
        for attr in ("impressions", "reach", "clicks", "results"):
            value = _number(cell(record, attr), decimal_comma)
            setattr(row, attr, int(value.to_integral_value()) if value is not None else None)
        row.result_type = cell(record, "result_type") or None
        rows.append(row.complete())
        for raw_date, bucket in ((cell(record, "start"), starts), (cell(record, "end"), ends)):
            if raw_date:
                parsed = _date(raw_date)
                if parsed is None:
                    unclear.append(f"Tarih okunamadı: {raw_date}")
                else:
                    bucket.append(parsed)
        currency = currency or cell(record, "currency") or None
    if not rows:
        raise AdsParseError("Dosyada kampanya satırı yok.")
    return ParsedAds(
        level=level,
        rows=rows,
        period_start=min(starts) if starts else None,
        period_end=max(ends) if ends else None,
        currency=currency.upper() if currency else None,
        unclear=sorted(set(unclear)),
    )


def looks_like_csv(filename: str | None, raw: bytes) -> bool:
    """A .csv upload, or text whose first line has several ; or , separated fields."""
    if filename and filename.lower().endswith(".csv"):
        return True
    try:
        first = _decode(raw[:4096]).splitlines()[0]
    except (AdsParseError, IndexError):
        return False
    return max(first.count(";"), first.count(","), first.count("\t")) >= 3


def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if b"\x00" in raw[:200]:
        raise AdsParseError("Metin dosyası değil.")
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AdsParseError("Dosyanın karakter kodlaması okunamadı.")


def _columns(header: list[str]) -> tuple[dict[str, int], str | None]:
    folded: list[str] = []
    currency = None
    for name in header:
        clean = fold(name)
        suffix = _CURRENCY_SUFFIX.search(clean)
        if suffix and suffix.group(1).isalpha():
            currency = currency or suffix.group(1).upper()
            clean = clean[: suffix.start()].strip()
        folded.append(clean)
    columns: dict[str, int] = {}
    taken: set[int] = set()
    for name, matchers in COLUMNS.items():
        for match in matchers:  # the first matcher with a hit wins
            index = next((i for i, h in enumerate(folded) if i not in taken and match(h)), None)
            if index is not None:
                columns[name] = index
                taken.add(index)
                break
    return columns, currency


_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")


def _number(text: str, decimal_comma: bool) -> Decimal | None:
    """'1.234,56' / '1,234.56' / '₺1.234' / '%1,25' / '-' -> Decimal or None."""
    clean = re.sub(r"[^\d,.\-]", "", text)
    if not clean or clean in {"-", ".", ","}:
        return None
    if "," in clean and "." in clean:
        decimal = "," if clean.rfind(",") > clean.rfind(".") else "."
    elif "," in clean:
        decimal = "," if decimal_comma or not _THOUSANDS_COMMA.match(clean) else ""
    elif "." in clean:
        decimal = "" if decimal_comma and _THOUSANDS_DOT.match(clean) else "."
    else:
        decimal = "."
    thousands = {",": ".", ".": ","}.get(decimal, ",." if not decimal else "")
    for sep in thousands:
        clean = clean.replace(sep, "")
    if decimal == ",":
        clean = clean.replace(",", ".")
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None


_MONTHS = {
    **{
        m: i
        for i, m in enumerate(
            ["oca", "sub", "mar", "nis", "may", "haz", "tem", "agu", "eyl", "eki", "kas", "ara"],
            start=1,
        )
    },
    **{
        m: i
        for i, m in enumerate(
            ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
            start=1,
        )
    },
}
_NUMERIC_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})[./](\d{1,2})[./](\d{4})")
_DAY_MONTH = re.compile(r"(\d{1,2})\s+([a-z]{3})[a-z]*\.?(?:\s+(\d{4}))?")
_MONTH_DAY = re.compile(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?(?:\s+(\d{4}))?")


def parse_period(text: str | None) -> tuple[dt.date, dt.date] | None:
    """A date range as written on a screenshot -> (start, end), or None if it is not two
    clear dates. '9 Kas 2026 - 15 Kas 2026', '9-15 Kas 2026' is not supported on purpose
    (the model is asked for both dates as written); a year missing on the first date is
    taken from the second ('9 Kas - 15 Kas 2026')."""
    if not text:
        return None
    folded = fold(text)
    found: list[tuple[int, int, int | None, int]] = []  # (day, month, year, position)
    for m in _NUMERIC_DATE.finditer(folded):
        if m.group(1):
            found.append((int(m.group(3)), int(m.group(2)), int(m.group(1)), m.start()))
        else:
            found.append((int(m.group(4)), int(m.group(5)), int(m.group(6)), m.start()))
    if not found:
        for m in _DAY_MONTH.finditer(folded):
            if m.group(2) in _MONTHS:
                year = int(m.group(3)) if m.group(3) else None
                found.append((int(m.group(1)), _MONTHS[m.group(2)], year, m.start()))
        if not found:
            for m in _MONTH_DAY.finditer(folded):
                if m.group(1) in _MONTHS:
                    year = int(m.group(3)) if m.group(3) else None
                    found.append((int(m.group(2)), _MONTHS[m.group(1)], year, m.start()))
    found.sort(key=lambda item: item[3])
    if len(found) != 2:
        return None
    (d1, m1, y1, _), (d2, m2, y2, _) = found
    if y2 is None:
        return None
    if y1 is None:
        y1 = y2 if (m1, d1) <= (m2, d2) else y2 - 1
    try:
        start, end = dt.date(y1, m1, d1), dt.date(y2, m2, d2)
    except ValueError:
        return None
    return (start, end) if start <= end else None


def _date(text: str) -> dt.date | None:
    text = text.strip()
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text[:10], pattern).replace(tzinfo=dt.UTC).date()
        except ValueError:
            continue
    return None
