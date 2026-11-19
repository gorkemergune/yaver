"""Live: real screenshots (examples/screenshots/*.png, made-up data) read by Claude.

docker compose exec api pytest -m live -k vision -s
"""

import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.coordinator import Coordinator
from app.agent.team import get_team
from app.agent.vision import ImageInput, read_images
from app.config import Settings, get_settings
from app.db.models import Attachment, Event, LlmUsage, Proposal
from app.db.models.enums import ProposalKind
from app.llm.router import LLMRouter, build_router, env_value
from app.llm.types import ImagePart
from app.llm.usage import DbUsageStore
from app.services.images import process_image, store_image
from tests.db.test_agent_tools import context

pytestmark = pytest.mark.live

SHOTS = Path(__file__).resolve().parents[3] / "examples" / "screenshots"
NOW = dt.datetime(2026, 11, 23, 7, 0, tzinfo=dt.UTC)  # Monday 10:00 Istanbul


@pytest.fixture
async def router(session: AsyncSession) -> AsyncIterator[LLMRouter]:
    if not env_value(get_settings(), "ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    if not SHOTS.is_dir():
        pytest.skip("examples/ not mounted")
    router = build_router(store=DbUsageStore(async_sessionmaker(session.bind)))
    yield router
    await router.aclose()


def screenshot(name: str) -> ImagePart:
    image = process_image((SHOTS / name).read_bytes(), max_bytes=20 * 1024 * 1024, max_edge=1600)
    return ImagePart(image.mime, image.data)


async def usage(session: AsyncSession) -> list[LlmUsage]:
    return list((await session.scalars(select(LlmUsage).order_by(LlmUsage.id))).all())


async def test_timetable_screenshot_becomes_a_schedule_proposal(
    session: AsyncSession, router: LLMRouter
) -> None:
    ctx = context(session, "yaver")
    ctx.llm = router

    text = await read_images(ctx, [ImageInput(1, screenshot("schedule.png"))])

    print(f"\n{text}")
    rows = await usage(session)
    for row in rows:
        print(f"  {row.purpose:<15} {row.tier:<9} {row.provider}/{row.model} ${row.cost_usd}")
    assert "öneri #" in text
    assert [(r.purpose, r.provider) for r in rows if not r.error] == [
        ("image_read", "anthropic"),
        ("schedule_image", "anthropic"),
    ]
    assert "sonnet" in next(r for r in rows if r.purpose == "schedule_image").model
    assert all(r.provider != "groq" for r in rows)
    proposal = await session.scalar(select(Proposal))
    assert proposal is not None
    assert proposal.kind is ProposalKind.SCHEDULE
    found = {
        (day, entry["start_time"][:5], entry["kind"])
        for entry in proposal.entries
        for day in entry["weekdays"]
    }
    print(f"  slots: {sorted(found)}")
    assert ("monday", "09:00", "class") in found  # MATH221
    assert ("wednesday", "13:00", "lab") in found  # EE211 lab
    assert ("thursday", "15:00", "lab") in found or ("thursday", "15:00", "class") in found
    assert ("friday", "11:00", "class") in found  # HUM201
    assert len(found) == 9


async def test_exam_notice_end_to_end(
    session: AsyncSession, router: LLMRouter, tmp_path: Path
) -> None:
    settings = Settings(upload_dir=tmp_path)
    yaver = Coordinator(router, get_team(), settings)
    raw = (SHOTS / "exam_notice.png").read_bytes()
    image = process_image(raw, max_bytes=20 * 1024 * 1024, max_edge=1600)
    attachment = Attachment(
        path=store_image(image, tmp_path, NOW),
        mime=image.mime,
        width=image.width,
        height=image.height,
        size_bytes=len(image.data),
        sha256=image.sha256,
    )
    session.add(attachment)
    await session.commit()

    first = await yaver.handle(
        session, "bunu takvime ekler misin", now=NOW, attachment_ids=[attachment.id]
    )
    print(f"\n1) {first.reply}")
    assert await session.scalar(select(Event)) is None  # nothing before "evet"
    proposal = await session.scalar(select(Proposal))
    assert proposal is not None
    assert proposal.kind is ProposalKind.EVENTS
    print(f"  proposal: {proposal.entries} unclear={proposal.unclear}")
    assert proposal.entries[0]["date"] == "2026-11-27"
    assert proposal.entries[0]["start_time"][:5] == "10:00"

    second = await yaver.handle(session, "evet", conversation_id=first.conversation_id, now=NOW)
    print(f"2) {second.reply}")
    for entry in second.trace:
        print(f"  call [{entry['agent_id']}] {entry['tool']}({entry['arguments']})")
    event = await session.scalar(select(Event))
    assert event is not None
    assert event.start_at == dt.datetime(2026, 11, 27, 7, 0, tzinfo=dt.UTC)  # 10:00 Istanbul
    assert second.change_set_id is not None
    assert "ee211" in event.title.lower(), event.title
    assert "öneri #" not in first.reply.lower()  # internal ids stay internal
    rows = await usage(session)
    total = sum(r.cost_usd for r in rows)
    print(f"  LLM calls: {len(rows)}, cost ${total}")
    print("  " + ", ".join(f"{r.purpose}:{r.provider}/{r.model}" for r in rows))
    image_rows = [r for r in rows if r.purpose.startswith(("image_", "schedule_image"))]
    assert all(r.provider == "anthropic" for r in image_rows)
