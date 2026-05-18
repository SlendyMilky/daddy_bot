import logging

from aiogram import Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

# Substrings of TelegramBadRequest messages we treat as benign (no user-facing reply, debug-only log).
_BENIGN_BAD_REQUEST_SUBSTRINGS = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "query is too old",
    "message can't be deleted",
    "message_id_invalid",
)


def register_error_handlers(dp: Dispatcher) -> None:
    router = Router()

    @router.errors()
    async def on_error(event: ErrorEvent) -> bool:
        exc = event.exception
        if isinstance(exc, TelegramBadRequest):
            msg = str(exc).lower()
            if any(needle in msg for needle in _BENIGN_BAD_REQUEST_SUBSTRINGS):
                logger.debug("Benign TelegramBadRequest ignored: %s", exc)
                return True

        logger.exception("Unhandled update error: %s", exc)
        update = event.update
        message = getattr(update, "message", None)
        if message:
            try:
                await message.answer(
                    "Un bug est passe par la. Reessaie dans quelques instants.",
                    disable_notification=True,
                )
            except Exception as reply_exc:  # noqa: BLE001
                logger.debug("Failed to send error reply: %s", reply_exc)
        return True

    dp.include_router(router)
