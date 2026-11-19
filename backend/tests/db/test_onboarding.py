"""First-run setup: tools, schedule proposal -> confirm -> one change set, routing."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import run_tool
from app.db.models import (
    ChangeLog,
    Conversation,
    Course,
    Holiday,
    Proposal,
    RecurringBlock,
)
from app.db.models.enums import ConversationMode, ProposalStatus
from app.llm.types import LLMRequest, LLMResponse
from tests.agent_fakes import NOW, ScriptedLLM, call, calls, coordinator, last_result, say
from tests.db.test_agent_tools import context

PARSED: dict[str, Any] = {
    "entries": [
        {
            "kind": "class",
            "title": "Linear Algebra",
            "course": "MATH221",
            "weekdays": ["monday", "wednesday"],
            "start_time": "09:00",
            "end_time": "11:00",
            "location": "B204",
        },
        {
            "kind": "lab",
            "title": "EE211 Lab",
            "course": "EE211",
            "weekdays": ["thursday"],
            "start_time": "13:00",
            "end_time": "15:00",
        },
    ],
    "unclear": ["Cuma ?? Fizik"],
}
LONG_TABLE = "\n".join(
    [
        "Gün | Saat | Ders",
        "Pzt | 09-11 | Linear Algebra (MATH221) B204",
        "Çar | 09-11 | Linear Algebra (MATH221) B204",
        "Per | 13-15 | EE211 Lab",
        "Cuma | ?? | Fizik",
    ]
)


def parser_llm(result: dict[str, Any] | None = None) -> ScriptedLLM:
    return ScriptedLLM({"schedule_parser": [call("schedule_entries", **(result or PARSED))]})


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


# --- tools -----------------------------------------------------------------------------


async def test_term_and_holiday(session: AsyncSession) -> None:
    ctx = context(session, "onboarding")

    term = await run_tool(
        "add_term",
        {"name": "2026-2027 Güz", "start_date": "2026-09-28", "end_date": "2027-01-08"},
        ctx,
    )
    holiday = await run_tool(
        "add_holiday",
        {"name": "Ara tatil", "start_date": "2026-11-16", "end_date": "2026-11-20"},
        ctx,
    )
    backwards = await run_tool(
        "add_term", {"name": "x", "start_date": "2027-01-08", "end_date": "2026-09-28"}, ctx
    )

    assert term["term"]["start"] == "2026-09-28"
    assert holiday["holiday"]["end"] == "2026-11-20"
    stored = await session.scalar(select(Holiday))
    assert stored is not None
    assert stored.term_id == term["term"]["term_id"]  # linked to the term it falls into
    assert "end_date is before start_date" in backwards["error"]


async def test_long_schedule_is_parsed_by_the_smart_tier_into_a_pending_proposal(
    session: AsyncSession,
) -> None:
    ctx = context(session, "onboarding")
    ctx.llm = llm = parser_llm()

    result = await run_tool("propose_schedule", {"text": LONG_TABLE}, ctx)

    assert llm.purposes == ["schedule_parse"]  # -> routing.purposes: smart (Sonnet)
    assert result["entries"] == 2
    assert result["unclear"] == ["Cuma ?? Fizik"]
    table = result["table"].splitlines()
    assert table[0] == "| Gün | Saat | Ders / blok | Tür | Yer |"
    assert table[2:] == [
        "| Pazartesi | 09:00-11:00 | Linear Algebra (MATH221) | Ders | B204 |",
        "| Çarşamba | 09:00-11:00 | Linear Algebra (MATH221) | Ders | B204 |",
        "| Perşembe | 13:00-15:00 | EE211 Lab | Lab |  |",
    ]
    assert await count(session, RecurringBlock) == 0  # nothing saved before confirmation
    proposal = await session.get(Proposal, result["proposal_id"])
    assert proposal is not None
    assert proposal.status is ProposalStatus.PENDING


async def test_short_schedule_uses_the_default_tier(session: AsyncSession) -> None:
    ctx = context(session, "onboarding")
    ctx.llm = llm = parser_llm()

    await run_tool("propose_schedule", {"text": "Pzt 9-11 Linear Algebra"}, ctx)

    assert llm.purposes == ["schedule_parse_short"]


async def test_apply_writes_once_and_closes_older_proposals(session: AsyncSession) -> None:
    ctx = context(session, "onboarding")
    ctx.llm = ScriptedLLM(
        {
            "schedule_parser": [
                call("schedule_entries", **PARSED),
                call("schedule_entries", **PARSED),
            ]
        }
    )
    first = await run_tool("propose_schedule", {"text": LONG_TABLE}, ctx)
    second = await run_tool("propose_schedule", {"text": LONG_TABLE + "\nduzeltme"}, ctx)
    unseen = await run_tool("apply_proposal", {"proposal_id": second["proposal_id"]}, ctx)

    reply = context(session, "onboarding")  # the user's next message: "evet"
    applied = await run_tool("apply_proposal", {"proposal_id": second["proposal_id"]}, reply)
    again = await run_tool("apply_proposal", {"proposal_id": second["proposal_id"]}, reply)

    assert "has not seen this proposal yet" in unseen["error"]  # same message: no table shown
    assert applied == {"blocks_created": 3, "already_existed": 0}
    assert "already applied" in again["error"]
    assert await count(session, RecurringBlock) == 3
    assert sorted((await session.scalars(select(Course.code))).all()) == ["EE211", "MATH221"]
    old = await session.get(Proposal, first["proposal_id"])
    assert old is not None
    assert old.status is ProposalStatus.DISCARDED
    sets = (await session.scalars(select(ChangeLog.change_set_id).distinct())).all()
    assert sets == [reply.change_set_id]  # the whole schedule is one undo


@pytest.mark.parametrize(
    ("parsed", "message"),
    [
        ({"entries": []}, "no weekly entries"),
        (
            {
                "entries": [
                    {
                        "kind": "class",
                        "title": "X",
                        "weekdays": ["funday"],
                        "start_time": "09:00",
                        "end_time": "10:00",
                    }
                ]
            },
            "could not read",
        ),
    ],
)
async def test_unreadable_parses_are_errors(
    session: AsyncSession, parsed: dict[str, Any], message: str
) -> None:
    ctx = context(session, "onboarding")
    ctx.llm = parser_llm(parsed)

    result = await run_tool("propose_schedule", {"text": "?"}, ctx)

    assert message in result["error"]
    assert await count(session, Proposal) == 0


# --- conversation flow -----------------------------------------------------------------


async def test_onboarding_conversation(session: AsyncSession) -> None:
    llm = ScriptedLLM()
    yaver = coordinator(llm)

    # 1) start: the setup assistant greets
    llm.add("onboarding", say("Merhaba! Dönem ne zaman başlıyor, ne zaman bitiyor?"))
    first = await yaver.handle(
        session, "Kuruluma başlayalım", now=NOW, mode=ConversationMode.ONBOARDING
    )
    conversation_id = first.conversation_id
    assert first.speaker == "onboarding"

    # 2) term
    llm.add(
        "onboarding",
        calls(
            (
                "add_term",
                {"name": "2026-2027 Güz", "start_date": "2026-09-28", "end_date": "2027-01-08"},
            )
        ),
        say("Kaydettim. Ders programını yazar mısın?"),
    )
    await yaver.handle(
        session, "28 eylülde başladı 8 ocakta bitiyor", conversation_id=conversation_id, now=NOW
    )

    # 3) pasted schedule -> table, nothing saved yet
    proposal_ids: list[int] = []

    def show_table(request: LLMRequest) -> LLMResponse:
        result = last_result(request)
        proposal_ids.append(result["proposal_id"])
        return say(result["table"] + "\n\nDoğru mu?")

    llm.add("onboarding", call("propose_schedule", text=LONG_TABLE), show_table)
    llm.add("schedule_parser", call("schedule_entries", **PARSED))
    shown = await yaver.handle(session, LONG_TABLE, conversation_id=conversation_id, now=NOW)
    assert "| Pazartesi | 09:00-11:00 |" in shown.reply
    assert await count(session, RecurringBlock) == 0
    assert shown.change_set_id is None

    # 4) "evet" -> applied as one change set, then finished
    llm.add(
        "onboarding",
        lambda request: call("apply_proposal", proposal_id=proposal_ids[0]),
        call("finish_onboarding"),
        say("Hazırız! Değiştirmek istediğin her şeyi bana yazman yeterli."),
    )
    done = await yaver.handle(session, "evet", conversation_id=conversation_id, now=NOW)
    assert await count(session, RecurringBlock) == 3
    entries = (
        await session.scalars(
            select(ChangeLog).where(ChangeLog.change_set_id == done.change_set_id)
        )
    ).all()
    assert {e.entity for e in entries} == {"courses", "recurring_blocks"}
    assert {e.agent_id for e in entries} == {"onboarding"}
    conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    await session.refresh(conversation)
    assert conversation.mode is ConversationMode.CHAT

    # 5) after setup the same conversation goes to the normal team
    llm.add("yaver", say("Rica ederim!"))
    after = await yaver.handle(session, "teşekkürler", conversation_id=conversation_id, now=NOW)
    assert after.speaker == "yaver"
    llm.assert_done()
