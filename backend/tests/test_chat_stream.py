"""Y3: the chat stream never goes silent - pings while the answer is slow, and an answer that
takes too long ends with error "timeout" (the coordinator is cancelled: nothing is saved)."""

import asyncio
import json
from typing import Any

from app.agent.coordinator import ChatReply
from app.agent.loop import Emit
from app.api.chat import stream_reply


async def events_of(response: Any) -> list[dict[str, Any]]:
    out = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode()
        out += [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    return out


async def test_a_slow_answer_gets_pings_then_done() -> None:
    async def answer(emit: Emit) -> ChatReply:
        await emit({"type": "turn", "agent_id": "yaver"})
        await asyncio.sleep(0.25)
        return ChatReply(1, "tamam", "yaver", None, [], [], [])

    events = await events_of(stream_reply(answer, timeout=5, ping=0.05))

    kinds = [e["type"] for e in events]
    assert kinds[0] == "turn"
    assert kinds[-1] == "done"
    assert kinds.count("ping") >= 2


async def test_an_answer_past_the_deadline_is_cancelled_with_timeout() -> None:
    cancelled = asyncio.Event()

    async def answer(emit: Emit) -> ChatReply:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()  # the coordinator rolls back here
            raise
        raise AssertionError("not reached")

    events = await events_of(stream_reply(answer, timeout=0.2, ping=0.05))

    assert events[-1] == {"type": "error", "code": "timeout"}
    assert cancelled.is_set()
