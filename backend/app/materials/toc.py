"""A material's table of contents: chapters / sections / experiments with their PDF pages.

1. The PDF's own outline (bookmarks), when it has one.
2. Otherwise the printed "Contents" page: lines like "4.e Experiment #5 ... 38" (a title may
   run onto the next line). Printed page numbers are moved to PDF pages by finding the
   section titles in the text (the offset most titles agree on).
Pages always come from the PDF, never from a model.
"""

import io
import logging
import re
from collections import Counter
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.time_resolver import normalize

logger = logging.getLogger(__name__)

CONTENTS_HEADINGS = ("contents", "table of contents", "icindekiler")
CONTENTS_SCAN_PAGES = 8
# "4.e Experiment #5 ..... 38", "1.3 Matrix Algebra 27", "Chapter 2 Determinants 85"
LINE = re.compile(
    r"^(?:(?:chapter|bolum|section)\s+)?(?P<number>\d{1,2}(?:\.[0-9a-z]{1,2}){0,2})\.?\s+"
    r"(?P<title>.*?)[\s.·…]+(?P<page>\d{1,4})\s*$",
    re.IGNORECASE,
)
TRAILING_PAGE = re.compile(r"^(?P<title>.*?)[\s.·…]+(?P<page>\d{1,4})\s*$")
NUMBER_ONLY = re.compile(
    r"^(?P<number>\d{1,2}(?:\.[0-9a-z]{1,2}){0,2})\.?\s+(?P<title>\D.*)$", re.I
)


@dataclass(slots=True)
class Section:
    number: str | None
    title: str
    page_start: int  # PDF page, 1-based
    page_end: int
    level: int = 1


def sections(raw: bytes, pages: list[str]) -> list[Section]:
    found = _from_outline(raw) or _from_contents(pages)
    return _with_ends(found, len(pages))


def _from_outline(raw: bytes) -> list[Section]:
    try:
        reader = PdfReader(io.BytesIO(raw))
        outline = reader.outline
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        logger.info("no PDF outline: %s", exc)
        return []
    found: list[Section] = []

    def walk(items: list[object], level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                index = reader.get_destination_page_number(item)  # type: ignore[arg-type]
            except Exception:  # broken destinations are common in exported PDFs
                continue
            if index is None:
                continue
            page = index + 1
            title = str(getattr(item, "title", "") or "").strip()
            if title and page >= 1:
                number, rest = _split_number(title)
                found.append(Section(number, rest, page, page, level))

    walk(list(outline), 1)
    return found


def _split_number(title: str) -> tuple[str | None, str]:
    match = NUMBER_ONLY.match(title)
    if match:
        return match["number"], match["title"].strip()
    return None, title


def _contents_page(pages: list[str]) -> int | None:
    for index, text in enumerate(pages[:CONTENTS_SCAN_PAGES]):
        head = normalize(text[:200])
        if any(heading in head for heading in CONTENTS_HEADINGS):
            return index
    return None


def _from_contents(pages: list[str]) -> list[Section]:
    index = _contents_page(pages)
    if index is None:
        return []
    lines = [line.strip() for line in pages[index].splitlines() if line.strip()]
    entries: list[tuple[str | None, str, int]] = []
    pending: tuple[str, str] | None = None  # "4.a Experiment #1" waiting for its page line
    for line in lines:
        match = LINE.match(line)
        if match and match["title"].strip():
            entries.append((match["number"], _tidy(match["title"]), int(match["page"])))
            pending = None
            continue
        start = NUMBER_ONLY.match(line)
        if start and not TRAILING_PAGE.match(line):
            pending = (start["number"], start["title"].strip())
            continue
        tail = TRAILING_PAGE.match(line)
        if pending and tail:
            title = f"{pending[1]}: {_tidy(tail['title'])}"
            entries.append((pending[0], title, int(tail["page"])))
            pending = None
    if not entries:
        return []
    offset = _offset(entries, pages, index)
    return [
        Section(number, title, max(1, min(len(pages), printed + offset)), 0, _level(number))
        for number, title, printed in entries
    ]


def _tidy(title: str) -> str:
    return re.sub(r"[\s.·…]+$", "", title).strip()


def _level(number: str | None) -> int:
    return 1 + (number or "").count(".")


def _offset(entries: list[tuple[str | None, str, int]], pages: list[str], contents: int) -> int:
    """PDF page - printed page, as most titles found in the text agree (0 if none found)."""
    votes: Counter[int] = Counter()
    lowered = [normalize(p) for p in pages]
    for _, title, printed in entries:
        key = normalize(title.split(":")[-1])[:30].strip()
        if len(key) < 6:
            continue
        for number in range(contents + 1, len(pages)):
            if key in lowered[number]:
                votes[(number + 1) - printed] += 1
                break
    return votes.most_common(1)[0][0] if votes else 0


def _with_ends(found: list[Section], total: int) -> list[Section]:
    """A section ends where the next one of the same or a higher level starts."""
    ordered = sorted(found, key=lambda s: (s.page_start, s.level))
    for i, section in enumerate(ordered):
        end = total
        for later in ordered[i + 1 :]:
            if later.level <= section.level and later.page_start > section.page_start:
                end = later.page_start - 1
                break
        section.page_end = max(section.page_start, end)
    return ordered
