"""Clean-ups on the coordinator's final answer that a prompt alone doesn't guarantee."""

import re

from app.core.time_resolver import normalize

_SENTENCE = re.compile(r"[^.!?…]+(?:[.!?…]+|$)\s*")
_WORD = re.compile(r"\w+")
# "Karen:" / "Karen olarak sormak istiyorum:" in front of a question: a speaker label,
# not part of what is asked.
_LABEL = re.compile(r"^[^:?\n]{1,40}:\s+")
_COVERED = 0.9  # share of a question's words already asked before -> it is a repeat
_MIN_WORDS = 3  # shorter questions are dropped only when they repeat word for word


def _words(sentence: str) -> list[str]:
    # Words of 3+ letters, plus anything with a digit (course codes, dates, hours).
    return [
        w
        for w in _WORD.findall(normalize(sentence))
        if len(w) >= 3 or any(ch.isdigit() for ch in w)
    ]


def _is_repeat(question: str, asked: list[list[str]]) -> bool:
    words = _words(_LABEL.sub("", question.strip()))
    if not words:
        return False
    if any(words == earlier for earlier in asked):
        return True
    if len(words) < _MIN_WORDS:
        return False
    seen = {w for earlier in asked for w in earlier}
    if any(ch.isdigit() for w in words if w not in seen for ch in w):
        return False  # another course code / date / hour: a different question
    covered = sum(1 for w in words if w in seen) / len(words)
    return covered >= _COVERED


def dedupe_questions(text: str) -> str:
    """Drops a question sentence that repeats one already asked earlier in the answer
    (the same yaver question passed on twice, e.g. once in the yaver's line and once in a
    closing sentence). Everything else is kept as written."""
    asked: list[list[str]] = []
    lines = []
    for line in text.split("\n"):
        kept = []
        for sentence in _SENTENCE.findall(line):
            if sentence.rstrip().endswith("?"):
                if _is_repeat(sentence, asked):
                    continue
                asked.append(_words(_LABEL.sub("", sentence.strip())))
            kept.append(sentence)
        cleaned = "".join(kept).rstrip()
        if cleaned or not line.strip():
            lines.append(cleaned if line.strip() else line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
