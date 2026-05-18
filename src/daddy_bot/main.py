from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import TelegramObject, Update

from daddy_bot.core.config import get_settings
from daddy_bot.core.db import close_connection
from daddy_bot.core.error_handlers import register_error_handlers
from daddy_bot.core.logging import setup_logging
from daddy_bot.core.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter
from daddy_bot.core.router_registry import register_routers
from daddy_bot.db.json_migration import run_auto_migration
from daddy_bot.modules.bibine import run_bibine_scheduler
from daddy_bot.modules.princesse_morning import run_princesse_morning_scheduler
from daddy_bot.web.app import create_admin_app
from daddy_bot.web.message_hub import hub

logger = logging.getLogger(__name__)


class _MessageRelayMiddleware:
    """Outer middleware that publishes incoming Telegram messages to the admin chat hub.

    Only activates when at least one admin SSE client is connected to that chat,
    so there is zero overhead otherwise.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update) and event.message:
            msg = event.message
            chat_id = msg.chat.id
            if hub.has_subscribers(chat_id):
                from_user = msg.from_user
                sender_name = "Unknown"
                if from_user:
                    if from_user.username:
                        sender_name = f"@{from_user.username}"
                    else:
                        sender_name = from_user.first_name or "Unknown"

                text = msg.text or msg.caption or ""
                media_type: str | None = None
                if msg.photo:
                    media_type = "photo"
                elif msg.sticker:
                    media_type = "sticker"
                    text = msg.sticker.emoji or ""
                elif msg.voice:
                    media_type = "voice"
                elif msg.video:
                    media_type = "video"
                elif msg.document:
                    media_type = "document"
                elif msg.audio:
                    media_type = "audio"

                payload: dict[str, Any] = {
                    "message_id": msg.message_id,
                    "sender": sender_name,
                    "sender_id": from_user.id if from_user else None,
                    "text": text,
                    "media_type": media_type,
                    "date": datetime.fromtimestamp(msg.date.timestamp(), tz=UTC).isoformat()
                    if msg.date
                    else datetime.now(tz=UTC).isoformat(),
                    "is_bot": from_user.is_bot if from_user else False,
                }
                await hub.publish(chat_id, payload)

        return await handler(event, data)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _log_task_result(task: asyncio.Task) -> None:
    """Done-callback that logs any non-cancellation exception raised by background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None and not isinstance(exc, asyncio.CancelledError):
        logger.exception("Background task %s crashed", task.get_name(), exc_info=exc)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    def _handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            # Windows: add_signal_handler is not supported for the proactor loop.
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, lambda *_: _handler())


async def start_bot() -> None:
    setup_logging()
    settings = get_settings()

    try:
        summary = await run_auto_migration(_project_root())
        if summary:
            logger.info("JSON migration summary: %s", summary)
    except Exception:
        logger.exception("Auto migration failed at boot; continuing with empty tables.")

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
    dp.update.outer_middleware(_MessageRelayMiddleware())

    register_routers(dp)
    register_error_handlers(dp)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    _install_signal_handlers(loop, stop_event)

    web_server: uvicorn.Server | None = None
    if settings.admin_web_enabled:
        admin_app = create_admin_app(bot=bot, settings=settings)
        web_config = uvicorn.Config(
            admin_app,
            host="0.0.0.0",
            port=settings.admin_web_port,
            log_config=None,
        )
        web_server = uvicorn.Server(web_config)

    logger.info("Daddy bot started.")
    scheduler_task = asyncio.create_task(run_bibine_scheduler(bot), name="bibine_scheduler")
    princesse_scheduler_task = asyncio.create_task(
        run_princesse_morning_scheduler(bot), name="princesse_scheduler"
    )
    scheduler_task.add_done_callback(_log_task_result)
    princesse_scheduler_task.add_done_callback(_log_task_result)

    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        name="polling",
    )
    polling_task.add_done_callback(_log_task_result)

    tasks: list[asyncio.Task] = [polling_task, scheduler_task, princesse_scheduler_task]
    if web_server is not None:
        web_task = asyncio.create_task(web_server.serve(), name="web_server")
        web_task.add_done_callback(_log_task_result)
        tasks.append(web_task)
    else:
        web_task = None

    stop_wait = asyncio.create_task(stop_event.wait(), name="stop_wait")

    try:
        done, _ = await asyncio.wait(
            {polling_task, stop_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_wait in done and not polling_task.done():
            logger.info("Stopping polling and schedulers...")
            await dp.stop_polling()
    finally:
        if web_server is not None:
            web_server.should_exit = True
        all_tasks = tasks + [stop_wait]
        for task in all_tasks:
            if not task.done():
                task.cancel()
        for task in all_tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        with contextlib.suppress(Exception):
            await bot.session.close()
        await close_connection()


def run() -> None:
    asyncio.run(start_bot())


if __name__ == "__main__":
    run()
