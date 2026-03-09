from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class SlidingWindowRateLimiter:
    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def is_limited(self, user_id: int) -> bool:
        now = time.monotonic()
        user_events = self._events[user_id]
        window_start = now - self.window_seconds

        while user_events and user_events[0] < window_start:
            user_events.popleft()

        if len(user_events) >= self.max_events:
            return True

        user_events.append(now)
        return False


class RateLimitMiddleware(BaseMiddleware):
    def __init__(
        self,
        limiter: SlidingWindowRateLimiter,
        cooldown_message: str,
        owner_ids: set[int] | None = None,
    ):
        self.limiter = limiter
        self.cooldown_message = cooldown_message
        self.owner_ids = owner_ids or set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ):
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None or user_id in self.owner_ids:
            return await handler(event, data)

        if self.limiter.is_limited(user_id):
            if isinstance(event, Message):
                await event.answer(self.cooldown_message, disable_notification=True)
            elif isinstance(event, CallbackQuery):
                await event.answer(self.cooldown_message, show_alert=False)
            return None

        return await handler(event, data)
