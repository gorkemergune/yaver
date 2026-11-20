"""Coordinator + yavers end to end with a scripted LLM and real PostgreSQL.

Monday 23 Nov 2026, 10:00 Istanbul. The scripts call resolve_date and use its result,
exactly as the real model must (no date math in the "model")."""

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import ChatReply
from app.db.models import (
    Attendance,
    BlockOverride,
    ChangeLog,
    Course,
    Event,
    Message,
    RecurringBlock,
)
from app.db.models.enums import MessageRole, OverrideAction
from app.llm.types import LLMRequest, LLMResponse
from tests.agent_fakes import NOW, ScriptedLLM, call, calls, coordinator, last_result, say


def resolved(field: str = "start") -> Any:
    return lambda request: last_result(request)[field]


def then(tool: str, **arguments: Any) -> Any:
    """Next tool call using the previous resolve_date result for date/time placeholders."""

    def step(request: LLMRequest) -> LLMResponse:
        result = last_result(request)
        args = {k: (v(request) if callable(v) else v) for k, v in arguments.items()}
        assert result.get("status") == "resolved", result
        return call(tool, **args)

    return step


async def send(session: AsyncSession, llm: ScriptedLLM, text: str) -> ChatReply:
    reply = await coordinator(llm).handle(session, text, now=NOW)
    llm.assert_done()
    return reply


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


# --- 1) "Pazartesi 9-11 Linear Algebra, Çarşamba 13-15 EE211 lab, salı perşembe 19-20 spor"


def week_setup_script() -> ScriptedLLM:
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        calls(
            (
                "delegate",
                {
                    "agent_id": "academic",
                    "instruction": "Pazartesi 9-11 Linear Algebra, Çarşamba 13-15 EE211 lab ekle",
                },
            ),
            (
                "delegate",
                {"agent_id": "discipline", "instruction": "Salı ve perşembe 19-20 spor ekle"},
            ),
        ),
        say("Atlas derslerini, Kaan sporu ekledi."),
    )
    llm.add(
        "academic",
        calls(
            (
                "add_recurring_block",
                {
                    "kind": "class",
                    "title": "Linear Algebra",
                    "weekdays": ["monday"],
                    "start_time": "09:00",
                    "end_time": "11:00",
                    "course": "Linear Algebra",
                },
            ),
            (
                "add_recurring_block",
                {
                    "kind": "lab",
                    "title": "EE211 Lab",
                    "weekdays": ["wednesday"],
                    "start_time": "13:00",
                    "end_time": "15:00",
                    "course": "EE211",
                },
            ),
        ),
        say("Linear Algebra ve EE211 Lab eklendi."),
    )
    llm.add(
        "discipline",
        call(
            "add_recurring_block",
            kind="sport",
            title="Spor",
            weekdays=["tuesday", "thursday"],
            start_time="19:00",
            end_time="20:00",
        ),
        say("Salı ve perşembe 19-20 spor eklendi."),
    )
    return llm


async def test_full_week_story(session: AsyncSession) -> None:
    # 1) weekly schedule from one message, two yavers, one change set
    first = await send(
        session,
        week_setup_script(),
        "Pazartesi 9-11 Linear Algebra, Çarşamba 13-15 EE211 lab, salı perşembe 19-20 spor",
    )
    blocks = (await session.scalars(select(RecurringBlock).order_by(RecurringBlock.weekday))).all()
    assert [(b.title, b.weekday, b.start_time.hour) for b in blocks] == [
        ("Linear Algebra", 0, 9),
        ("Spor", 1, 19),
        ("EE211 Lab", 2, 13),
        ("Spor", 3, 19),
    ]
    assert sorted((await session.scalars(select(Course.code))).all()) == ["EE211", "Linear Algebra"]
    assert first.change_set_id is not None
    sets = (await session.scalars(select(ChangeLog.change_set_id).distinct())).all()
    assert sets == [first.change_set_id]
    agents = set((await session.scalars(select(ChangeLog.agent_id))).all())
    assert agents == {"academic", "discipline"}
    assert [a["name"] for a in first.agents] == ["Atlas", "Kaan"]

    # 2) "Bugün linear iptal, yarın 14'te Iceberg toplantısı var, akşam spora gidemem"
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        calls(
            ("delegate", {"agent_id": "academic", "instruction": "Bugün linear iptal"}),
            (
                "delegate",
                {"agent_id": "agenda", "instruction": "Yarın 14'te Iceberg toplantısı var"},
            ),
            ("delegate", {"agent_id": "discipline", "instruction": "Bugün akşam spora gidemem"}),
        ),
        say("Atlas linear'ı iptal etti, Deniz toplantıyı ekledi; Kaan: bugün spor yok."),
    )
    llm.add(
        "academic",
        call("resolve_date", expression="bugün", direction="future"),
        then("cancel_block_on", date=resolved(), block="linear"),
        say("Bugünkü Linear Algebra iptal edildi."),
    )
    llm.add(
        "agenda",
        call("resolve_date", expression="yarın 14'te", direction="future"),
        then(
            "add_event",
            kind="meeting",
            title="Iceberg toplantısı",
            date=resolved(),
            start_time=resolved("time"),
        ),
        say("Yarın 14:00 Iceberg toplantısı eklendi."),
    )
    llm.add(
        "discipline",
        call("resolve_date", expression="bugün akşam", direction="any"),
        then("cancel_block_on", date=resolved(), block="spor"),
        say("Bugün zaten spor yok."),
    )
    second = await send(
        session, llm, "Bugün linear iptal, yarın 14'te Iceberg toplantısı var, akşam spora gidemem"
    )

    override = await session.scalar(select(BlockOverride))
    assert override is not None
    assert (override.date, override.action) == (dt.date(2026, 11, 23), OverrideAction.CANCEL)
    assert await count(session, BlockOverride) == 1  # no sport block on Monday to cancel
    event = await session.scalar(select(Event))
    assert event is not None
    assert event.start_at == dt.datetime(2026, 11, 24, 11, 0, tzinfo=dt.UTC)  # 14:00 Istanbul
    discipline_errors = [
        m
        for agent, req in llm.requests
        if agent == "discipline"
        for m in req.messages
        if m.role == "tool" and m.is_error
    ]
    assert discipline_errors
    assert "no 'spor' block" in discipline_errors[0].content
    assert second.change_set_id is not None
    assert {action["tool"] for action in second.actions} == {
        "cancel_block_on",
        "add_event",
    }

    # 3) "Geçen çarşamba EE211'e gitmedim" -> resolved in the past, counted in class hours
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        call("delegate", agent_id="academic", instruction="Geçen çarşamba EE211'e gitmedim"),
        say("Atlas devamsızlığı kaydetti."),
    )
    llm.add(
        "academic",
        call("resolve_date", expression="geçen çarşamba", direction="past"),
        then(
            "log_attendance",
            course="EE211",
            dates=lambda request: [last_result(request)["start"]],
            status="absent",
        ),
        say("EE211 devamsızlık kaydedildi: 18 Kasım Çarşamba 13:00-15:00, 2 saat."),
    )
    third = await send(session, llm, "Geçen çarşamba EE211'e gitmedim")
    attendance = await session.scalar(select(Attendance))
    assert attendance is not None
    assert (attendance.date, attendance.hours) == (dt.date(2026, 11, 18), 2)
    logged = third.actions[0]["result"]
    assert logged["summary"]["absent_hours"] == 2
    assert "not_logged" not in logged

    # 4) "Yarın ne var?" -> read only, answered by the coordinator itself
    llm = ScriptedLLM()
    seen: dict[str, Any] = {}

    def answer(request: LLMRequest) -> LLMResponse:
        seen.update(last_result(request))
        return say("Yarın 14:00 Iceberg toplantısı ve 19:00 spor var.")

    llm.add(
        "yaver",
        call("resolve_date", expression="yarın", direction="any"),
        then("get_day_plan", date=resolved()),
        answer,
    )
    fourth = await send(session, llm, "Yarın ne var?")
    assert [item["title"] for item in seen["items"]] == ["Iceberg toplantısı", "Spor"]
    assert fourth.change_set_id is None
    assert fourth.agents == []

    # 5) "Son değişikliği geri al" -> the attendance (message 3) is undone, nothing else
    llm = ScriptedLLM()
    llm.add("yaver", call("undo"), say("Son değişiklik geri alındı."))
    fifth = await send(session, llm, "Son değişikliği geri al")
    assert await count(session, Attendance) == 0
    assert await count(session, Event) == 1
    assert await count(session, BlockOverride) == 1
    undone = (
        await session.scalars(select(ChangeLog).where(ChangeLog.undone_at.is_not(None)))
    ).all()
    assert {entry.change_set_id for entry in undone} == {third.change_set_id}
    assert fifth.actions[0]["result"]["undone_change_set"] == str(third.change_set_id)

    # ... and once more: the whole of message 2 (three yavers) goes in one step
    llm = ScriptedLLM()
    llm.add("yaver", call("undo"), say("Geri alındı."))
    await send(session, llm, "Bir öncekini de geri al")
    assert await count(session, Event) == 0
    assert await count(session, BlockOverride) == 0
    assert await count(session, RecurringBlock) == 4  # message 1 untouched

    # conversation history: user + per-yaver replies + final answers, with agent ids
    roles = (
        await session.execute(select(Message.role, Message.agent_id).order_by(Message.id))
    ).all()
    assert roles[:4] == [
        (MessageRole.USER, None),
        (MessageRole.ASSISTANT, "academic"),
        (MessageRole.ASSISTANT, "discipline"),
        (MessageRole.ASSISTANT, "yaver"),
    ]


async def test_addressing_a_yaver_by_name_skips_the_coordinator(session: AsyncSession) -> None:
    await send(session, week_setup_script(), "kurulum")
    llm = ScriptedLLM()
    llm.add(
        "academic",
        call("resolve_date", expression="yarın", direction="any"),
        then("get_day_plan", date=resolved()),
        say("Yarın 19:00 spor var, dersin yok."),
    )

    reply = await send(session, llm, "Atlas, yarın ne var?")

    assert reply.speaker == "academic"
    assert [agent for agent, _ in llm.requests] == ["academic"] * 3
    assert llm.models == [{"groq": "openai/gpt-oss-20b"}] * 3  # per-yaver model from agents.yaml
    assert llm.requests[0][1].messages[-1].content == "yarın ne var?"


async def test_ambiguous_date_becomes_a_question_not_a_guess(session: AsyncSession) -> None:
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        call("delegate", agent_id="agenda", instruction="Gelecek cuma toplantı ekle"),
        lambda r: say(last_result(r)["reply"]),
    )

    def ask(request: LLMRequest) -> LLMResponse:
        result = last_result(request)
        assert result["status"] == "ambiguous"
        options = " mı, ".join(c["start"] for c in result["candidates"])
        return say(f"{options} mı?")

    llm.add("agenda", call("resolve_date", expression="gelecek cuma", direction="future"), ask)

    reply = await send(session, llm, "Gelecek cuma toplantı ekle")

    assert reply.reply == "2026-11-27 mı, 2026-12-04 mı?"
    assert reply.change_set_id is None
    assert await count(session, Event) == 0


async def test_unknown_delegate_target_is_reported_back(session: AsyncSession) -> None:
    llm = ScriptedLLM()

    def check(request: LLMRequest) -> LLMResponse:
        assert "unknown agent_id" in last_result(request)["error"]
        return say("Bunu yapamadım.")

    llm.add("yaver", call("delegate", agent_id="finance", instruction="x"), check)

    assert (await send(session, llm, "x")).reply == "Bunu yapamadım."


async def test_step_limit_ends_with_a_summary_turn(session: AsyncSession) -> None:
    llm = ScriptedLLM()
    llm.add("yaver", *[call("resolve_date", expression="yarın") for _ in range(6)])

    def final(request: LLMRequest) -> LLMResponse:
        assert request.tool_choice == "none"
        return say("Çok adım oldu, duruyorum.")

    llm.add("yaver", final)

    assert (await send(session, llm, "Yarın?")).reply == "Çok adım oldu, duruyorum."


async def test_failure_rolls_back_the_whole_message(session: AsyncSession) -> None:
    llm = week_setup_script()
    llm.scripts["discipline"] = []  # the second yaver's LLM call blows up

    try:
        await coordinator(llm).handle(session, "kurulum", now=NOW)
    except AssertionError:
        pass
    else:
        raise AssertionError("expected the scripted LLM to fail")

    assert await count(session, RecurringBlock) == 0  # academic's blocks rolled back too
    assert await count(session, Message) == 0


async def test_history_is_sent_with_the_next_message(session: AsyncSession) -> None:
    first = await send(session, week_setup_script(), "kurulum")
    llm = ScriptedLLM({"yaver": [say("Rica ederim!")]})

    await coordinator(llm).handle(
        session, "teşekkürler", conversation_id=first.conversation_id, now=NOW
    )

    sent = llm.requests[0][1].messages
    assert [m.role for m in sent] == ["user", "assistant", "user"]
    assert sent[1].content == "Atlas derslerini, Kaan sporu ekledi."
    assert "Şu an: 2026-11-23 10:00 Pazartesi" in (llm.requests[0][1].system_suffix or "")


async def test_tomorrow_quiz(session: AsyncSession) -> None:
    await send(session, week_setup_script(), "kurulum")
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        call("delegate", agent_id="academic", instruction="Yarın EE211 quiz var"),
        say("Atlas quiz'i ekledi."),
    )
    llm.add(
        "academic",
        call("resolve_date", expression="yarın", direction="future"),
        then("add_event", kind="quiz", title="EE211 Quiz", date=resolved(), course="EE211"),
        say("Yarın EE211 quiz eklendi."),
    )

    reply = await send(session, llm, "Yarın EE211 quiz var")

    event = await session.scalar(select(Event))
    assert event is not None
    assert (event.kind.value, event.all_day) == ("quiz", True)
    assert event.start_at == dt.datetime(2026, 11, 23, 21, 0, tzinfo=dt.UTC)  # 24 Nov 00:00 IST
    course = await session.scalar(select(Course).where(Course.code == "EE211"))
    assert course is not None
    assert event.course_id == course.id
    assert reply.change_set_id is not None


async def test_fast_path_simple_message_without_delegation(session: AsyncSession) -> None:
    await send(session, week_setup_script(), "kurulum")
    llm = ScriptedLLM()
    llm.add(
        "yaver",
        call("resolve_date", expression="bugün", direction="future"),
        then("cancel_block_on", date=resolved(), block="linear"),
        say("Bugünkü Linear Algebra iptal edildi."),
    )

    reply = await send(session, llm, "Bugün linear iptal")

    assert [agent for agent, _ in llm.requests] == ["yaver"] * 3  # no yaver round trip
    assert reply.agents == []
    override = await session.scalar(select(BlockOverride))
    assert override is not None
    assert override.date == dt.date(2026, 11, 23)
    entry = await session.scalar(
        select(ChangeLog).where(ChangeLog.change_set_id == reply.change_set_id)
    )
    assert entry is not None
    assert entry.agent_id == "yaver"


async def test_second_delegation_to_the_same_yaver_is_not_run_again(session: AsyncSession) -> None:
    llm = ScriptedLLM()

    def check(request: LLMRequest) -> LLMResponse:
        assert last_result(request)["already_done"] is True
        return say("Tamam.")

    llm.add(
        "yaver",
        call("delegate", agent_id="discipline", instruction="salı spor ekle"),
        call("delegate", agent_id="discipline", instruction="salı spor ekle"),
        check,
    )
    llm.add(
        "discipline",
        call(
            "add_recurring_block",
            kind="sport",
            title="Spor",
            weekdays=["tuesday"],
            start_time="19:00",
            end_time="20:00",
        ),
        say("Eklendi."),
    )

    reply = await send(session, llm, "salı 19-20 spor")

    assert await count(session, RecurringBlock) == 1
    assert [a["agent_id"] for a in reply.agents] == ["discipline"]
