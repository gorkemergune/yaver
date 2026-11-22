"""Startup meetings: an event about the startup ("bugün akşam NEXA toplantısı var") is linked
to Venture (events.owner_id) when it is added, and an hour before it Venture sends the week's
presentation draft - who did what in the latest weekN folder, whose folder is empty
(app.jobs.meeting_prep).

Which events: the startup's names - agents.yaml `keywords` of Venture, the proper names in its
area text (a personal domain "Startup - Nexa Lab işleri" gives "Nexa Lab"; matched by its first
word too, "NEXA") - or a repo / weekN in the words. No imports of the tool registry here: the
add_event tool imports this module.
"""

import re
from collections.abc import Iterable

from app.agent.intents import startup_signal
from app.core.time_resolver import normalize

STARTUP_ID = "startup"
MEETING_KINDS = frozenset({"meeting", "other", "hackathon", "deadline"})
# capitalised words of an area text that are not a name of the user's own
GENERIC = {
    "startup", "github", "meta", "instagram", "facebook", "linkedin", "google", "ai", "mvp",
    "girisim", "tr", "turkiye",
}  # fmt: skip
_PROPER = re.compile(r"\b[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ]*(?:\s+[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ]*)*")


def names_in(domain: str) -> list[str]:
    """'Startup - Nexa Lab işleri, haftalık hedefler' -> ['Nexa Lab']."""
    found = []
    for match in _PROPER.finditer(domain):
        words = [w for w in match.group(0).split() if normalize(w) not in GENERIC]
        if words:
            found.append(" ".join(words))
    return list(dict.fromkeys(found))


def startup_names(keywords: Iterable[str], domain: str) -> list[str]:
    return list(dict.fromkeys([*keywords, *names_in(domain)]))


def about_the_startup(text: str, names: Iterable[str]) -> bool:
    """The words name the startup (a whole name or its first word, 4+ letters) or its repo."""
    words = set(re.findall(r"\w+", normalize(text)))
    plain = normalize(text)
    for name in names:
        key = normalize(name)
        first = key.split()[0] if key.split() else ""
        if key and (
            re.search(rf"\b{re.escape(key)}\b", plain) or (len(first) >= 4 and first in words)
        ):
            return True
    return startup_signal(text)


def team_names() -> tuple[str | None, list[str]]:
    """(Venture's id if it is in the team, its names) from the running team."""
    from app.agent.team import get_team  # lazily: the team module loads the tool registry

    member = get_team().get(STARTUP_ID)
    if member is None:
        return None, []
    return member.id, startup_names(member.keywords, member.domain)


def owner_for(kind: str, *texts: str | None) -> str | None:
    """Venture for a meeting about the startup, else None."""
    if kind not in MEETING_KINDS:
        return None
    owner, names = team_names()
    if owner is None:
        return None
    return owner if about_the_startup(" ".join(t for t in texts if t), names) else None


def name_of(employee_id: str) -> str:
    from app.agent.team import get_team  # lazily, as team_names

    member = get_team().get(employee_id)
    return member.name if member is not None else employee_id
