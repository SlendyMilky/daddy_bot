from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from daddy_bot.core.config import get_settings
from daddy_bot.core.error_handlers import register_error_handlers
from daddy_bot.core.logging import setup_logging
from daddy_bot.core.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter
from daddy_bot.core.router_registry import register_routers


async def start_bot() -> None:
    setup_logging()
    settings = get_settings()
    logger = logging.getLogger(__name__)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    limiter = SlidingWindowRateLimiter(
        max_events=settings.rate_limit_max_events,
        window_seconds=settings.rate_limit_window_seconds,
    )
    dp.update.middleware(
        RateLimitMiddleware(
            limiter=limiter,
            cooldown_message=settings.rate_limit_cooldown_message,
            owner_ids=settings.owner_id_set(),
        )
    )

    register_routers(dp)
    register_error_handlers(dp)

    logger.info("Daddy bot started.")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def run() -> None:
    asyncio.run(start_bot())


if __name__ == "__main__":
    run()
