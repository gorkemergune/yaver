"""Intent-first routing: the code, not a word in the message, decides who gets each part;
a new request right after a question is not its answer; a yaver outside its area hands the
message back (`handoff`) and the right one does it in the same message.

Real failure behind these: "yarın sabah Medipoldeki kahvaltıya gidicem" went to Scholar
(it had an open question), Scholar said "ders değil" and nothing was added."""

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.db.models import Conversation, Event
from app.db.models.enums import EventKind
from app.llm.types import LLMRequest
from tests.agent_fakes import NOW, ScriptedLLM, call, coordinator, route_as, say
from tests.db.test_agent_tools import context

BREAKFAST = "yarın sabah Medipoldeki kahvaltıya gidicem"
ADDED = "Yarın 09:00'a Medipol kahvaltısını ekledim."


def adds_breakfast(llm: ScriptedLLM, who: str = "agenda") -> None:
    llm.add(
        who,
        call("resolve_date", expression="yarın sabah", direction="future"),
        call(
            "add_event",
            kind="other",
            title="Medipol kahvaltısı",
            date="2026-11-24",
            start_time="09:00",
            location="Medipol",
        ),
        say(ADDED),
    )


async def breakfast(session: AsyncSession) -> Event:
    [event] = (await session.scalars(select(Event))).all()
    assert event.title == "Medipol kahvaltısı"
    assert event.kind is EventKind.OTHER
    assert event.start_at == dt.datetime(2026, 11, 24, 6, 0, tzinfo=dt.UTC)  # 09:00 Istanbul
    return event


def seen_by(requests: list[LLMRequest]) -> Any:
    def answer(request: LLMRequest) -> Any:
        requests.append(request)
        return say(f"Chrono: {ADDED}")

    return answer


async def test_the_intent_picks_the_employee_in_code(session: AsyncSession) -> None:
    llm = ScriptedLLM()
    llm.add("intent", route_as(("event", BREAKFAST)))
    adds_breakfast(llm)
    coordinator_saw: list[LLMRequest] = []
    llm.add("yaver", seen_by(coordinator_saw))

    reply = await coordinator(llm).handle(session, BREAKFAST, now=NOW)

    await breakfast(session)
    assert [r["agent_id"] for r in reply.agents] == ["agenda"]
    # the coordinator only writes the answer: it sees the delegation as already done
    [request] = coordinator_saw
    assert [m.role for m in request.messages] == ["user", "assistant", "tool"]
    assert request.messages[1].tool_calls[0].arguments == {
        "agent_id": "agenda",
        "instruction": BREAKFAST,
    }
    assert reply.change_set_id is not None
    llm.assert_done()


async def test_two_parts_go_to_two_employees_with_the_whole_message(
    session: AsyncSession,
) -> None:
    text = "pazartesi dsa sınavı var, bi de yarın sabah kahvaltıya gidicem"
    llm = ScriptedLLM()
    llm.add(
        "intent",
        route_as(("exam", "pazartesi dsa sınavı var"), ("event", "yarın sabah kahvaltıya gidicem")),
    )
    got: dict[str, str] = {}

    def remember_instruction(who: str) -> Any:
        def step(request: LLMRequest) -> Any:
            got[who] = request.messages[0].content
            return say("Tamam.")

        return step

    llm.add("academic", remember_instruction("academic"))
    llm.add("agenda", remember_instruction("agenda"))
    llm.add("yaver", say("Scholar: tamam. Chrono: tamam."))

    reply = await coordinator(llm).handle(session, text, now=NOW)

    assert [r["agent_id"] for r in reply.agents] == ["academic", "agenda"]
    assert got["academic"] == f"pazartesi dsa sınavı var\nKullanıcının mesajı: {text}"
    assert got["agenda"].startswith("yarın sabah kahvaltıya gidicem\n")


async def test_a_new_request_after_a_question_is_not_its_answer(session: AsyncSession) -> None:
    conversation = Conversation(
        title="x",
        pending_action={
            "agent_id": "academic",
            "request": "bugünkü ek ders vardı ee211 ona gitmedim",
            "question": "Bu telafi dersine mi gitmedin?",
            "created_at": NOW.isoformat(),
        },
    )
    session.add(conversation)
    await session.commit()
    llm = ScriptedLLM()
    asked: list[str] = []

    def classify(request: LLMRequest) -> Any:
        asked.append(request.messages[0].content)
        return route_as(("event", BREAKFAST))

    llm.add("intent", classify)
    adds_breakfast(llm)
    llm.add("yaver", say(f"Chrono: {ADDED}"))  # never Scholar

    await coordinator(llm).handle(session, BREAKFAST, conversation_id=conversation.id, now=NOW)

    await breakfast(session)
    assert asked[0].startswith("Açık soru (ekip az önce sordu): Bu telafi dersine mi gitmedin?")
    llm.assert_done()


async def test_an_answer_to_the_question_still_goes_to_who_asked(session: AsyncSession) -> None:
    conversation = Conversation(
        title="x",
        pending_action={
            "agent_id": "academic",
            "request": "pazartesi DSA sınavı var",
            "question": "DSA hangi ders: CSE 211 mi, CSE 221 mi?",
            "created_at": NOW.isoformat(),
        },
    )
    session.add(conversation)
    await session.commit()
    llm = ScriptedLLM()
    llm.add("intent", route_as(("answer", "cse 211")))
    llm.add("academic", say("CSE 211 sınavı saat kaçta?"))

    reply = await coordinator(llm).handle(
        session, "cse 211", conversation_id=conversation.id, now=NOW
    )

    assert reply.speaker == "academic"
    llm.assert_done()


async def test_a_yaver_outside_its_area_hands_it_to_the_right_one(session: AsyncSession) -> None:
    llm = ScriptedLLM()
    llm.add("intent", route_as(("class", BREAKFAST)))  # a wrong guess of the classifier
    llm.add("academic", call("handoff", reason="ders değil, etkinlik", area="event"))
    adds_breakfast(llm)
    llm.add("yaver", say(f"Chrono: {ADDED}"))

    reply = await coordinator(llm).handle(session, BREAKFAST, now=NOW)

    await breakfast(session)
    # Scholar's handoff is no message of its own
    assert [r["agent_id"] for r in reply.agents] == ["agenda"]
    llm.assert_done()


async def test_named_yaver_hands_back_and_the_coordinator_routes_it(
    session: AsyncSession,
) -> None:
    text = f"Scholar, {BREAKFAST}"
    llm = ScriptedLLM()
    llm.add("academic", call("handoff", reason="ders değil", area="event"))
    llm.add("intent", route_as(("event", BREAKFAST)))
    adds_breakfast(llm)
    llm.add("yaver", say(f"Chrono: {ADDED}"))

    reply = await coordinator(llm).handle(session, text, now=NOW)

    await breakfast(session)
    assert reply.speaker == "yaver"
    llm.assert_done()


async def test_any_yaver_can_add_a_plain_event_itself(session: AsyncSession) -> None:
    """Scholar got the breakfast as the answer to its question: it adds it, no handoff."""
    text = "Scholar, yarın sabah 9da medipol kahvaltısı ekle"
    llm = ScriptedLLM()
    adds_breakfast(llm, who="academic")

    reply = await coordinator(llm).handle(session, text, now=NOW)

    await breakfast(session)
    assert reply.speaker == "academic"


async def test_no_model_for_the_intents_falls_back_to_the_coordinator(
    session: AsyncSession,
) -> None:
    llm = ScriptedLLM()
    llm.add("intent", say("no tool call"))  # classification failed
    llm.add("yaver", call("delegate", agent_id="agenda", instruction=BREAKFAST), say(ADDED))
    adds_breakfast(llm)

    await coordinator(llm).handle(session, BREAKFAST, now=NOW)

    await breakfast(session)
    llm.assert_done()


async def test_a_part_of_the_day_gets_a_default_hour(session: AsyncSession) -> None:
    ctx = context(session, "agenda")
    morning = await run_tool(
        "resolve_date", {"expression": "yarın sabah", "direction": "future"}, ctx
    )
    exact = await run_tool(
        "resolve_date", {"expression": "yarın 14'te", "direction": "future"}, ctx
    )

    assert (morning["start"], morning["default_start_time"]) == ("2026-11-24", "09:00")
    assert "default_start_time" not in exact
