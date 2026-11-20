"""Provider-agnostic web search (Tavily or Brave, key in .env). No key: `None`, and the
callers report the integration as pending instead of failing."""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx2

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 15.0
PENDING_NOTE = "Web arama anahtarı bekleniyor (TAVILY_API_KEY ya da BRAVE_API_KEY)."


class SearchError(Exception):
    """The provider answered with an error (bad key, quota, network)."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    @property
    def site(self) -> str:
        return urlparse(self.url).netloc.removeprefix("www.")

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class WebSearch(Protocol):
    name: str

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...


class Tavily:
    name = "tavily"

    def __init__(self, key: str) -> None:
        self._key = key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        data = await _request(
            "POST",
            "https://api.tavily.com/search",
            json={"api_key": self._key, "query": query, "max_results": max_results},
        )
        return [
            SearchResult(
                str(r.get("title", "")), str(r.get("url", "")), str(r.get("content", ""))[:400]
            )
            for r in data.get("results", [])[:max_results]
        ]


class Brave:
    name = "brave"

    def __init__(self, key: str) -> None:
        self._key = key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        data = await _request(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": self._key, "Accept": "application/json"},
        )
        results = data.get("web", {}).get("results", [])
        return [
            SearchResult(
                str(r.get("title", "")), str(r.get("url", "")), str(r.get("description", ""))[:400]
            )
            for r in results[:max_results]
        ]


async def _request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        async with httpx2.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.request(method, url, **kwargs)
    except httpx2.HTTPError as exc:
        raise SearchError(f"web search unreachable: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        raise SearchError(f"web search failed: HTTP {response.status_code}")
    data: dict[str, Any] = response.json()
    return data


def web_search_from(settings: Settings) -> WebSearch | None:
    keys = {
        "tavily": settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else "",
        "brave": settings.brave_api_key.get_secret_value() if settings.brave_api_key else "",
    }
    wanted = settings.web_search_provider.lower()
    order = [wanted] if wanted in keys else ["tavily", "brave"]
    for name in order:
        if keys.get(name):
            return Tavily(keys[name]) if name == "tavily" else Brave(keys[name])
    return None


@lru_cache
def get_web_search() -> WebSearch | None:
    return web_search_from(get_settings())
