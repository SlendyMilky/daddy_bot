import asyncio
import contextlib
import time

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.enums import ChatAction
from aiogram.types import Message

from daddy_bot.core.config import get_settings
from daddy_bot.services.openai_service import OpenAIService

router = Router(name="start")
settings = get_settings()
openai_service = OpenAIService(api_key=settings.openai_api_key, model=settings.openai_start_model)


async def _typing_loop(message: Message) -> None:
    while True:
        await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
        await asyncio.sleep(4)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    typing_task = asyncio.create_task(_typing_loop(message))
    full_text = ""
    last_sent = "Daddy ecrit..."
    last_edit_at = 0.0
    sent = await message.reply("Daddy ecrit...", disable_notification=True, parse_mode=None)

    try:
        async for delta in openai_service.stream_start_message():
            full_text += delta
            preview = (full_text.strip() or openai_service.fallback_start_message())[:4000]
            now = time.monotonic()

            if preview != last_sent and (now - last_edit_at) >= 0.8:
                try:
                    await sent.edit_text(preview, parse_mode=None)
                    last_sent = preview
                    last_edit_at = now
                except Exception:
                    break
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task

    final_text = (full_text.strip() or openai_service.fallback_start_message())[:4000]
    if final_text != last_sent:
        try:
            await sent.edit_text(final_text, parse_mode=None)
        except Exception:
            await message.reply(final_text, disable_notification=True, parse_mode=None)
