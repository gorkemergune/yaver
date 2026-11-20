"""Pages -> overlapping passages that remember their pages ("s. 3-4")."""

from dataclasses import dataclass

# The embedding model reads ~128 tokens (~500 characters of Turkish): longer passages would
# be embedded by their beginning only.
TARGET_CHARS = 500
OVERLAP_CHARS = 100
MIN_CHARS = 40  # shorter leftovers (a lone page number) are dropped
PAGE_BREAK_CHARS = 300  # short pages (slides) are packed together, longer ones are not


@dataclass(frozen=True, slots=True)
class Chunk:
    content: str
    page_start: int  # 1-based
    page_end: int


def chunk_pages(
    pages: list[str], target: int = TARGET_CHARS, overlap: int = OVERLAP_CHARS
) -> list[Chunk]:
    """Paragraphs are packed up to `target` characters; the next passage repeats the last
    `overlap` characters so a sentence cut at the edge is still found."""
    pieces: list[tuple[int, str]] = []
    for number, text in enumerate(pages, start=1):
        for paragraph in text.split("\n\n"):
            paragraph = paragraph.strip()
            while len(paragraph) > target:  # a page-long paragraph: cut at a space
                cut = paragraph.rfind(" ", 0, target)
                cut = cut if cut > target // 2 else target
                pieces.append((number, paragraph[:cut].strip()))
                paragraph = paragraph[cut:].strip()
            if paragraph:
                pieces.append((number, paragraph))

    chunks: list[Chunk] = []
    buffer: list[tuple[int, str]] = []
    size = 0
    for number, piece in pieces:
        new_page = bool(buffer) and number != buffer[-1][0]
        if new_page and size >= PAGE_BREAK_CHARS:
            # a well-filled passage stays on its page: citations say "s. 2", not "s. 1-2"
            chunks.append(_make(buffer))
            buffer, size = [], 0
        elif buffer and size + len(piece) > target:
            chunks.append(_make(buffer))
            tail = _make(buffer).content[-overlap:]
            buffer = [(buffer[-1][0], tail)] if overlap and len(tail) >= MIN_CHARS else []
            size = sum(len(p) for _, p in buffer)
        buffer.append((number, piece))
        size += len(piece) + 2
    if buffer:
        chunks.append(_make(buffer))
    return [c for c in chunks if len(c.content) >= MIN_CHARS]


def _make(buffer: list[tuple[int, str]]) -> Chunk:
    return Chunk(
        content="\n\n".join(p for _, p in buffer),
        page_start=buffer[0][0],
        page_end=buffer[-1][0],
    )
