import logging
import re

import httpx
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from daddy_bot.utils.patterns import (
    INSTAGRAM_CALLBACK_RE,
    INSTAGRAM_RE,
    TIKTOK_CALLBACK_RE,
    TIKTOK_RE,
    TWITTER_CALLBACK_RE,
    TWITTER_RE,
)

logger = logging.getLogger(__name__)

router = Router(name="social_stub")

_TIKTOK_VM_RE = re.compile(r"https?://vm\.tiktok\.com/\w+", re.IGNORECASE)
_TIKTOK_FULL_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/@\w+/video/\d+[\w\-?=&;_]*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _delete_button(prefix: str, message_id: int, username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Supprimer message original",
            callback_data=f"{prefix} - {message_id} - {username}",
        )
    ]])


async def _handle_delete_callback(callback: CallbackQuery, bot: Bot) -> None:
    data = callback.data or ""

    msg_id_match = re.search(r"[0-9]+", data)
    author_match = re.search(r".* - (.+)$", data)

    if not msg_id_match or not author_match or not callback.message or not callback.from_user:
        await callback.answer()
        return

    message_id = int(msg_id_match.group(0))
    original_author = author_match.group(1).strip()
    requester = callback.from_user.username or ""

    if requester != original_author:
        await callback.answer(
            "⚠️ Bouton utilisable que par l'auteur du message original.",
            show_alert=False,
        )
        return

    try:
        await bot.delete_message(chat_id=callback.message.chat.id, message_id=message_id)
        await callback.answer("Message supprimé.")
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning("Could not delete message %d: %s", message_id, exc)
        await callback.answer(
            "❌ Erreur ❌\n\nJe n'ai pas les droits ou je ne peux pas supprimer le message.",
            show_alert=True,
        )


# ---------------------------------------------------------------------------
# Twitter / X
# ---------------------------------------------------------------------------

def _to_vxtwitter(url: str) -> str:
    return re.sub(r"(?:twitter|x)\.com", "vxtwitter.com", url, flags=re.IGNORECASE)


@router.message(F.text.func(lambda value: bool(value and TWITTER_RE.search(value))))
async def on_twitter(message: Message) -> None:
    text = message.text or ""
    match = TWITTER_RE.search(text)
    if not match or not message.from_user:
        return

    vx_url = _to_vxtwitter(match.group(0))
    username = message.from_user.username or message.from_user.first_name

    await message.answer(
        f"{vx_url}\n\n<i>Envoyé par : {username}</i>",
        parse_mode="HTML",
        reply_markup=_delete_button("Twitter", message.message_id, username),
        disable_notification=False,
    )


@router.callback_query(F.data.func(lambda value: bool(value and TWITTER_CALLBACK_RE.search(value))))
async def on_twitter_callback(callback: CallbackQuery, bot: Bot) -> None:
    await _handle_delete_callback(callback, bot)


# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------

async def _resolve_tiktok_url(short_url: str) -> str:
    """Follow one redirect from a vm.tiktok.com short URL and return the full URL."""
    async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
        try:
            response = await client.get(short_url)
            location = response.headers.get("location", "")
            full_match = _TIKTOK_FULL_RE.search(location)
            if full_match:
                return full_match.group(0)
        except httpx.HTTPError as exc:
            logger.warning("Failed to resolve TikTok short URL %s: %s", short_url, exc)
    return short_url


@router.message(F.text.func(lambda value: bool(value and TIKTOK_RE.search(value))))
async def on_tiktok(message: Message) -> None:
    text = message.text or ""
    match = TIKTOK_RE.search(text)
    if not match or not message.from_user:
        return

    original_url = match.group(0)
    username = message.from_user.username or message.from_user.first_name

    if _TIKTOK_VM_RE.search(original_url):
        full_url = await _resolve_tiktok_url(original_url)
    else:
        canonical = _TIKTOK_FULL_RE.search(original_url)
        full_url = canonical.group(0) if canonical else original_url

    vx_url = re.sub(r"tiktok\.com", "tnktok.com", full_url, flags=re.IGNORECASE)

    await message.answer(
        f"{vx_url}\n\n<i>Envoyé par : {username}</i>",
        parse_mode="HTML",
        reply_markup=_delete_button("Tiktok", message.message_id, username),
        disable_notification=False,
    )


@router.callback_query(F.data.func(lambda value: bool(value and TIKTOK_CALLBACK_RE.search(value))))
async def on_tiktok_callback(callback: CallbackQuery, bot: Bot) -> None:
    await _handle_delete_callback(callback, bot)


# ---------------------------------------------------------------------------
# Instagram (stub)
# ---------------------------------------------------------------------------

async def _send_social_stub(message: Message, name: str) -> None:
    await message.answer(
        f"Le module `{name}` est detecte mais pas encore migre depuis n8n.",
        disable_notification=True,
    )


@router.message(F.text.func(lambda value: bool(value and INSTAGRAM_RE.search(value))))
async def on_instagram(message: Message) -> None:
    await _send_social_stub(message, "instagram")


@router.callback_query(F.data.func(lambda value: bool(value and INSTAGRAM_CALLBACK_RE.search(value))))
async def on_instagram_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await _send_social_stub(callback.message, "instagram")
    await callback.answer()
