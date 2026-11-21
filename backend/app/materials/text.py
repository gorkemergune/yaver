"""The text of a material, page by page: PDFs through pypdf (app.rag.pdf), Word files (.docx)
read from their XML in code (no extra dependency), cut into ~3000-character "pages"."""

import html
import io
import re
import zipfile

from app.rag.pdf import is_pdf, page_texts

DOCX_PAGE_CHARS = 3000
PARAGRAPH = re.compile(r"<w:p[ >].*?</w:p>", re.S)
TAG = re.compile(r"<[^>]+>")


class UnreadableError(ValueError):
    """Not a PDF or .docx, or a broken one."""


def document_pages(filename: str, raw: bytes) -> list[str]:
    if is_pdf(raw):
        return page_texts(raw)
    if filename.lower().endswith(".docx"):
        return docx_pages(raw)
    raise UnreadableError(f"{filename}: not a PDF or .docx")


def docx_pages(raw: bytes, page_chars: int = DOCX_PAGE_CHARS) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
        raise UnreadableError(f"broken .docx: {exc}") from exc
    paragraphs = []
    for block in PARAGRAPH.findall(xml):
        text = html.unescape(TAG.sub("", block.replace("<w:tab/>", " "))).strip()
        if text:
            paragraphs.append(text)
    pages: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if current and size + len(paragraph) > page_chars:
            pages.append("\n".join(current))
            current, size = [], 0
        current.append(paragraph)
        size += len(paragraph) + 1
    if current:
        pages.append("\n".join(current))
    return pages
