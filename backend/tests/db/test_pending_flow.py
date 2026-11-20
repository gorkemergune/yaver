"""The open question kept on the conversation: a short answer ("Evet, salı") finishes the
job in code instead of depending on the coordinator to pass the context along."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import ToolContext
from app.agent.tools import run_tool
from app.db.models import Attendance, Conversation
from app.llm.types import LLMRequest
from tests.agent_fakes import NOW, ScriptedLLM, call, coordinator, say
from tests.db.test_agent_tools import context

ASKED = "16 Kasım Pazartesi EE 211 dersin yok. En yakın ders 17 Kasım Salı, o mu?"
INSTRUCTION = "Geçen pazartesi EE 211'e gitmedim"


@pytest.fixture
async def ctx(session: AsyncSession) -> ToolContext:
    ctx = context(session, "academic")
    for kind, title, weekday, start, end in (
        ("class", "EE 211", "tuesday", "14:00", "16:00"),
        ("class", "EE 211", "thursday", "13:00", "14:00"),
    ):
        result = await run_tool(
            "add_recurring_block",
            {"kind": kind, "title": title, "course": "EE 211", "weekdays": [weekday],
             "start_time": start, "end_time": end},
            ctx,
        )  # fmt: skip
        assert "created" in result, result
    await session.commit()
    return ctx


async def ask_first(llm: ScriptedLLM, session: AsyncSession) -> int:
    """Monday 23 Nov: "geçen pazartesi" (16th) has no EE 211, the tool suggests the 17th."""
    llm.add(
        "yaver",
        call("delegate", agent_id="academic", instruction=INSTRUCTION),
        say(f"Friday: {ASKED}"),
    )
    llm.add(
        "academic",
        call("log_attendance", course="EE 211", dates=["2026-11-16"]),
        say(ASKED),
    )
    reply = await coordinator(llm).handle(session, INSTRUCTION, now=NOW)
    assert reply.change_set_id is None
    conversation = await session.get(Conversation, reply.conversation_id)
    assert conversation is not None
    pending = conversation.pending_action
    assert pending is not None
    assert (pending["agent_id"], pending["tool"], pending["request"]) == (
        "academic",
        "log_attendance",
        INSTRUCTION,
    )
    assert [o["label"] for o in pending["options"]] == ["2026-11-17 Salı"]
    return reply.conversation_id


async def absences(session: AsyncSession) -> list[tuple[str, int]]:
    rows = (await session.scalars(select(Attendance).order_by(Attendance.date))).all()
    return [(row.date.isoformat(), row.hours) for row in rows]


async def test_yes_with_the_day_runs_the_tool_in_code(ctx: ToolContext) -> None:
    llm = ScriptedLLM()
    conversation_id = await ask_first(llm, ctx.session)
    seen: list[LLMRequest] = []

    def report(request: LLMRequest) -> Any:
        seen.append(request)
        return say("17 Kasım Salı EE 211 14:00-16:00: 2 saat devamsızlık kaydettim.")

    llm.add("academic", report)
    reply = await coordinator(llm).handle(
        ctx.session, "Evet, salı", conversation_id=conversation_id, now=NOW
    )

    assert await absences(ctx.session) == [("2026-11-17", 2)]
    assert reply.change_set_id is not None
    assert reply.speaker == "academic"
    assert [(t["tool"], t.get("bound")) for t in reply.trace] == [("log_attendance", True)]
    # one answer without tools, with the question it answers
    (request,) = seen
    assert request.tools == []  # no tool list: the code already ran it
    assert [m.content for m in request.messages] == [INSTRUCTION, ASKED, "Evet, salı"]
    assert "Bunu az önce sen yaptın" in (request.system_suffix or "")
    conversation = await ctx.session.get(Conversation, conversation_id)
    assert conversation is not None
    assert conversation.pending_action is None  # answered
    llm.assert_done()


async def test_another_answer_goes_back_to_the_yaver_that_asked(ctx: ToolContext) -> None:
    llm = ScriptedLLM()
    conversation_id = await ask_first(llm, ctx.session)
    seen: list[LLMRequest] = []

    def thursday(request: LLMRequest) -> Any:
        seen.append(request)
        return call("log_attendance", course="EE 211", dates=["2026-11-19"])

    llm.add("academic", thursday, say("19 Kasım Perşembe EE 211: 1 saat kaydettim."))
    reply = await coordinator(llm).handle(
        ctx.session, "perşembe", conversation_id=conversation_id, now=NOW
    )

    assert await absences(ctx.session) == [("2026-11-19", 1)]
    assert reply.speaker == "academic"
    assert [m.content for m in seen[0].messages] == [INSTRUCTION, ASKED, "perşembe"]
    assert "son sorunun cevabı" in (seen[0].system_suffix or "")
    llm.assert_done()


async def test_no_or_a_new_message_goes_to_the_coordinator(ctx: ToolContext) -> None:
    llm = ScriptedLLM()
    conversation_id = await ask_first(llm, ctx.session)
    llm.add("yaver", say("Tamam, bir şey kaydetmedim."))
    reply = await coordinator(llm).handle(
        ctx.session, "hayır boşver", conversation_id=conversation_id, now=NOW
    )
    assert reply.speaker == "yaver"
    assert await absences(ctx.session) == []
    conversation = await ctx.session.get(Conversation, conversation_id)
    assert conversation is not None
    assert conversation.pending_action is None
    llm.assert_done()


async def test_an_english_answer_is_rewritten_once(ctx: ToolContext) -> None:
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        say("You have no classes recorded today and the plan is empty, have a nice day."),
        say("Bugün kayıtlı dersin yok, plan boş. İyi günler!"),
    )
    reply = await coordinator(llm).handle(ctx.session, "Bugün ne var", now=NOW)
    assert reply.reply == "Bugün kayıtlı dersin yok, plan boş. İyi günler!"
    assert llm.purposes == ["chat", "language_fix"]
    assert len(reply.llm_calls) == 2
    llm.assert_done()


async def test_a_new_request_after_a_question_is_not_its_answer(ctx: ToolContext) -> None:
    """Live run: Karen asked about the evening; "Geçen salı EE211'e gitmedim" went to her."""
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        call("delegate", agent_id="discipline", instruction="akşam spora gidemem"),
        say("Karen: bugün spor yok. Hangi akşamı kastediyorsun?"),
    )
    llm.add("discipline", say("Bugün spor yok. Hangi akşamı kastediyorsun?"))
    first = await coordinator(llm).handle(ctx.session, "akşam spora gidemem", now=NOW)
    conversation = await ctx.session.get(Conversation, first.conversation_id)
    assert conversation is not None
    assert conversation.pending_action is not None
    assert conversation.pending_action["agent_id"] == "discipline"
    assert conversation.pending_action["tool"] is None  # a question in words only

    llm.add(
        "yaver",
        call("delegate", agent_id="academic", instruction="Geçen salı EE 211'e gitmedim"),
        say("Friday: 17 Kasım Salı EE 211 2 saat kaydetti."),
    )
    llm.add(
        "academic",
        call("log_attendance", course="EE 211", dates=["2026-11-17"]),
        say("17 Kasım Salı EE 211: 2 saat kaydettim."),
    )
    reply = await coordinator(llm).handle(
        ctx.session, "Geçen salı EE 211'e gitmedim", conversation_id=first.conversation_id, now=NOW
    )
    assert reply.speaker == "yaver"
    assert await absences(ctx.session) == [("2026-11-17", 2)]
    llm.assert_done()


async def test_resolving_a_date_is_not_doing_the_request(ctx: ToolContext) -> None:
    """Live run: resolve_date, then "kaydetmemi onaylar mısın?" - one more turn with a tool."""
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        call("resolve_date", expression="geçen salı", direction="past"),
        say("Friday kaydetmek için hazır. Onay verir misin?"),
        call("delegate", agent_id="academic", instruction="Geçen salı EE 211'e gitmedim"),
        say("Friday: 17 Kasım Salı EE 211 2 saat kaydetti."),
    )
    llm.add(
        "academic",
        call("log_attendance", course="EE 211", dates=["2026-11-17"]),
        say("Kaydettim."),
    )
    await coordinator(llm).handle(ctx.session, "Geçen salı EE 211'e gitmedim", now=NOW)
    assert await absences(ctx.session) == [("2026-11-17", 2)]
    llm.assert_done()
