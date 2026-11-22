"""A fake GitHub API for Venture's GitHub tools (unit tests and the live regression set):
a made-up startup repository with week1-week3 folders and four members, each handing in a
different way - a folder with a README, a folder with only code (its commits under a login
that is not the name), a single report file. Any owner/name is answered (the user may name
the repo in the message); only GET reaches it."""

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx2

from app.config import Settings
from app.integrations.github import GitHub

FILES: dict[str, str] = {
    "README.md": "# Örnek Lab\n\nKampüs etkinlikleri için yapay zekâ asistanı. Her hafta bir "
    "klasör, her üye kendi klasörüne teslim eder.\n",
    "week1/README.md": "# Week 1\nFikir ve problem tanımı.\n",
    "week1/ali/README.md": "# Ali - problem tanımı\nÖğrenci anketi taslağı.\n",
    "week1/zeynep/README.md": "# Zeynep - persona\nÜç kullanıcı personası.\n",
    "week2/README.md": "# Week 2\nPazar araştırması.\n",
    "week2/ali/README.md": "# Ali - pazar büyüklüğü\nTAM/SAM/SOM hesabı.\n",
    "week2/mert-rapor.md": "# Mert - anket sonuçları\n42 öğrenciyle anket.\n",
    "week3/README.md": "# Week 3 - MVP prototipleri\nBu hafta herkes bir prototip parçası "
    "yapıp toplantıda sunacak.\n",
    "week3/ali/README.md": "# Etkinlik öneri API'si\nFastAPI ile /recommend endpoint'i: "
    "öğrencinin ilgi alanlarına göre 5 etkinlik önerir. Veri: kulüp takvimlerinden 120 "
    "etkinlik.\n",
    "week3/ali/app.py": "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/recommend')"
    "\ndef recommend(): ...\n",
    "week3/zeynep/README.md": "# Landing page\nTanıtım sayfası ve bekleme listesi formu "
    "(HTML + Tailwind). 37 kişi kayıt oldu.\n",
    "week3/zeynep/index.html": "<html><body><h1>Örnek Lab</h1></body></html>\n",
    "week3/mert-rapor.md": "# Rakip analizi\nÜç rakip incelendi: Eventbrite, kulüp "
    "Instagram sayfaları, okul portalı. Fark: kişiye özel öneri.\n",
    "week3/deniz/segment.py": "# k-means ile kullanıcı segmentleri\nK = 4\n",
    "week3/deniz/notes.txt": "Kullanıcı segmentasyonu: anket verisinden 4 segment çıktı "
    "(sosyal, akademik, spor, sanat).\n",
    "toplantilar/2026-11-20.md": "# Toplantı 20 Kasım\n- Week 3 sunumları 24 Kasım akşamı\n",
}
# (path prefix, login, git name, ISO date, message)
COMMITS: list[tuple[str, str, str, str, str]] = [
    ("week3/deniz", "dnz42", "Deniz Kaya", "2026-11-22T18:10:00Z", "segment denemesi"),
    ("week3/zeynep", "zeynepy", "Zeynep Yıldız", "2026-11-22T15:00:00Z", "landing page formu"),
    ("week3/mert-rapor.md", "mertc", "Mert Can", "2026-11-21T20:00:00Z", "rakip analizi"),
    ("week3/ali", "ali-dev", "Ali Demir", "2026-11-21T12:00:00Z", "recommend endpoint"),
    ("week3/README.md", "ali-dev", "Ali Demir", "2026-11-20T09:00:00Z", "week3 klasörü"),
    ("week2/mert-rapor.md", "mertc", "Mert Can", "2026-11-14T10:00:00Z", "anket sonuçları"),
    ("week2/ali", "ali-dev", "Ali Demir", "2026-11-13T10:00:00Z", "pazar büyüklüğü"),
    ("week1/zeynep", "zeynepy", "Zeynep Yıldız", "2026-11-06T10:00:00Z", "personalar"),
    ("week1/ali", "ali-dev", "Ali Demir", "2026-11-06T09:00:00Z", "problem tanımı"),
]
MEMBERS = {"ali": "Ali", "zeynep": "Zeynep", "mert": "Mert", "deniz": "Deniz"}
WEEK3_FACTS = {  # what an answer about week 3 must say per member (any of the words)
    "ali": ("öneri", "recommend", "api"),
    "zeynep": ("landing", "tanıtım", "bekleme"),
    "mert": ("rakip", "rakib", "eventbrite"),  # "rakibi": p -> b before a vowel
    "deniz": ("segment",),
}


def _dirs(files: dict[str, str]) -> set[str]:
    found = set()
    for path in files:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            found.add("/".join(parts[:i]))
    return found


def _b64(text: str) -> dict[str, Any]:
    return {
        "type": "file",
        "encoding": "base64",
        "size": len(text.encode()),
        "content": base64.b64encode(text.encode()).decode(),
    }


def _commit(login: str, name: str, date: str, message: str) -> dict[str, Any]:
    return {
        "sha": f"{abs(hash((login, date))):040x}"[:40],
        "author": {"login": login},
        "commit": {"author": {"name": name, "date": date}, "message": message},
    }


class FakeGitHub:
    """api.github.com for any owner/name; `status` makes every request fail with it."""

    def __init__(
        self,
        status: int | None = None,
        *,
        one_author: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.files = {**FILES, **(extra or {})}  # e.g. an empty member folder (.gitkeep)
        self.one_author = one_author  # every commit by this login (a one-person repo)
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append((request.method, request.url.path))
        if self.status is not None:
            return httpx2.Response(self.status, json={"message": "nope"})
        parts = request.url.path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "repos":
            return httpx2.Response(404, json={})
        rest = "/".join(parts[3:])
        params = request.url.params
        files = self.files
        dirs = _dirs(files)
        if rest == "":
            return self._json({"default_branch": "main", "description": "Örnek Lab"})
        if rest == "git/trees/main":
            tree = [{"path": d, "type": "tree"} for d in sorted(dirs)]
            tree += [{"path": f, "type": "blob"} for f in sorted(files)]
            return self._json({"tree": tree})
        if rest == "readme":
            return self._json(_b64(files["README.md"]))
        if rest == "contents" or rest.startswith("contents/"):
            path = rest.removeprefix("contents").strip("/")
            if path in files:
                return self._json(_b64(files[path]))
            if path == "" or path in dirs:
                prefix = f"{path}/" if path else ""
                names = {
                    p[len(prefix) :].split("/")[0] for p in [*files, *dirs] if p.startswith(prefix)
                }
                return self._json(
                    [
                        {
                            "name": n,
                            "path": prefix + n,
                            "type": "dir" if prefix + n in dirs else "file",
                            "size": len(files.get(prefix + n, "")),
                        }
                        for n in sorted(names)
                        if n
                    ]
                )
            return httpx2.Response(404, json={})
        if rest == "commits":
            path = params.get("path")
            since, until = params.get("since"), params.get("until")
            rows = [
                _commit(self.one_author or login, self.one_author or name, date, message)
                for prefix, login, name, date, message in COMMITS
                if (not path or prefix == path or prefix.startswith(f"{path}/"))
                and (not since or date >= since)
                and (not until or date < until)
            ]
            return self._json(rows)
        if rest == "contributors":
            logins = dict.fromkeys(
                [self.one_author] if self.one_author else [c[1] for c in COMMITS]
            )
            return self._json([{"login": login, "type": "User"} for login in logins])
        if rest == "issues":
            return self._json(
                [
                    {
                        "number": 3,
                        "title": "Sunum slaytları",
                        "state": "open",
                        "user": {"login": "zeynepy"},
                        "assignees": [{"login": "mertc"}],
                        "created_at": "2026-11-20T10:00:00Z",
                    },
                    {"number": 4, "title": "Bir PR", "pull_request": {}, "state": "open"},
                ]
            )
        if rest == "pulls":
            return self._json(
                [
                    {
                        "number": 4,
                        "title": "week3: recommend endpoint",
                        "state": "open",
                        "user": {"login": "ali-dev"},
                        "assignees": [],
                        "created_at": "2026-11-21T12:00:00Z",
                    }
                ]
            )
        if rest == "milestones":
            return self._json([])
        return httpx2.Response(404, json={})

    @staticmethod
    def _json(data: Any) -> httpx2.Response:
        return httpx2.Response(200, content=json.dumps(data).encode())

    def factory(self) -> Callable[..., GitHub | None]:
        """In place of app.integrations.github.get_github (same signature)."""

        def make(settings: Settings | None = None, repo: str | None = None) -> GitHub | None:
            name = repo or (settings.github_startup_repo if settings else None) or "acme/startup"
            return GitHub(
                "token",
                name,
                base_url="https://github.test",
                transport=httpx2.MockTransport(self.handler),
            )

        return make
