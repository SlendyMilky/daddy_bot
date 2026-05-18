from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

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

logger = logging.getLogger(__name__)


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
