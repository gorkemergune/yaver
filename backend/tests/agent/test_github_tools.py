"""Venture's GitHub tools against a fake GitHub API (tests/github_fake.py): read only, the
repo the user names or GITHUB_STARTUP_REPO, "week3'te kim ne yapmış" per member, and a
setup problem said exactly (live: "repoya erişimim yok, aracım yok")."""

import datetime as dt
import uuid
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr

from app.agent.context import ToolContext
from app.agent.tools import REGISTRY, run_tool
from app.agent.tools import github as github_tools
from app.config import Settings
from app.core import config_problems
from app.core.change_log import ChangeRecorder
from app.integrations import github as gh
from tests.agent_fakes import example_team
from tests.github_fake import FakeGitHub

IST = ZoneInfo("Europe/Istanbul")
NOW = dt.datetime(2026, 11, 23, 9, 0, tzinfo=dt.UTC)
TOOLS = (
    "github_list",
    "github_read",
    "github_search",
    "github_commits",
    "github_issues",
    "github_week_summary",
)


def settings(token: str | None = "t", repo: str | None = "acme/startup") -> Settings:
    return Settings(
        _env_file=None,
        github_token=SecretStr(token) if token else None,
        github_startup_repo=repo,
    )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    api = FakeGitHub()
    monkeypatch.setattr(github_tools, "client_factory", api.factory())
    monkeypatch.setattr(github_tools, "get_settings", settings)
    return api


def context() -> ToolContext:
    session = MagicMock()  # the GitHub tools write nothing
    change_set = uuid.uuid4()
    return ToolContext(
        session=session,
        now=NOW,
        tz=IST,
        change_set_id=change_set,
        recorder=ChangeRecorder(session, change_set),
        agent_id="startup",
    )


async def call(name: str, **arguments: Any) -> dict[str, Any]:
    return await run_tool(name, arguments, context())


def test_venture_has_the_tools_and_only_venture() -> None:
    team = example_team()
    venture = team.get("startup")
    assert venture is not None
    assert set(TOOLS) <= {t.name for t in venture.tools}
    assert all(not REGISTRY[name].mutates for name in TOOLS)  # read only
    others = [a for a in team.agents if a.id != "startup"]
    assert not any(t.name in TOOLS for a in others for t in a.tools)


async def test_week_summary_per_member(fake: FakeGitHub) -> None:
    result = await call("github_week_summary", week=3)

    assert result["folder"] == "week3"
    assert "MVP prototipleri" in result["week_readme"]
    members = {m["folder_or_file"]: m for m in result["members"]}
    assert set(members) == {"ali", "zeynep", "mert-rapor", "deniz"}
    assert "recommend" in members["ali"]["readme"]
    assert members["ali"]["commit_authors"] == {"ali-dev (Ali Demir)": 1}
    assert members["deniz"]["readme"].startswith("Kullanıcı segmentasyonu")  # notes.txt
    assert members["deniz"]["commit_authors"] == {"dnz42 (Deniz Kaya)": 1}  # login != name
    assert "Rakip analizi" in members["mert-rapor"]["readme"]
    assert members["zeynep"]["last_commit"] == "2026-11-22 18:00"  # local time
    assert all(method == "GET" for method, _ in fake.requests)


async def test_folders_named_like_a_contributor(fake: FakeGitHub) -> None:
    result = await call("github_week_summary", week=3)
    named = {m["folder_or_file"]: m["named_after_a_contributor"] for m in result["members"]}

    # ali -> ali-dev, zeynep -> zeynepy, mert-rapor -> mertc, deniz -> "Deniz Kaya"
    assert named == {"ali": True, "zeynep": True, "mert-rapor": True, "deniz": True}
    assert "single_author" not in result


async def test_a_one_person_week_folder_is_not_split_into_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real repo (a course's doc/week03: Lab03, Lecture03, examples, all one author):
    the parts are not team members."""
    monkeypatch.setattr(github_tools, "client_factory", FakeGitHub(one_author="solo").factory())
    monkeypatch.setattr(github_tools, "get_settings", settings)

    result = await call("github_week_summary", week=3)

    assert result["single_author"] == "solo"
    assert "not team members" in result["note"]
    assert "invent no members" in result["note"]


async def test_week_without_a_folder_lists_the_weeks(fake: FakeGitHub) -> None:
    result = await call("github_week_summary", week=7)

    assert result["error"] == "no folder for this week"
    assert result["week_folders"] == ["week1", "week2", "week3"]


async def test_listing_a_repo_the_token_cant_see_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github_tools, "client_factory", FakeGitHub(404).factory())
    monkeypatch.setattr(github_tools, "get_settings", settings)

    result = await call("github_list", repo="github/acme/startup")

    assert result["status"] == "github_error"  # not "no such folder"
    assert "acme/startup deposu bulunamadı" in result["problem"]


async def test_list_read_search(fake: FakeGitHub) -> None:
    top = await call("github_list")
    assert top["week_folders"] == {1: "week1", 2: "week2", 3: "week3"}
    assert any(e["name"] == "README.md" and e["type"] == "file" for e in top["entries"])

    read = await call("github_read", path="week3/mert-rapor.md")
    assert "Eventbrite" in read["text"]
    assert read["truncated"] is False
    folder = await call("github_read", path="week3/ali")
    assert folder["error"] == "a folder: list it with github_list"

    found = await call("github_search", query="segment")
    assert {n["path"] for n in found["names"]} == {"week3/deniz/segment.py"}
    assert any(line["path"] == "week3/deniz/notes.txt" for line in found["lines"])


async def test_commits_by_author_and_date(fake: FakeGitHub) -> None:
    by_ali = await call("github_commits", author="ali")
    assert by_ali["count"] == 4
    assert by_ali["by_author"] == {"ali-dev": 4}

    week = await call("github_commits", since="2026-11-21", until="2026-11-22")
    assert [c["message"] for c in week["commits"]] == [
        "segment denemesi",
        "landing page formu",
        "rakip analizi",
        "recommend endpoint",
    ]
    by_name = await call("github_commits", author="Deniz")  # the git name, not the login
    assert by_name["by_author"] == {"dnz42": 1}


async def test_issues_and_pulls(fake: FakeGitHub) -> None:
    result = await call("github_issues")

    assert [i["title"] for i in result["issues"]] == ["Sunum slaytları"]  # the PR is not one
    assert result["pulls"][0]["by"] == "ali-dev"


async def test_a_repo_named_in_the_message_is_used(fake: FakeGitHub) -> None:
    result = await call("github_list", repo="github/gorkemergune/startup")

    assert result["repo"] == "gorkemergune/startup"
    assert fake.requests[0] == ("GET", "/repos/gorkemergune/startup/contents")


@pytest.mark.parametrize(
    ("token", "repo", "named", "expected"),
    [
        (None, "acme/startup", None, "GITHUB_TOKEN yok"),
        ("t", None, None, "GITHUB_STARTUP_REPO ayarlı değil"),
        ("t", "acme/<startup>", None, "GITHUB_STARTUP_REPO geçersiz: 'acme/<startup>'"),
        (None, None, "github/acme/startup", "GITHUB_TOKEN yok"),
    ],
)
async def test_a_missing_setting_is_named(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
    repo: str | None,
    named: str | None,
    expected: str,
) -> None:
    config_problems.clear_source(".env")
    current = settings(token, repo)  # an invalid repo is reported here (UI banner too)
    monkeypatch.setattr(github_tools, "get_settings", lambda: current)
    monkeypatch.setattr(github_tools, "client_factory", FakeGitHub().factory())

    result = await call("github_week_summary", week=3, repo=named)

    assert result["status"] == "not_set_up"
    assert result["problem"].startswith(expected)
    assert "do not say you have no access" in result["note"]
    config_problems.clear_source(".env")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "GITHUB_TOKEN geçersiz ya da süresi dolmuş"),
        (403, "GITHUB_TOKEN'ın acme/startup deposunu okuma yetkisi yok"),
        (404, "acme/startup deposu bulunamadı ya da GITHUB_TOKEN onu göremiyor"),
    ],
)
async def test_github_refusing_is_named(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: str
) -> None:
    monkeypatch.setattr(github_tools, "get_settings", settings)
    monkeypatch.setattr(github_tools, "client_factory", FakeGitHub(status).factory())

    result = await call("github_week_summary", week=3)

    assert result["status"] == "github_error"
    assert result["problem"].startswith(expected)


def test_parse_repo() -> None:
    assert gh.parse_repo("github/gorkemergune/startup") == "gorkemergune/startup"
    assert gh.parse_repo("https://github.com/acme/app.git") == "acme/app"
    assert gh.parse_repo("github.com/acme/app/tree/main/week3") == "acme/app"
    assert gh.parse_repo("acme/<startup>") is None
    assert gh.parse_repo("startup") is None


def test_the_morning_note_says_what_is_missing() -> None:
    assert "Eksik: GITHUB_TOKEN yok" in gh.pending_note(settings(token=None))
    assert "Eksik: GITHUB_STARTUP_REPO ayarlı değil" in gh.pending_note(settings(repo=None))
