"""Venture's morning look at the startup repository, against a fake GitHub API (made-up repo:
week folders, a meeting note, an issue, a milestone, pull requests). Read only."""

import base64
import datetime as dt
import json
import re
import uuid
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.change_log import undo_change_set
from app.db.models import EmployeeNote, Event, Followup
from app.db.models.enums import EventKind, FollowupCheckRule, FollowupStatus
from app.integrations.github import PENDING_NOTE, GitHub, GitHubError, get_github
from app.office.shift_jobs import run_shift_job
from app.office.state import Office
from app.startup import repo as startup
from tests.agent_fakes import NOW
from tests.db.test_office import IST
from tests.db.test_shift_jobs import example_config, notes_of, office  # noqa: F401

REPO = "acme/startup"
MEETING = """# Toplantı 18 Kasım 2026
- 25 Kasım: demo videosu teslim
- 24 Kasım bütçe tablosu
- 28.11.2026 jüri sunumu provası
- 10 Kasım: geçmiş bir iş
Notlar: tarih olmayan satır
"""


def b64(text: str) -> dict[str, str]:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


def tree(*paths: str) -> dict[str, Any]:
    return {
        "tree": [
            {"path": p.rstrip("/"), "type": "tree" if p.endswith("/") else "blob"} for p in paths
        ]
    }


def commit(login: str) -> dict[str, Any]:
    return {"author": {"login": login}, "commit": {"author": {"name": login.title()}}}


class FakeGitHub:
    """Routes like api.github.com; remembers every request (method + path)."""

    def __init__(self, *, pulls: list[dict[str, Any]] | None = None) -> None:
        self.requests: list[tuple[str, str]] = []
        base = f"/repos/{REPO}"
        self.routes: dict[str, Any] = {
            base: {"default_branch": "main", "description": "Kampüs etkinlik asistanı"},
            f"{base}/git/trees/main": tree(
                "README.md",
                "hafta-01/",
                "hafta-01/ali.md",
                "hafta-02/",
                "hafta-02/ali.md",
                "hafta-02/ayse.md",
                "hafta-03/",
                "hafta-03/ayse-rapor.md",
                "toplantilar/",
                "toplantilar/2026-11-18.md",
                "demo/",
                "demo/senaryo.md",
            ),
            f"{base}/readme": b64(
                "# Örnek Girişim\n\n![logo](x.png)\n\nKampüs için yapay zekâ destekli etkinlik "
                "asistanı.\nHer hafta bir teslim.\n\n## Ekip\n"
            ),
            f"{base}/contents/toplantilar/2026-11-18.md": b64(MEETING),
            f"{base}/issues": [
                {"number": 4, "title": "Pitch deck son hali", "body": "Son tarih: 24.11.2026"},
                {"number": 5, "title": "Logo", "body": None},
                {"number": 7, "title": "Bir PR", "body": "", "pull_request": {}},
            ],
            f"{base}/milestones": [
                {"number": 1, "title": "Kuluçka başvurusu", "due_on": "2026-12-05T08:00:00Z"}
            ],
            f"{base}/pulls": pulls
            if pulls is not None
            else [
                {"number": 9, "title": "Demo videosu taslağı", "body": ""},
                {"number": 10, "title": "Deck güncellemesi", "body": "Closes #4"},
            ],
            f"{base}/contributors": [
                {"login": "ali", "type": "User"},
                {"login": "ayse", "type": "User"},
                {"login": "mehmet", "type": "User"},
                {"login": "dependabot[bot]", "type": "Bot"},
            ],
        }

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if path == f"/repos/{REPO}/commits":
            if request.url.params.get("path") == "hafta-03":
                return httpx2.Response(200, json=[commit("ayse")])
            return httpx2.Response(200, json=[commit("ali"), commit("ayse"), commit("ali")])
        if path in self.routes:
            return httpx2.Response(200, content=json.dumps(self.routes[path]).encode())
        return httpx2.Response(404, json={"message": "Not Found"})

    def client(self) -> GitHub:
        return GitHub(
            "token",
            REPO,
            base_url="https://github.test",
            transport=httpx2.MockTransport(self.handler),
        )


async def test_without_a_token_the_integration_is_pending(
    session: AsyncSession,
    office: Office,  # noqa: F811
) -> None:
    off = Settings(_env_file=None, github_token=None, github_startup_repo=None)
    assert get_github(off) is None
    assert get_github(off.model_copy(update={"github_startup_repo": REPO})) is None
    assert get_github(off.model_copy(update={"github_token": SecretStr("t")})) is None
    assert (
        get_github(
            off.model_copy(update={"github_token": SecretStr("t"), "github_startup_repo": REPO})
        )
        is not None
    )

    note = await run_shift_job(
        "shift:startup:github_watch",
        now=NOW,
        settings=off,
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        config=example_config(),
        office=office,
        web=None,
    )

    assert note == PENDING_NOTE
    assert PENDING_NOTE in await notes_of(session, "startup")


async def test_the_first_morning_maps_the_repo_and_fills_the_calendar(
    session: AsyncSession,
    office: Office,  # noqa: F811
) -> None:
    fake = FakeGitHub()
    github = fake.client()

    note = await run_shift_job(
        "shift:startup:github_watch",
        now=NOW,  # Monday 23 November, 10:00 Istanbul
        settings=Settings(_env_file=None),
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        config=example_config(),
        office=office,
        web=None,
        repo=github,
    )
    await github.aclose()

    assert note is not None
    print(note)
    the_map, morning = note.split("\n\nSabah depo kontrolü:\n")
    assert the_map.startswith("GitHub deposu haritası (acme/startup):")
    assert (
        "README: Örnek Girişim - Kampüs için yapay zekâ destekli etkinlik asistanı. "
        "Her hafta bir teslim." in the_map
    )
    assert "Hafta klasörleri: hafta-01, hafta-02, hafta-03 (son: hafta-03, 1 dosya)" in the_map
    assert "Toplantı notları: 1 (toplantilar/2026-11-18.md)" in the_map
    assert "Açık issue: 2 (#4 Pitch deck son hali; #5 Logo)" in the_map  # the PR is not one
    assert "Milestone: Kuluçka başvurusu (2026-12-05)" in the_map
    assert "Son 7 gün: 3 commit (ali, ayse)" in the_map
    assert "Ekip (katkı verenler): ali, ayse, mehmet" in the_map  # no bots

    lines = morning.splitlines()
    assert lines[0] == "Hafta 3 (hafta-03/, 1 dosya): teslim eden ayse; henüz yok: ali, mehmet"
    assert lines[1].startswith("Takvime + takibe eklendi: ")
    for added in (
        "bütçe tablosu (24 Kas)",
        "#4 Pitch deck son hali (24 Kas)",
        "demo videosu teslim (25 Kas)",
        "jüri sunumu provası (28 Kas)",
        "Kuluçka başvurusu (milestone) (5 Ara)",
    ):
        assert added in lines[1]
    assert "geçmiş bir iş" not in morning  # 10 November is past
    assert "Hatırlatma: bütçe tablosu, 24 Kas (1 gün kaldı); ilgili dosya/PR yok." in lines
    assert "Hazır: #4 Pitch deck son hali (PR #10); takip kapandı." in lines
    assert "Hazır: demo videosu teslim (PR #9); takip kapandı." in lines
    assert not any("jüri" in line for line in lines if line.startswith(("Hatırlatma", "Hazır")))
    assert re.search(r"\(Geri almak için değişiklik: [0-9a-f-]{36}\)$", morning)

    events = (await session.scalars(select(Event))).all()
    first_day = {
        (e.title, e.kind, e.all_day)
        for e in events
        if e.start_at.astimezone(IST).date() == dt.date(2026, 11, 24)
    }
    assert first_day == {
        ("bütçe tablosu", EventKind.DEADLINE, True),
        ("#4 Pitch deck son hali", EventKind.DEADLINE, True),
    }
    followups = (await session.scalars(select(Followup).order_by(Followup.id))).all()
    assert len(followups) == 5
    assert all(f.check_rule is FollowupCheckRule.ON_DATE for f in followups)
    statuses = {f.title: f.status for f in followups}
    assert statuses["demo videosu teslim (GitHub)"] is FollowupStatus.DONE
    assert statuses["bütçe tablosu (GitHub)"] is FollowupStatus.WAITING

    # read only: nothing but GET left the client
    assert {method for method, _ in fake.requests} == {"GET"}


async def test_the_next_morning_adds_nothing_twice_and_skips_the_map(
    session: AsyncSession,
    office: Office,  # noqa: F811 - employees exist (notebook)
) -> None:
    fake = FakeGitHub()
    github = fake.client()
    session.add(
        EmployeeNote(employee_id="startup", content=f"{startup.MAP_TITLE} (x): ...", created_at=NOW)
    )
    await session.flush()
    first = await startup.morning(session, github, "startup", NOW, IST)

    second = await startup.morning(session, github, "startup", NOW + dt.timedelta(hours=1), IST)
    await github.aclose()

    assert not first.startswith(startup.MAP_TITLE)
    assert "Takvime + takibe eklendi" in first
    assert "Takvime + takibe eklendi" not in second
    assert "Geri almak için" not in second  # nothing changed
    assert "Hatırlatma: bütçe tablosu" in second  # still nothing for it
    assert len((await session.scalars(select(Event))).all()) == 5


async def test_a_new_pull_request_closes_the_follow_up_later(session: AsyncSession) -> None:
    fake = FakeGitHub(pulls=[])
    github = fake.client()
    first = await startup.morning(session, github, "startup", NOW, IST)
    assert "Hatırlatma: demo videosu teslim, 25 Kas (2 gün kaldı); ilgili dosya/PR yok." in first

    fake.routes[f"/repos/{REPO}/pulls"] = [{"number": 12, "title": "Demo videosu v1", "body": ""}]
    second = await startup.morning(session, github, "startup", NOW + dt.timedelta(days=1), IST)
    await github.aclose()

    assert "Hazır: demo videosu teslim (PR #12); takip kapandı." in second
    followup = await session.scalar(
        select(Followup).where(Followup.title.startswith("demo videosu"))
    )
    assert followup is not None
    assert followup.status is FollowupStatus.DONE


async def test_a_file_in_the_repo_also_counts(session: AsyncSession) -> None:
    fake = FakeGitHub(pulls=[])
    fake.routes[f"/repos/{REPO}/git/trees/main"]["tree"].append(
        {"path": "finans/butce-tablosu.xlsx", "type": "blob"}
    )
    github = fake.client()

    note = await startup.morning(session, github, "startup", NOW, IST)
    await github.aclose()

    assert "Hazır: bütçe tablosu (finans/butce-tablosu.xlsx); takip kapandı." in note


async def test_the_mornings_changes_are_undoable(session: AsyncSession) -> None:
    github = FakeGitHub().client()
    note = await startup.morning(session, github, "startup", NOW, IST)
    await github.aclose()
    change_set = re.search(r"değişiklik: ([0-9a-f-]{36})", note)
    assert change_set is not None

    await undo_change_set(session, uuid.UUID(change_set.group(1)), NOW)

    assert (await session.scalars(select(Event))).all() == []
    assert (await session.scalars(select(Followup))).all() == []


async def test_the_client_refuses_anything_but_reads() -> None:
    github = FakeGitHub().client()
    with pytest.raises(GitHubError, match="read-only"):
        await github._client.post(f"/repos/{REPO}/issues", json={"title": "x"})
    with pytest.raises(GitHubError, match="read-only"):
        await github._client.delete(f"/repos/{REPO}")
    await github.aclose()


async def test_a_refused_token_is_a_note_not_a_crash(
    session: AsyncSession,
    office: Office,  # noqa: F811
) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"message": "Bad credentials"})

    github = GitHub(
        "bad", REPO, base_url="https://github.test", transport=httpx2.MockTransport(refuse)
    )
    note = await run_shift_job(
        "shift:startup:github_watch",
        now=NOW,
        settings=Settings(_env_file=None),
        sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),
        config=example_config(),
        office=office,
        web=None,
        repo=github,
    )
    await github.aclose()

    assert note == "GitHub deposuna bakılamadı: GitHub refused the token (401)"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- 25 Kasım: demo videosu teslim", (dt.date(2026, 11, 25), "demo videosu teslim")),
        ("* [ ] 3 Ocak final raporu", (dt.date(2027, 1, 3), "final raporu")),  # next year
        ("Sunum 2026-12-01", (dt.date(2026, 12, 1), "Sunum")),
        ("1) 05.12.2026 - jüri", (dt.date(2026, 12, 5), "jüri")),
        ("31 Şubat bir şey", None),
        ("tarih yok", None),
    ],
)
def test_dated_lines(line: str, expected: tuple[dt.date, str] | None) -> None:
    items = startup.items_from_text(line, "not", "note:x", dt.date(2026, 11, 23))

    assert ((items[0].day, items[0].title) if items else None) == expected
