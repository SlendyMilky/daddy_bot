"""Admin logs screen: in-memory ring buffer + SSE stream endpoint."""
from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from daddy_bot.web.deps import RequireOwner

logger = logging.getLogger(__name__)
router = APIRouter()

_RING_BUFFER_SIZE = 1000
log_buffer: collections.deque[dict] = collections.deque(maxlen=_RING_BUFFER_SIZE)
_subscribers: list[asyncio.Queue[dict]] = []


class RingBufferHandler(logging.Handler):
    """Logging handler that pushes records to the ring buffer and SSE subscribers."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
            "time": record.created,
        }
        log_buffer.append(entry)
        for q in list(_subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(entry)


_handler: RingBufferHandler | None = None


def install_log_handler() -> None:
    global _handler
    if _handler is not None:
        return
    _handler = RingBufferHandler()
    _handler.setLevel(logging.DEBUG)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    logging.getLogger().addHandler(_handler)


@router.get("", response_class=HTMLResponse)
async def logs_page(request: Request, user_id: RequireOwner) -> HTMLResponse:
    recent = list(log_buffer)[-200:]
    return request.app.state.templates.TemplateResponse(
        "logs.html",
        {"request": request, "user_id": user_id, "recent_logs": recent},
    )


@router.get("/stream")
async def logs_stream(request: Request, user_id: RequireOwner) -> StreamingResponse:
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
    _subscribers.append(queue)

    async def generator() -> AsyncGenerator[bytes, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=15.0)
                    payload = json.dumps(entry)
                    yield f"data: {payload}\n\n".encode()
                except TimeoutError:
                    yield b"data: {\"keep\":\"alive\"}\n\n"
        finally:
            if queue in _subscribers:
                _subscribers.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
