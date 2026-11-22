"""Venture's read-only look into the startup's GitHub repository, in chat: list a folder,
read a file (markdown, text, code, a PDF's text), search names and contents, commits by
author and date, issues and pull requests, and "kim ne yapmış" for a week folder.

Only GET requests reach GitHub (app.integrations.github). The repository is the one the
user names ("github/acme/startup", "github.com/acme/startup") or GITHUB_STARTUP_REPO.
When something is not set up the tool says exactly what (GITHUB_TOKEN yok,
GITHUB_STARTUP_REPO geçersiz, the token can't read the repo), never "erişimim yok".
"""

import asyncio
import datetime as dt
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.context import ToolContext
from app.agent.tools import ToolResult, tool
from app.config import get_settings
from app.integrations import github as gh
from app.rag.pdf import page_texts
from app.startup.repo import WEEK_DIR, fold

MAX_CHARS = 6000  # of a file read into the conversation
MAX_SEARCH_FILES = 40  # text files read for a content search
MAX_GROUPS = 12  # members / projects summarised in a week folder
TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml",
    ".yml", ".toml", ".html", ".css", ".java", ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".kt",
    ".swift", ".sql", ".sh", ".csv", ".ipynb",
}  # fmt: skip
NOT_SET_UP = (
    "tell the user exactly this problem in one sentence (it is a setting to fix), "
    "do not say you have no access in general and do not ask them for the repo again"
)

# Tests put a fake GitHub here (same signature as gh.get_github).
client_factory: Callable[..., gh.GitHub | None] = gh.get_github

REPO = Field(
    None,
    description="owner/name if the user named a repository (github/owner/name, a github.com "
    "link); omit for the startup repository",
)


async def _with_github(
    ctx: ToolContext, repo: str | None, work: Callable[[gh.GitHub], Awaitable[ToolResult]]
) -> ToolResult:
    named = gh.parse_repo(repo) if repo else None
    settings = get_settings()
    problem = gh.setup_problem(settings, named)
    client = None if problem else client_factory(settings, named)
    if client is None:
        return {
            "status": "not_set_up",
            "problem": problem or gh.NO_REPO,
            "note": NOT_SET_UP,
        }
    try:
        result = await work(client)
    except gh.GitHubError as exc:
        return {
            "status": "github_error",
            "repo": client.repo,
            "problem": str(exc),
            "note": NOT_SET_UP,
        }
    finally:
        await client.aclose()
    return {"repo": client.repo, **result}


def _date(moment: dt.datetime | None, tz: dt.tzinfo) -> str | None:
    return moment.astimezone(tz).strftime("%Y-%m-%d %H:%M") if moment else None


def _commit(commit: dict[str, Any], tz: dt.tzinfo) -> dict[str, Any]:
    message = str((commit.get("commit") or {}).get("message") or "").strip().splitlines()
    return {
        "sha": str(commit.get("sha") or "")[:7],
        "date": _date(gh.commit_time(commit), tz),
        "author": gh.commit_author(commit),
        "name": gh.commit_name(commit),
        "message": message[0][:160] if message else "",
    }


# ---- list a folder -------------------------------------------------------------------


class ListArgs(BaseModel):
    path: str = Field("", max_length=300, description="folder in the repo; empty = the top")
    repo: str | None = REPO


@tool(
    "github_list",
    "List a folder of the startup's GitHub repository (read only): files and subfolders. "
    "The top level also shows the week folders (week3, hafta-03).",
    ListArgs,
)
async def github_list(args: ListArgs, ctx: ToolContext) -> ToolResult:
    async def work(client: gh.GitHub) -> ToolResult:
        data = await client.contents(args.path)
        if data is None:
            await client.info()  # a missing / unseen repository says so (GitHubError)
            return {"path": args.path, "error": "no such folder"}
        if isinstance(data, dict):  # a file: say so, the model reads it with github_read
            return {"path": args.path, "is_file": True, "size": data.get("size")}
        entries = [
            {"name": e.get("name"), "type": e.get("type"), "size": e.get("size")}
            for e in data[:200]
        ]
        result: dict[str, Any] = {"path": args.path or "/", "entries": entries}
        weeks = {
            int(m.group(1)): e["name"]
            for e in entries
            if e["type"] == "dir" and (m := WEEK_DIR.match(str(e["name"])))
        }
        if weeks:
            result["week_folders"] = dict(sorted(weeks.items()))
        return result

    return await _with_github(ctx, args.repo, work)


# ---- read a file -----------------------------------------------------------------------


class ReadArgs(BaseModel):
    path: str = Field(min_length=1, max_length=300, description="file path in the repo")
    repo: str | None = REPO


def _as_text(path: str, data: bytes) -> str | None:
    if path.lower().endswith(".pdf"):
        return "\n\n".join(t for t in page_texts(data) if t.strip())
    if b"\x00" in data[:4000]:
        return None  # an image, an archive
    return data.decode("utf-8", errors="replace")


@tool(
    "github_read",
    "Read one file of the startup's GitHub repository (read only): markdown, text, code, or "
    "the text of a PDF. Long files are cut.",
    ReadArgs,
)
async def github_read(args: ReadArgs, ctx: ToolContext) -> ToolResult:
    async def work(client: gh.GitHub) -> ToolResult:
        data, size = await client.file_bytes(args.path)
        if data is None:
            if size:
                return {"path": args.path, "error": f"too large to read here ({size} bytes)"}
            listing = await client.contents(args.path)
            if isinstance(listing, list):
                return {"path": args.path, "error": "a folder: list it with github_list"}
            return {"path": args.path, "error": "no such file"}
        text = await asyncio.to_thread(_as_text, args.path, data)
        if text is None:
            return {"path": args.path, "binary": True, "size": size}
        return {
            "path": args.path,
            "text": text[:MAX_CHARS],
            "truncated": len(text) > MAX_CHARS,
        }

    return await _with_github(ctx, args.repo, work)


# ---- search ---------------------------------------------------------------------------


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=100, description="a name or words to look for")
    path: str = Field("", max_length=300, description="only under this folder; empty = all")
    repo: str | None = REPO


@tool(
    "github_search",
    "Search the startup's GitHub repository (read only): file and folder names, and the "
    "lines of its text files that contain the words.",
    SearchArgs,
)
async def github_search(args: SearchArgs, ctx: ToolContext) -> ToolResult:
    words = fold(args.query).split()
    prefix = args.path.strip("/")

    async def work(client: gh.GitHub) -> ToolResult:
        entries = [
            e
            for e in await client.tree()
            if not prefix or e.path == prefix or e.path.startswith(f"{prefix}/")
        ]
        names = [
            {"path": e.path, "type": "dir" if e.kind == "tree" else "file"}
            for e in entries
            if all(w in fold(e.path) for w in words)
        ]
        texts = [
            e.path
            for e in entries
            if e.kind == "blob" and PurePosixPath(e.path).suffix.lower() in TEXT_SUFFIXES
        ][:MAX_SEARCH_FILES]
        lines: list[dict[str, Any]] = []
        for path in texts:
            body = await client.text(path)
            for number, line in enumerate((body or "").splitlines(), start=1):
                if all(w in fold(line) for w in words):
                    lines.append({"path": path, "line": number, "text": line.strip()[:200]})
            if len(lines) >= 30:
                break
        return {
            "query": args.query,
            "names": names[:30],
            "lines": lines[:30],
            "text_files_searched": len(texts),
        }

    return await _with_github(ctx, args.repo, work)


# ---- commits ----------------------------------------------------------------------------


class CommitsArgs(BaseModel):
    author: str | None = Field(None, max_length=80, description="GitHub login or name")
    since: dt.date | None = Field(None, description="YYYY-MM-DD, from this day")
    until: dt.date | None = Field(None, description="YYYY-MM-DD, up to and with this day")
    path: str | None = Field(None, max_length=300, description="only commits touching this")
    repo: str | None = REPO


@tool(
    "github_commits",
    "Commits of the startup's GitHub repository (read only), newest first: date, author, "
    "message; filter by author, dates (YYYY-MM-DD) and path. Counts per author too.",
    CommitsArgs,
)
async def github_commits(args: CommitsArgs, ctx: ToolContext) -> ToolResult:
    def start(day: dt.date) -> dt.datetime:
        return dt.datetime.combine(day, dt.time(), tzinfo=ctx.tz)

    async def work(client: gh.GitHub) -> ToolResult:
        commits = await client.commits(
            since=start(args.since) if args.since else None,
            until=start(args.until + dt.timedelta(days=1)) if args.until else None,
            path=args.path or None,
        )
        rows = [_commit(c, ctx.tz) for c in commits]
        if args.author:
            who = fold(args.author)
            rows = [r for r in rows if who in fold(r["author"]) or who in fold(r["name"])]
        return {
            "count": len(rows),
            "by_author": dict(Counter(r["author"] for r in rows).most_common()),
            "commits": rows[:40],
        }

    return await _with_github(ctx, args.repo, work)


# ---- issues / pull requests -----------------------------------------------------------


class IssuesArgs(BaseModel):
    kind: Literal["issues", "pulls", "both"] = "both"
    state: Literal["open", "closed", "all"] = "open"
    repo: str | None = REPO


@tool(
    "github_issues",
    "Issues and pull requests of the startup's GitHub repository (read only): number, "
    "title, state, who opened it, assignees, date.",
    IssuesArgs,
)
async def github_issues(args: IssuesArgs, ctx: ToolContext) -> ToolResult:
    def row(item: dict[str, Any]) -> dict[str, Any]:
        created = item.get("created_at")
        return {
            "number": item.get("number"),
            "title": item.get("title"),
            "state": item.get("state"),
            "by": (item.get("user") or {}).get("login"),
            "assignees": [a.get("login") for a in item.get("assignees") or []],
            "created": str(created)[:10] if created else None,
        }

    async def work(client: gh.GitHub) -> ToolResult:
        result: dict[str, Any] = {"state": args.state}
        if args.kind in ("issues", "both"):
            result["issues"] = [row(i) for i in (await client.issues(args.state))[:40]]
        if args.kind in ("pulls", "both"):
            result["pulls"] = [row(p) for p in (await client.pulls(args.state))[:40]]
        return result

    return await _with_github(ctx, args.repo, work)


# ---- a week folder: who did what ---------------------------------------------------------


class WeekArgs(BaseModel):
    week: int | None = Field(None, ge=0, le=60, description="the N of weekN; omit for the latest")
    repo: str | None = REPO


def _group(rel: str, is_dir: bool) -> str:
    """'ali/app.py' -> 'ali'; 'ayse-rapor.md' -> 'ayse-rapor' (a member's file)."""
    head = rel.split("/", 1)[0]
    return head if is_dir or "/" in rel else PurePosixPath(head).stem


def _named_after(name: str, people: set[str], rows: list[dict[str, Any]]) -> bool:
    key = fold(re.split(r"[-_ .]", name)[0])
    names = people | {fold(r["author"]) for r in rows}
    names |= {fold(part) for r in rows for part in r["name"].split()}
    return len(key) >= 3 and any(key in n or n in key for n in names if len(n) >= 3)


async def _text_of(client: gh.GitHub, folder: str, files: list[str]) -> str | None:
    """What a member's folder says: its README, else an .md / .txt, else a PDF's first page
    (members hand in slides and reports too)."""
    by_suffix = [
        next((f for f in files if PurePosixPath(f).name.lower().startswith("readme")), None),
        next((f for f in files if PurePosixPath(f).suffix.lower() in (".md", ".txt")), None),
    ]
    for name in by_suffix:
        if name:
            return _excerpt(await client.text(f"{folder}/{name}"))
    pdf = next((f for f in files if f.lower().endswith(".pdf")), None)
    if pdf is None:
        return None
    data, _size = await client.file_bytes(f"{folder}/{pdf}")
    if data is None:
        return None
    pages = await asyncio.to_thread(page_texts, data)
    return _excerpt(f"({pdf}) " + " ".join(pages[:2]))


def _excerpt(text: str | None, limit: int = 700) -> str | None:
    if not text:
        return None
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text[:limit] + ("…" if len(text) > limit else "")


@tool(
    "github_week_summary",
    "Who did what in a week folder of the startup's repository (week3, hafta-03; read "
    "only): per member / project subfolder or file its files, commit authors and messages "
    "and README text. Use it for 'weekN'te kim ne yapmış', a presentation or meeting draft.",
    WeekArgs,
)
async def github_week_summary(args: WeekArgs, ctx: ToolContext) -> ToolResult:
    async def work(client: gh.GitHub) -> ToolResult:
        return await summarize_week(client, args.week, ctx.tz)

    return await _with_github(ctx, args.repo, work)


PLACEHOLDERS = {".gitkeep", ".keep", ".gitignore"}  # an "empty" member folder has only these


def _week_folders(entries: list[gh.RepoEntry]) -> dict[int, str]:
    """week number -> its folder (the shallowest when two match)."""
    found: dict[int, str] = {}
    for path in sorted(
        (e.path for e in entries if e.kind == "tree"), key=lambda p: (p.count("/"), p)
    ):
        match = WEEK_DIR.match(path.rsplit("/", 1)[-1])
        if match:
            found.setdefault(int(match.group(1)), path)
    return found


def _groups(entries: list[gh.RepoEntry], folder: str) -> tuple[dict[str, list[str]], str | None]:
    """A week folder's member / project groups (real files only) and its own README."""
    groups: dict[str, list[str]] = {}
    week_readme = None
    for entry in entries:
        if not entry.path.startswith(f"{folder}/"):
            continue
        rel = entry.path[len(folder) + 1 :]
        if "/" not in rel and entry.kind == "blob" and rel.lower().startswith("readme"):
            week_readme = entry.path
            continue
        files = groups.setdefault(_group(rel, entry.kind == "tree"), [])
        if entry.kind == "blob" and PurePosixPath(rel).name not in PLACEHOLDERS:
            files.append(rel)
    return groups, week_readme


async def summarize_week(client: gh.GitHub, week: int | None, tz: dt.tzinfo) -> dict[str, Any]:
    """Who did what in week `week` (None: the latest week folder): per member / project its
    files, commit authors, last commit, messages, README; empty folders and the members of
    the week before with no folder this week. Read only. Used by github_week_summary and by
    Venture's meeting preparation (app.jobs.meeting_prep)."""
    entries = await client.tree()
    weeks = _week_folders(entries)
    if week is None and weeks:
        week = max(weeks)
    if week is None or week not in weeks:
        return {
            "week": week,
            "error": "no folder for this week",
            "week_folders": sorted(weeks.values()),
        }
    folder = weeks[week]
    groups, week_readme = _groups(entries, folder)
    contributors = await client.contributors()
    people = {fold(c) for c in contributors}
    members = []
    everyone: set[str] = set()
    for name, files in list(groups.items())[:MAX_GROUPS]:
        if not files:
            members.append({"folder_or_file": name, "empty": True})
            continue
        target = f"{folder}/{name}" if any("/" in f for f in files) else f"{folder}/{files[0]}"
        rows = [_commit(c, tz) for c in await client.commits(path=target)]
        everyone |= {r["author"] for r in rows}
        members.append(
            {
                "folder_or_file": name,
                # the folder / file is named like someone who commits to the repo
                "named_after_a_contributor": _named_after(name, people, rows),
                "files": files[:15],
                "commit_authors": dict(
                    Counter(
                        f"{r['author']} ({r['name']})" if r["name"] else r["author"] for r in rows
                    ).most_common()
                ),
                "last_commit": rows[0]["date"] if rows else None,
                "commit_messages": [r["message"] for r in rows[:5]],
                "readme": await _text_of(client, folder, files),
            }
        )
    earlier = [n for n in weeks if n < week]
    missing: list[str] = []
    if earlier:
        before, _ = _groups(entries, weeks[max(earlier)])
        missing = [name for name, files in before.items() if files and name not in groups]
    result: dict[str, Any] = {
        "week": week,
        "folder": folder,
        "week_readme": _excerpt(await client.text(week_readme)) if week_readme else None,
        "members": members,
        "empty_folders": [m["folder_or_file"] for m in members if m.get("empty")],
        "no_folder_this_week": missing,  # handed in the week before, nothing this week
        "contributors": contributors,
        "note": "one short paragraph per member: who (folder / file name and commit "
        "authors), what (README, files, commit messages); say whose folder is empty; add "
        "nothing that is not here",
    }
    if len(everyone) == 1 and len([m for m in members if not m.get("empty")]) > 1:
        # a real repo (a course's doc/week03): Lab03, Lecture03, examples - all by one
        # person. These are parts of the week, not members: say so, don't invent people.
        result["single_author"] = next(iter(everyone))
        result["note"] = (
            f"every file of this week is by one person ({result['single_author']}): the "
            "folders / files are parts or topics, not team members. Say that the folder "
            "has no per-member hand-ins and summarise the parts; invent no members"
        )
    return result
