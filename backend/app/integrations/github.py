"""The startup's GitHub repository for Venture, READ ONLY.

Only GET requests leave this module (`_get` is the single way out, and the transport
refuses any other method), so a token with write rights still cannot change anything.
Without GITHUB_TOKEN + a repository (GITHUB_STARTUP_REPO or one the user names) there is
no client: Venture notes that the integration is pending.
"""

import base64
import datetime as dt
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx2

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT_SECONDS = 20
PER_PAGE = 100
PENDING_NOTE = (
    "GitHub entegrasyonu bekliyor: GITHUB_TOKEN ve GITHUB_STARTUP_REPO (.env) girilince "
    "startup deposunu haritalayıp her sabah teslimlere bakacağım."
)
NO_TOKEN = (
    "GITHUB_TOKEN yok (.env): GitHub'da yalnız bu depoyu okuyabilen bir fine-grained token "
    "oluşturup GITHUB_TOKEN'a yazmak gerekiyor."
)
NO_REPO = "GITHUB_STARTUP_REPO ayarlı değil (.env, owner/name biçiminde, ör. acme/startup)."


class GitHubError(Exception):
    """A GitHub failure, worded for the user (Turkish): which setting or what went wrong."""


def parse_repo(text: str | None) -> str | None:
    """'owner/name' from what a user or .env writes: acme/startup, github.com/acme/startup,
    https://github.com/acme/startup.git, "github/acme/startup"."""
    if not text:
        return None
    value = text.strip().strip("<>").strip()
    value = re.sub(r"^(?:https?://)?(?:www\.)?(?:github\.com|github)/", "", value, flags=re.I)
    parts = [p for p in value.removesuffix(".git").split("/") if p]
    if len(parts) < 2:
        return None
    repo = f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return repo if re.fullmatch(r"[\w.-]+/[\w.-]+", repo) else None


def setup_problem(settings: Settings | None = None, repo: str | None = None) -> str | None:
    """What keeps the GitHub tools from working, in one Turkish sentence; None = set up.
    `repo`: a repository the user named (it stands in for GITHUB_STARTUP_REPO)."""
    settings = settings or get_settings()
    if not (settings.github_token and settings.github_token.get_secret_value().strip()):
        return NO_TOKEN
    if repo or settings.github_startup_repo:
        return None
    return NO_REPO


class ReadOnlyTransport(httpx2.AsyncBaseTransport):
    """Wraps the real transport; anything but GET/HEAD is refused before it leaves."""

    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method not in ("GET", "HEAD"):
            raise GitHubError(f"read-only: {request.method} {request.url.path} refused")
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


@dataclass(frozen=True, slots=True)
class RepoEntry:
    path: str
    kind: str  # blob | tree


class GitHub:
    def __init__(
        self,
        token: str,
        repo: str,
        *,
        base_url: str = API,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.repo = repo
        self._client = httpx2.AsyncClient(
            base_url=base_url,
            timeout=TIMEOUT_SECONDS,
            transport=ReadOnlyTransport(transport or httpx2.AsyncHTTPTransport()),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "yaver-assistant",
            },
        )
        self._default_branch: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str, /, **params: Any) -> Any:
        try:
            response = await self._client.get(url, params=params or None)
        except httpx2.HTTPError as exc:
            raise GitHubError(f"GitHub unreachable: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            raise GitHubError(f"GitHub refused the token ({response.status_code})")
        if response.status_code >= 400:
            raise GitHubError(f"GitHub error {response.status_code}")
        return response.json()

    async def info(self) -> dict[str, Any]:
        data = await self._get(f"/repos/{self.repo}")
        if data is None:
            raise GitHubError(f"repository {self.repo} not found (or the token can't see it)")
        self._default_branch = data.get("default_branch") or "main"
        return dict(data)

    async def tree(self) -> list[RepoEntry]:
        if self._default_branch is None:
            await self.info()
        data = await self._get(f"/repos/{self.repo}/git/trees/{self._default_branch}", recursive=1)
        return [
            RepoEntry(item["path"], item["type"])
            for item in (data or {}).get("tree", [])
            if item.get("type") in ("blob", "tree")
        ]

    async def contents(self, path: str = "") -> Any:
        """A folder: list of {name, path, type (file|dir), size}; a file: its dict (base64)."""
        return await self._get(f"/repos/{self.repo}/contents/{path.strip('/')}".rstrip("/"))

    async def file_bytes(self, path: str) -> tuple[bytes | None, int]:
        """(content, size); content None for a folder, a missing file or one over 1 MB (the
        contents API leaves those empty)."""
        data = await self.contents(path)
        if not isinstance(data, dict):
            return None, 0
        size = int(data.get("size") or 0)
        if data.get("encoding") != "base64" or (size and not data.get("content")):
            return None, size
        return base64.b64decode(data.get("content", "")), size

    async def text(self, path: str) -> str | None:
        data = await self._get(f"/repos/{self.repo}/contents/{path}")
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")

    async def readme(self) -> str | None:
        data = await self._get(f"/repos/{self.repo}/readme")
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")

    async def issues(self, state: str = "open") -> list[dict[str, Any]]:
        """Issues only (the API lists pull requests here too)."""
        data = await self._get(f"/repos/{self.repo}/issues", state=state, per_page=PER_PAGE)
        return [i for i in data or [] if "pull_request" not in i]

    async def pulls(self, state: str = "all") -> list[dict[str, Any]]:
        return list(
            await self._get(f"/repos/{self.repo}/pulls", state=state, per_page=PER_PAGE) or []
        )

    async def milestones(self, state: str = "open") -> list[dict[str, Any]]:
        return list(
            await self._get(f"/repos/{self.repo}/milestones", state=state, per_page=PER_PAGE) or []
        )

    async def commits(
        self,
        *,
        since: dt.datetime | None = None,
        until: dt.datetime | None = None,
        path: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": PER_PAGE}
        if since is not None:
            params["since"] = since.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if until is not None:
            params["until"] = until.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if path is not None:
            params["path"] = path
        return list(await self._get(f"/repos/{self.repo}/commits", **params) or [])

    async def contributors(self) -> list[str]:
        data = await self._get(f"/repos/{self.repo}/contributors", per_page=PER_PAGE)
        return [c["login"] for c in data or [] if c.get("type") != "Bot" and c.get("login")]


def get_github(settings: Settings | None = None, repo: str | None = None) -> GitHub | None:
    """The client for `repo` (one the user named) or GITHUB_STARTUP_REPO; None when the token
    or both repositories are missing (`setup_problem` says which)."""
    settings = settings or get_settings()
    token = settings.github_token.get_secret_value().strip() if settings.github_token else ""
    repo = repo or settings.github_startup_repo
    if not token or not repo:
        return None
    return GitHub(token, repo)


def commit_name(commit: dict[str, Any]) -> str:
    """The git author name (what the member wrote in git config), '' if none."""
    return str(((commit.get("commit") or {}).get("author") or {}).get("name") or "")


def commit_time(commit: dict[str, Any]) -> dt.datetime | None:
    raw = ((commit.get("commit") or {}).get("author") or {}).get("date")
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None


def commit_author(commit: dict[str, Any]) -> str:
    """GitHub login if the commit is linked to an account, else the git author name."""
    author = commit.get("author") or {}
    if author.get("login"):
        return str(author["login"])
    return str(((commit.get("commit") or {}).get("author") or {}).get("name") or "?")
