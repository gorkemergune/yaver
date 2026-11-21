"""Venture and the startup's GitHub repository (read only), all in code, no LLM.

- The map: README, week folders (hafta-03 / week_3), meeting notes, open issues,
  milestones, the last week's commits. Written to Venture's notebook the first time the
  token works.
- Every morning (`github_watch` shift job):
  * who handed something in to the latest week folder (commits touching it), who not yet;
  * dated items - lines with a date in meeting notes / issues, milestones with a due
    date - become an all-day deadline in the calendar + an on-date follow-up, once
    (marker "[github:<key>]" in their notes), in one change set (undoable);
  * an item due within REMIND_DAYS without a related file or pull request -> reminder;
    with one -> its follow-up is closed.
Dates are parsed in code; a date without a year is the one closest to today
("10 Kasım" in late November is past, "3 Ocak" is next January).
"""

import datetime as dt
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.change_log import ChangeRecorder
from app.db.models import EmployeeNote, Event, Followup
from app.db.models.enums import EventKind, FollowupCheckRule, FollowupStatus
from app.integrations.github import GitHub, RepoEntry, commit_author

logger = logging.getLogger(__name__)

MAP_TITLE = "GitHub deposu haritası"
REMIND_DAYS = 3
RECENT_DAYS = 7
MAX_NOTE_FILES = 5  # meeting notes read per morning (newest first)
TEXT_EXTENSIONS = (".md", ".markdown", ".txt")
WEEK_DIR = re.compile(r"^(?:hafta|week|w)[-_ ]?0*(\d{1,2})$", re.IGNORECASE)
MEETING = re.compile(r"toplant|meeting|minutes|notlar|notes", re.IGNORECASE)
MONTHS_TR = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7,
    "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}  # fmt: skip
_ISO = re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")
_DOTTED = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](20\d\d)\b")
_WRITTEN = re.compile(
    r"\b(\d{1,2})\s+(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)"
    r"[a-z]*(?:\s+(20\d\d))?\b"
)
STOP_WORDS = {
    "icin", "ile", "olan", "gibi", "teslim", "tarihi", "son", "hali", "hafta", "yapilacak",
    "yapilmasi", "gerekiyor", "olarak", "kadar", "the", "and", "for", "with", "due",
}  # fmt: skip


def fold(text: str) -> str:
    table = str.maketrans("İIıŞşĞğÜüÖöÇç", "iiissgguuoocc")
    return text.translate(table).lower()


# ---- the map ---------------------------------------------------------------------------


@dataclass(slots=True)
class RepoMap:
    repo: str
    description: str | None
    readme_title: str | None
    readme_summary: str | None
    entries: list[RepoEntry]
    weeks: dict[int, str]  # week number -> folder path
    week_files: dict[int, list[str]]
    meeting_notes: list[str]
    issues: list[dict[str, Any]]
    milestones: list[dict[str, Any]]
    pulls: list[dict[str, Any]]
    recent_commits: list[dict[str, Any]]
    contributors: list[str]

    @property
    def files(self) -> list[str]:
        return [e.path for e in self.entries if e.kind == "blob"]


async def load_map(github: GitHub, now: dt.datetime) -> RepoMap:
    info = await github.info()
    entries = await github.tree()
    readme = await github.readme()
    weeks: dict[int, str] = {}
    for entry in entries:
        name = entry.path.rsplit("/", 1)[-1]
        match = WEEK_DIR.match(name)
        if entry.kind == "tree" and match and entry.path.count("/") <= 1:
            weeks.setdefault(int(match.group(1)), entry.path)
    week_files = {
        n: [e.path for e in entries if e.kind == "blob" and e.path.startswith(f"{folder}/")]
        for n, folder in weeks.items()
    }
    meeting_notes = sorted(
        (
            e.path
            for e in entries
            if e.kind == "blob"
            and e.path.lower().endswith(TEXT_EXTENSIONS)
            and MEETING.search(e.path)
            and not any(e.path.startswith(f"{f}/") for f in weeks.values())
        ),
        reverse=True,  # dated file names: newest first
    )
    title, summary = _readme_parts(readme)
    return RepoMap(
        repo=github.repo,
        description=info.get("description"),
        readme_title=title,
        readme_summary=summary,
        entries=entries,
        weeks=dict(sorted(weeks.items())),
        week_files=week_files,
        meeting_notes=meeting_notes,
        issues=await github.issues(),
        milestones=await github.milestones(),
        pulls=await github.pulls(),
        recent_commits=await github.commits(since=now - dt.timedelta(days=RECENT_DAYS)),
        contributors=await github.contributors(),
    )


def _readme_parts(readme: str | None) -> tuple[str | None, str | None]:
    if not readme:
        return None, None
    lines = [line.strip() for line in readme.splitlines()]
    title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), None)
    paragraph: list[str] = []
    for line in lines:
        if not line or line.startswith(("#", "!", "[!", "<", "|", "```")):
            if paragraph:
                break
            continue
        paragraph.append(line)
    summary = " ".join(paragraph)
    return title, (summary[:300] + ("..." if len(summary) > 300 else "")) or None


def map_note(m: RepoMap) -> str:
    lines = [f"{MAP_TITLE} ({m.repo}):"]
    about = m.readme_title or m.repo
    if m.readme_summary or m.description:
        about += f" - {m.readme_summary or m.description}"
    lines.append(f"README: {about}")
    if m.weeks:
        last = max(m.weeks)
        lines.append(
            f"Hafta klasörleri: {', '.join(m.weeks.values())} "
            f"(son: {m.weeks[last]}, {len(m.week_files[last])} dosya)"
        )
    else:
        lines.append("Hafta klasörü yok.")
    if m.meeting_notes:
        shown = ", ".join(m.meeting_notes[:3])
        more = f" +{len(m.meeting_notes) - 3}" if len(m.meeting_notes) > 3 else ""
        lines.append(f"Toplantı notları: {len(m.meeting_notes)} ({shown}{more})")
    if m.issues:
        shown = "; ".join(f"#{i['number']} {i['title']}" for i in m.issues[:5])
        lines.append(f"Açık issue: {len(m.issues)} ({shown})")
    if m.milestones:
        shown = "; ".join(
            f"{ms['title']}" + (f" ({ms['due_on'][:10]})" if ms.get("due_on") else "")
            for ms in m.milestones
        )
        lines.append(f"Milestone: {shown}")
    authors = sorted({commit_author(c) for c in m.recent_commits})
    lines.append(
        f"Son {RECENT_DAYS} gün: {len(m.recent_commits)} commit"
        + (f" ({', '.join(authors)})" if authors else "")
    )
    if m.contributors:
        lines.append(f"Ekip (katkı verenler): {', '.join(m.contributors)}")
    return "\n".join(lines)


# ---- dated items -----------------------------------------------------------------------


@dataclass(slots=True)
class DatedItem:
    key: str  # stable: "issue:4", "milestone:2", "note:<path>:<date>:<words>"
    title: str
    day: dt.date
    source: str  # where it was found, for the event's notes
    issue_number: int | None = None
    keywords: list[str] = field(default_factory=list)


def dates_in(line: str, today: dt.date) -> list[tuple[dt.date, tuple[int, int]]]:
    """Dates written in a line with their span; without a year: the one closest to today."""
    text = fold(line)
    found: list[tuple[dt.date, tuple[int, int]]] = []
    for pattern, order in ((_ISO, "ymd"), (_DOTTED, "dmy")):
        for m in pattern.finditer(text):
            y, mo, d = (
                (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if order == "ymd"
                else (int(m.group(3)), int(m.group(2)), int(m.group(1)))
            )
            try:
                found.append((dt.date(y, mo, d), m.span()))
            except ValueError:
                continue
    for m in _WRITTEN.finditer(text):
        month, day = MONTHS_TR[m.group(2)], int(m.group(1))
        try:
            if m.group(3):
                found.append((dt.date(int(m.group(3)), month, day), m.span()))
                continue
            years = (today.year - 1, today.year, today.year + 1)
            candidate = min(
                (dt.date(y, month, day) for y in years), key=lambda d: abs((d - today).days)
            )
            found.append((candidate, m.span()))
        except ValueError:
            continue
    return found


def keywords(text: str) -> list[str]:
    words = [w for w in re.split(r"[^a-z0-9]+", fold(text)) if len(w) >= 4]
    return [w for w in dict.fromkeys(words) if w not in STOP_WORDS][:6]


def _title(line: str, span: tuple[int, int]) -> str:
    text = line[: span[0]] + line[span[1] :]
    text = re.sub(r"^\s*(?:(?:[-*•]|\d+[.)]|\[[ xX]\])\s*)+", "", text)
    text = re.sub(r"\s*[:\-–(]\s*$|^\s*[:\-–)]\s*", "", text.strip())  # noqa: RUF001
    return re.sub(r"\s{2,}", " ", text).strip(" :-")[:120]


def items_from_text(text: str, source: str, key_prefix: str, today: dt.date) -> list[DatedItem]:
    items = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue  # headings carry the meeting's own date, not a task
        for day, span in dates_in(line, today):
            title = _title(line, span)
            if not title:
                continue
            words = keywords(title)
            key = f"{key_prefix}:{day.isoformat()}:{'-'.join(words[:3]) or 'madde'}"
            items.append(DatedItem(key, title, day, source, keywords=words))
            break  # one item per line
    return items


async def dated_items(github: GitHub, m: RepoMap, today: dt.date) -> list[DatedItem]:
    items: list[DatedItem] = []
    for path in m.meeting_notes[:MAX_NOTE_FILES]:
        text = await github.text(path)
        if text:
            items += items_from_text(text, f"toplantı notu {path}", f"note:{path}", today)
    for issue in m.issues:
        number, title = issue["number"], issue["title"]
        found = dates_in(f"{title}\n{issue.get('body') or ''}", today)
        if found:
            items.append(
                DatedItem(
                    f"issue:{number}", f"#{number} {title}"[:120], found[0][0],
                    f"issue #{number}", number, keywords(title),
                )
            )  # fmt: skip
    for milestone in m.milestones:
        if milestone.get("due_on"):
            day = dt.date.fromisoformat(milestone["due_on"][:10])
            items.append(
                DatedItem(
                    f"milestone:{milestone['number']}", f"{milestone['title']} (milestone)",
                    day, "milestone", keywords=keywords(milestone["title"]),
                )
            )  # fmt: skip
    unique = {item.key: item for item in items}
    return sorted(unique.values(), key=lambda i: (i.day, i.title))


def evidence(item: DatedItem, m: RepoMap) -> str | None:
    """A pull request or file that looks like the item's work, or None."""
    if item.issue_number is not None:
        ref = f"#{item.issue_number}"
        for pr in m.pulls:
            if re.search(rf"{ref}\b", f"{pr.get('title', '')} {pr.get('body') or ''}"):
                return f"PR #{pr['number']}"
    words = item.keywords
    if not words:
        return None
    need = min(2, len(words))

    def hits(text: str) -> int:
        folded = fold(text)
        return sum(1 for w in words if w in folded)

    for pr in m.pulls:
        if hits(pr.get("title", "")) >= need:
            return f"PR #{pr['number']}"
    for path in m.files:
        if hits(path) >= need:
            return path
    return None


# ---- week hand-ins ---------------------------------------------------------------------


async def week_status(github: GitHub, m: RepoMap) -> str | None:
    if not m.weeks:
        return None
    number = max(m.weeks)
    folder = m.weeks[number]
    authors = sorted({commit_author(c) for c in await github.commits(path=folder)})
    missing = [person for person in m.contributors if person not in authors]
    line = (
        f"Hafta {number} ({folder}/, {len(m.week_files[number])} dosya): "
        f"teslim eden {', '.join(authors) if authors else 'yok'}"
    )
    return line + (f"; henüz yok: {', '.join(missing)}" if missing else "")


# ---- calendar + follow-ups -------------------------------------------------------------


def marker(item: DatedItem) -> str:
    return f"[github:{item.key}]"


async def sync_items(
    session: AsyncSession,
    items: list[DatedItem],
    m: RepoMap,
    today: dt.date,
    tz: ZoneInfo,
    recorder: ChangeRecorder,
) -> list[str]:
    """Calendar + follow-up for new future items; reminders / closing for the near ones."""
    lines: list[str] = []
    added: list[str] = []
    for item in items:
        if item.day < today:
            continue
        tag = marker(item)
        event_id = await session.scalar(select(Event.id).where(Event.notes.contains(tag)))
        if event_id is None:
            start = dt.datetime.combine(item.day, dt.time(), tzinfo=tz)
            event = Event(
                kind=EventKind.DEADLINE,
                title=item.title[:200],
                start_at=start,
                end_at=start + dt.timedelta(days=1),
                all_day=True,
                notes=f"GitHub: {item.source} {tag}",
            )
            session.add(event)
            await recorder.created(event)
            followup = Followup(
                title=f"{item.title} (GitHub)"[:300],
                check_rule=FollowupCheckRule.ON_DATE,
                check_on=item.day,
                related_event_id=event.id,
                notes=tag,
            )
            session.add(followup)
            await recorder.created(followup)
            added.append(f"{item.title} ({_day(item.day)})")
        if (item.day - today).days > REMIND_DAYS:
            continue
        found = evidence(item, m)
        waiting = await session.scalar(
            select(Followup).where(
                Followup.notes.contains(tag), Followup.status == FollowupStatus.WAITING
            )
        )
        if found is None:
            left = (item.day - today).days
            when = "bugün" if left == 0 else f"{left} gün kaldı"
            lines.append(
                f"Hatırlatma: {item.title}, {_day(item.day)} ({when}); ilgili dosya/PR yok."
            )
        elif waiting is not None:
            before = recorder.before_update(waiting)
            waiting.status = FollowupStatus.DONE
            waiting.notes = f"{waiting.notes} kapandı: {found}"
            await recorder.updated(waiting, before)
            lines.append(f"Hazır: {item.title} ({found}); takip kapandı.")
    if added:
        lines.insert(0, f"Takvime + takibe eklendi: {'; '.join(added)}.")
    return lines


def _day(day: dt.date) -> str:
    months = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
    return f"{day.day} {months[day.month - 1]}"


# ---- the morning job -------------------------------------------------------------------


async def has_map(session: AsyncSession, employee_id: str) -> bool:
    found = await session.scalar(
        select(EmployeeNote.id).where(
            EmployeeNote.employee_id == employee_id, EmployeeNote.content.startswith(MAP_TITLE)
        )
    )
    return found is not None


async def morning(
    session: AsyncSession,
    github: GitHub,
    employee_id: str,
    now: dt.datetime,
    tz: ZoneInfo,
) -> str:
    """The note of one morning (the map first, the first time)."""
    today = now.astimezone(tz).date()
    m = await load_map(github, now)
    parts: list[str] = []
    if not await has_map(session, employee_id):
        parts.append(map_note(m))
    week = await week_status(github, m)
    recorder = ChangeRecorder(session, uuid.uuid4())
    recorder.agent_id = employee_id
    lines = await sync_items(session, await dated_items(github, m, today), m, today, tz, recorder)
    morning_lines = [line for line in (week, *lines) if line]
    if recorder.entries:
        morning_lines.append(f"(Geri almak için değişiklik: {recorder.change_set_id})")
    parts.append("Sabah depo kontrolü:\n" + ("\n".join(morning_lines) or "Yeni bir şey yok."))
    return "\n\n".join(parts)
