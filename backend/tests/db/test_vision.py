"""Images in the chat: read in code (Claude), shown as a proposal, written only after "evet"."""

import datetime as dt
import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coordinator import Coordinator
from app.agent.tools import run_tool
from app.agent.vision import resolve_notice_date
from app.config import Settings
from app.core.time_resolver import DEFAULT_CLOCK
from app.db.models import Attachment, ChangeLog, Event, Message, Proposal, RecurringBlock
from app.db.models.enums import MessageRole, ProposalKind, ProposalStatus
from app.llm.router import LLMUnavailableError
from app.llm.types import LLMRequest, LLMResponse
from app.services.images import process_image, store_image
from tests.agent_fakes import NOW, ScriptedLLM, call, example_team, say
from tests.db.test_agent_tools import context
from tests.db.test_onboarding import PARSED

ANNOUNCEMENT: dict[str, Any] = {
    "kind": "event",
    "summary": "EE211 ara sınav duyurusu",
    "events": [
        {
            "kind": "exam",
            "title": "EE211 Ara Sınav",
            "course": "EE211",
            "date_text": "27 Kasım Cuma",
            "start_time": "10:00",
            "end_time": "12:00",
            "location": "B201",
        },
        {"kind": "quiz", "title": "Quiz 2", "date_text": "?? Aralık"},
    ],
    "unclear": ["Salon: E? (silik)"],
}


async def stored_image(session: AsyncSession, upload_dir: Path) -> Attachment:
    out = io.BytesIO()
    Image.new("RGB", (320, 200), (240, 240, 240)).save(out, format="PNG")
    image = process_image(out.getvalue(), max_bytes=10**7, max_edge=1600)
    attachment = Attachment(
        path=store_image(image, upload_dir, NOW),
        mime=image.mime,
        width=image.width,
        height=image.height,
        size_bytes=len(image.data),
        sha256=image.sha256,
    )
    session.add(attachment)
    await session.flush()
    return attachment


def yaver_with_uploads(llm: ScriptedLLM, upload_dir: Path) -> Coordinator:
    return Coordinator(llm, example_team(), Settings(_env_file=None, upload_dir=upload_dir))


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def last_user_text(request: LLMRequest) -> str:
    return next(m.content for m in reversed(request.messages) if m.role == "user")


async def test_schedule_photo_is_proposed_then_applied_after_yes(
    session: AsyncSession, tmp_path: Path
) -> None:
    llm = ScriptedLLM()
    yaver = yaver_with_uploads(llm, tmp_path)
    attachment = await stored_image(session, tmp_path)
    seen: list[str] = []

    def show_table(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("Programını şöyle okudum: ... Ekleyeyim mi?")

    llm.add(
        "image_reader",
        call("image_contents", kind="schedule", summary="Haftalık ders programı"),
        call("schedule_entries", **PARSED),
    )
    llm.add("yaver", show_table)
    first = await yaver.handle(session, "", now=NOW, attachment_ids=[attachment.id])

    # read by Haiku (what is it), then Sonnet (the timetable); the image itself went along
    assert llm.purposes[:2] == ["image_read", "schedule_image"]
    image_request = llm.requests[0][1]
    assert image_request.messages[0].images[0].media_type == "image/png"
    assert seen[0].startswith("(Yalnızca görsel gönderdim.)")
    assert "öneri #1, henüz kaydedilmedi" in seen[0]
    assert "| Pazartesi | 09:00-11:00 | Linear Algebra (MATH221) | Ders | B204 |" in seen[0]
    assert "Belirsiz (tahmin edilmedi): Cuma ?? Fizik" in seen[0]
    assert await count(session, RecurringBlock) == 0  # nothing written before "evet"
    assert first.change_set_id is None
    proposal = await session.get(Proposal, 1)
    assert proposal is not None
    assert (proposal.kind, proposal.status) == (ProposalKind.SCHEDULE, ProposalStatus.PENDING)
    user_message = await session.scalar(select(Message).where(Message.role == MessageRole.USER))
    assert user_message is not None
    assert user_message.content == ""
    assert user_message.context is not None
    assert "öneri #1" in user_message.context
    await session.refresh(attachment)
    assert attachment.message_id == user_message.id

    # "evet": the open proposal (conversation.pending_action) is applied by the code, the
    # coordinator only reports it (one answer, no tool turn)
    llm.add("yaver", say("Programını ekledim."))
    done = await yaver.handle(session, "evet", conversation_id=first.conversation_id, now=NOW)
    assert [(t["tool"], t["arguments"], t.get("bound")) for t in done.trace] == [
        ("apply_proposal", {"proposal_id": 1}, True)
    ]

    assert await count(session, RecurringBlock) == 3
    sets = (await session.scalars(select(ChangeLog.change_set_id).distinct())).all()
    assert sets == [done.change_set_id]  # one "Geri al" for the whole schedule
    await session.refresh(proposal)
    assert proposal.status is ProposalStatus.APPLIED
    llm.assert_done()


async def test_announcement_dates_are_resolved_in_code_and_unclear_ones_listed(
    session: AsyncSession, tmp_path: Path
) -> None:
    llm = ScriptedLLM()
    yaver = yaver_with_uploads(llm, tmp_path)
    attachment = await stored_image(session, tmp_path)
    seen: list[str] = []

    def show(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("...")

    llm.add("image_reader", call("image_contents", **ANNOUNCEMENT))
    llm.add("yaver", show)
    await yaver.handle(session, "bunu ekler misin", now=NOW, attachment_ids=[attachment.id])

    assert llm.purposes[0] == "image_read"  # a notice: Haiku only, no Sonnet call
    assert "schedule_image" not in llm.purposes
    assert seen[0].startswith("bunu ekler misin\n\n[Görsel 1: EE211 ara sınav duyurusu")
    assert "| 27 Kasım Cuma | 10:00-12:00 | EE211 Ara Sınav | Sınav | B201 |" in seen[0]
    assert "Salon: E? (silik)" in seen[0]
    assert "Quiz 2: tek bir gün değil (?? Aralık)" in seen[0]  # a month is not a date
    proposal = await session.get(Proposal, 1)
    assert proposal is not None
    assert proposal.kind is ProposalKind.EVENTS
    assert len(proposal.entries) == 1

    # the same message may not add it directly (it would skip the confirmation)
    same_message = context(session, "yaver")
    same_message.new_proposals.add(1)
    direct = await run_tool(
        "add_event",
        {"kind": "exam", "title": "EE211 Ara Sınav", "date": "2026-11-27", "start_time": "10:00"},
        same_message,
    )
    assert "turned into a proposal" in direct["error"]
    assert await count(session, Event) == 0

    ctx = context(session, "agenda")  # the next message: "evet"
    applied = await run_tool("apply_proposal", {"proposal_id": 1}, ctx)
    again = await run_tool("apply_proposal", {"proposal_id": 1}, ctx)

    event = await session.scalar(select(Event))
    assert event is not None
    assert event.start_at == dt.datetime(2026, 11, 27, 7, 0, tzinfo=dt.UTC)  # 10:00 Istanbul
    assert event.notes == "Ders: EE211"  # no such course yet: kept as a note, not invented
    assert event.title == "EE211 Ara Sınav"  # course already in the title: not doubled
    assert len(applied["events_created"]) == 1
    assert "already applied" in again["error"]


async def test_no_vision_model_left_is_said_not_crashed(
    session: AsyncSession, tmp_path: Path
) -> None:
    llm = ScriptedLLM()
    yaver = yaver_with_uploads(llm, tmp_path)
    attachment = await stored_image(session, tmp_path)
    seen: list[str] = []

    def unavailable(request: LLMRequest) -> LLMResponse:
        raise LLMUnavailableError(["fast: provider groq cannot read images"])

    def show(request: LLMRequest) -> LLMResponse:
        seen.append(last_user_text(request))
        return say("Görseli şu an okuyamıyorum.")

    llm.add("image_reader", unavailable)
    llm.add("yaver", show)
    await yaver.handle(session, "", now=NOW, attachment_ids=[attachment.id])

    assert "[Görsel 1 okunamadı" in seen[0]
    assert await count(session, Proposal) == 0


@pytest.mark.parametrize(
    ("text", "day", "problem"),
    [
        ("27 Kasım Cuma 10:00", dt.date(2026, 11, 27), ""),
        ("27.11.2026", dt.date(2026, 11, 27), ""),
        ("28 Kasım Cuma", None, "gün adı tarihle uyuşmuyor"),  # 28 Kasım is a Saturday
        ("Aralık", None, "tek bir gün değil"),
        ("", None, "tarih okunamadı"),
    ],
)
def test_notice_dates(text: str, day: dt.date | None, problem: str) -> None:
    class Ctx:
        clock = DEFAULT_CLOCK

    resolution, why = resolve_notice_date(text, dt.date(2026, 11, 23), Ctx())  # type: ignore[arg-type]

    assert (resolution.start if resolution else None) == day
    assert why == problem
