from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from daddy_bot.utils.patterns import (
    INSTAGRAM_CALLBACK_RE,
    INSTAGRAM_RE,
    TIKTOK_CALLBACK_RE,
    TIKTOK_RE,
    TWITTER_CALLBACK_RE,
    TWITTER_RE,
)

router = Router(name="social_stub")


async def _send_social_stub(message: Message, name: str) -> None:
    await message.answer(
        f"Le module `{name}` est detecte mais pas encore migre depuis n8n.",
        disable_notification=True,
    )


@router.message(F.text.func(lambda value: bool(value and TWITTER_RE.search(value))))
async def on_twitter(message: Message) -> None:
    await _send_social_stub(message, "twitter/x")


@router.callback_query(F.data.func(lambda value: bool(value and TWITTER_CALLBACK_RE.search(value))))
async def on_twitter_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await _send_social_stub(callback.message, "twitter/x")
    await callback.answer()


@router.message(F.text.func(lambda value: bool(value and TIKTOK_RE.search(value))))
async def on_tiktok(message: Message) -> None:
    await _send_social_stub(message, "tiktok")


@router.callback_query(F.data.func(lambda value: bool(value and TIKTOK_CALLBACK_RE.search(value))))
async def on_tiktok_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await _send_social_stub(callback.message, "tiktok")
    await callback.answer()


@router.message(F.text.func(lambda value: bool(value and INSTAGRAM_RE.search(value))))
async def on_instagram(message: Message) -> None:
    await _send_social_stub(message, "instagram")


@router.callback_query(F.data.func(lambda value: bool(value and INSTAGRAM_CALLBACK_RE.search(value))))
async def on_instagram_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await _send_social_stub(callback.message, "instagram")
    await callback.answer()
