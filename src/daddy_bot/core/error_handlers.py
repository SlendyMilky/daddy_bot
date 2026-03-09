import logging

from aiogram import Dispatcher, Router
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)


def register_error_handlers(dp: Dispatcher) -> None:
    router = Router()

    @router.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("Unhandled update error: %s", event.exception)
        update = event.update
        message = getattr(update, "message", None)
        if message:
            await message.answer(
                "Un bug est passe par la. Reessaie dans quelques instants.",
                disable_notification=True,
            )
        return True

    dp.include_router(router)
