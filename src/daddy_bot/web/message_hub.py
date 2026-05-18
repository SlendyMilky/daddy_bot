"""In-memory pub/sub hub for live Telegram message relay to admin chat UI.

Messages are never persisted to disk. The ring buffer is purely in-memory
and is cleared on bot restart. Each connected SSE client subscribes to a
per-chat queue and receives messages in real time.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict, deque
from collections.abc import AsyncGenerator

_BUFFER_SIZE = 50  # Recent messages kept per chat (in-memory only)


class MessageHub:
    def __init__(self) -> None:
        self._subs: dict[int, list[asyncio.Queue[dict | None]]] = defaultdict(list)
        self._buffer: dict[int, deque[dict]] = defaultdict(lambda: deque(maxlen=_BUFFER_SIZE))

    def has_subscribers(self, chat_id: int) -> bool:
        return bool(self._subs.get(chat_id))

    def get_recent(self, chat_id: int) -> list[dict]:
        """Return buffered messages for the initial page load."""
        return list(self._buffer[chat_id])

    def subscribe(self, chat_id: int) -> asyncio.Queue[dict | None]:
        q: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=200)
        self._subs[chat_id].append(q)
        return q

    def unsubscribe(self, chat_id: int, q: asyncio.Queue[dict | None]) -> None:
        with contextlib.suppress(ValueError):
            self._subs[chat_id].remove(q)

    async def publish(self, chat_id: int, msg: dict) -> None:
        self._buffer[chat_id].append(msg)
        for q in list(self._subs.get(chat_id, [])):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(msg)

    async def iter_messages(
        self,
        chat_id: int,
        q: asyncio.Queue[dict | None],
    ) -> AsyncGenerator[dict, None]:
        """Async-generator that yields messages until the queue receives None (sentinel)."""
        while True:
            msg = await q.get()
            if msg is None:
                break
            yield msg


# Process-wide singleton shared by aiogram middleware and FastAPI routes
hub = MessageHub()
