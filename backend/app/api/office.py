"""The office's live state: a snapshot for the first load, then server-sent events.

GET /api/office/stream sends, in order:
  retry: 3000                      EventSource reconnect delay
  data: {"type": "snapshot", ...}  every employee with its state (same as /snapshot)
  data: {"type": "state", "employee_id", "activity", "task", "tool", "meeting_with",
         "needs_user", "needs_user_reason", "since", "ts"}       on every change
  data: {"type": "note", "employee_id", "note": {id, content, created_at}, "ts"}
  data: {"type": "ping", "ts"}     every 15 s: keeps proxies from closing the stream and lets
                                   the browser notice a dead one (comments never reach
                                   EventSource; a proxy may keep a stream open after the API died)
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.chat import SSE_HEADERS, sse
from app.office.state import Office, get_office

router = APIRouter(tags=["office"])
PING_SECONDS = 15.0


@router.get("/office/snapshot")
async def snapshot(office: Office = Depends(get_office)) -> dict[str, Any]:
    return await office.snapshot()


async def office_events(office: Office, ping_seconds: float = PING_SECONDS) -> AsyncGenerator[str]:
    # Subscribed before the snapshot is read: no change can fall between the two.
    async with office.hub.subscribe() as queue:
        yield "retry: 3000\n\n"
        yield sse({"type": "snapshot", **await office.snapshot()})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), ping_seconds)
            except TimeoutError:
                yield sse({"type": "ping", "ts": office.clock().isoformat()})
                continue
            yield sse(event)


@router.get("/office/stream")
async def stream(office: Office = Depends(get_office)) -> StreamingResponse:
    return StreamingResponse(
        office_events(office), media_type="text/event-stream", headers=SSE_HEADERS
    )
