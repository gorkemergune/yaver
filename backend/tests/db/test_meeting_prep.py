"""Tonight's startup meeting: "bugün akşam NEXA toplantısı var" -> Chrono adds the event,
linked to Venture (events.owner_id); an hour before it Venture writes the latest week's
presentation draft per member and whose folder is empty (app.jobs.meeting_prep)."""

import datetime as dt

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.change_log import undo_change_set
from app.db.models import Event, Message
from app.db.models.enums import EventKind
from app.jobs import meeting_prep
from app.llm.types import LLMRequest, LLMResponse
from app.startup import meeting
from tests.agent_fakes import NOW, ScriptedLLM, call, coordinator, last_result, route_as, say
from tests.github_fake import FakeGitHub

TEXT = "bugün akşam NEXA toplantısı var"
EVENING = dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.UTC)  # 19:00 Istanbul, Monday


@pytest.fixture
def nexa(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user's agents.yaml: Venture's domain names "Nexa Lab" (no keywords set)."""
    monkeypatch.setattr(
        meeting,
        "team_names",
        lambda: ("startup", meeting.startup_names([], "Startup - Nexa Lab işleri, rakipler")),
    )


def settings(**extra: object) -> Settings:
    values: dict[str, object] = {
        "github_token": SecretStr("t"),
        "github_startup_repo": "acme/startup",
        **extra,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_names_from_the_area_text() -> None:
    assert meeting.names_in("Startup - Nexa Lab işleri, haftalık hedefler, GitHub deposu") == [
        "Nexa Lab"
    ]
    assert meeting.names_in("Startup işleri - girişimin haftalık hedefleri") == []
    names = ["Nexa Lab"]
    assert meeting.about_the_startup("bugün akşam NEXA toplantısı", names)
    assert meeting.about_the_startup("Nexa Lab demo günü", names)
    assert meeting.about_the_startup("week3 sunumları", [])  # a week folder: the startup's
    assert not meeting.about_the_startup("EE211 lab toplantısı", names)  # "Lab" alone is not it
    assert not meeting.about_the_startup("Iceberg toplantısı", names)


async def test_chrono_adds_it_linked_to_venture(session: AsyncSession, nexa: None) -> None:
    llm = ScriptedLLM()
    llm.add("intent", route_as(("event", TEXT)))
    seen: dict[str, object] = {}

    def tells(request: LLMRequest) -> LLMResponse:
        seen.update(last_result(request))
        return say("Bu akşam 19:00'a NEXA toplantısını ekledim; Venture 1 saat önce hazırlar.")

    llm.add(
        "agenda",
        call("resolve_date", expression="bugün akşam", direction="future"),
        call(
            "add_event", kind="meeting", title="NEXA toplantısı", date="2026-11-23",
            start_time="19:00",
        ),
        tells,
    )  # fmt: skip
    llm.add("yaver", say("Chrono: bu akşam 19:00 NEXA toplantısı eklendi."))

    reply = await coordinator(llm).handle(session, TEXT, now=NOW)

    [event] = (await session.scalars(select(Event))).all()
    assert (event.title, event.kind, event.owner_id) == (
        "NEXA toplantısı",
        EventKind.MEETING,
        "startup",
    )
    linked = seen["linked_to"]
    assert isinstance(linked, dict)
    assert linked["employee"] == "startup"
    assert linked["tell_user"].startswith("Venture toplantıdan 1 saat önce")
    # "Geri al" takes the event (and its link) away
    assert reply.change_set_id is not None
    await undo_change_set(session, reply.change_set_id, NOW)
    assert (await session.scalars(select(Event))).all() == []
    llm.assert_done()


async def test_an_ordinary_meeting_is_not_linked(session: AsyncSession, nexa: None) -> None:
    llm = ScriptedLLM()
    llm.add("intent", route_as(("event", "perşembe 15te iceberg toplantısı")))
    llm.add(
        "agenda",
        call("add_event", kind="meeting", title="Iceberg toplantısı", date="2026-11-26",
             start_time="15:00"),
        say("Eklendi."),
    )  # fmt: skip
    llm.add("yaver", say("Eklendi."))

    await coordinator(llm).handle(session, "perşembe 15te iceberg toplantısı", now=NOW)

    [event] = (await session.scalars(select(Event))).all()
    assert event.owner_id is None


async def linked_meeting(session: AsyncSession, start: dt.datetime) -> Event:
    event = Event(
        kind=EventKind.MEETING, title="NEXA toplantısı", start_at=start, owner_id="startup"
    )
    session.add(event)
    await session.flush()
    return event


async def chat_messages(session: AsyncSession) -> list[Message]:
    return list(
        (await session.scalars(select(Message).where(Message.kind == "meeting_prep"))).all()
    )


async def test_an_hour_before_venture_sends_the_draft(session: AsyncSession) -> None:
    event = await linked_meeting(session, EVENING)
    fake = FakeGitHub(extra={"week3/ece/.gitkeep": ""})  # a member who handed in nothing
    hour_before = EVENING - dt.timedelta(minutes=55)

    early = await meeting_prep.prepare_due(
        session, EVENING - dt.timedelta(hours=3), settings(), github_factory=fake.factory()
    )
    [text] = await meeting_prep.prepare_due(
        session, hour_before, settings(), github_factory=fake.factory()
    )
    again = await meeting_prep.prepare_due(
        session, hour_before + dt.timedelta(minutes=5), settings(), github_factory=fake.factory()
    )

    assert early == []  # three hours before: not yet
    assert again == []  # then only once
    assert text.startswith("NEXA toplantısı Pazartesi 19:00'de (1 saatten az kaldı).")
    assert "Week 3 sunum taslağı hazır (week3):" in text
    assert "- ali (ali-dev): Etkinlik öneri API'si" in text
    assert "- deniz (dnz42): Kullanıcı segmentasyonu" in text
    assert "- mert-rapor (mertc): Rakip analizi" in text
    assert "Klasörü boş: ece." in text
    assert event.prep_sent_at == hour_before
    [message] = await chat_messages(session)
    assert (message.agent_id, message.content) == ("startup", text)
    assert all(method == "GET" for method, _ in fake.requests)


async def test_without_github_it_says_which_setting(session: AsyncSession) -> None:
    await linked_meeting(session, EVENING)

    [text] = await meeting_prep.prepare_due(
        session, EVENING - dt.timedelta(minutes=30), settings(github_token=None)
    )

    assert "Sunum taslağını hazırlayamadım: GITHUB_TOKEN yok" in text


async def test_all_day_and_unlinked_events_get_nothing(session: AsyncSession) -> None:
    session.add(Event(kind=EventKind.MEETING, title="Iceberg", start_at=EVENING))
    session.add(
        Event(
            kind=EventKind.MEETING, title="NEXA günü", start_at=EVENING, all_day=True,
            end_at=EVENING + dt.timedelta(days=1),
            owner_id="startup",
        )
    )  # fmt: skip
    await session.flush()

    sent = await meeting_prep.prepare_due(
        session, EVENING - dt.timedelta(minutes=30), settings(),
        github_factory=FakeGitHub().factory(),
    )  # fmt: skip

    assert sent == []
