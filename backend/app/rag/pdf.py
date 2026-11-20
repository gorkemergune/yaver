"""PDF -> text per page (pypdf; no OCR: a scanned PDF has no text layer)."""

import io
import logging
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

MAX_PAGES = 300


class PdfError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def is_pdf(raw: bytes) -> bool:
    return raw[:1024].lstrip().startswith(b"%PDF-")


def page_texts(raw: bytes) -> list[str]:
    """Text of every page (index 0 = page 1), whitespace tidied."""
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise PdfError("encrypted")
        pages = reader.pages
        if len(pages) > MAX_PAGES:
            raise PdfError("too_many_pages")
        texts = []
        for page in pages:
            try:
                text = page.extract_text() or ""
            except Exception:  # one broken page must not lose the rest
                logger.warning("PDF page could not be read", exc_info=True)
                text = ""
            texts.append(_tidy(text))
        return texts
    except PdfReadError as exc:
        raise PdfError("unreadable") from exc


def _tidy(text: str) -> str:
    text = text.replace("\u00a0", " ")  # no-break space
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
