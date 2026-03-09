import logging
from datetime import datetime

import httpx
from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from daddy_bot.utils.patterns import ERIKA_RE, PEUR_RE, QUOI_RE, SHALOM_RE, WOMEN_RE

logger = logging.getLogger(__name__)

router = Router(name="auto_triggers")

_ERIKA_URL = "https://www.myinstants.com/media/sounds/erikaaaa_aIVbt8n.mp3"
_ERIKA_HARDBASS_URL = "https://www.myinstants.com/media/sounds/erika-german-song-remix.mp3"


@router.message(F.text.func(lambda value: bool(value and ERIKA_RE.search(value))))
async def on_erika(message: Message) -> None:
    text = message.text or ""
    is_hardbass = "hardbass" in text.lower()

    url = _ERIKA_HARDBASS_URL if is_hardbass else _ERIKA_URL
    caption = "<i>C'était le vrai bon temps...</i>" if is_hardbass else "<i>C'était le bon temps...</i>"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)
            response.raise_for_status()
            audio_data = response.content
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch Erika audio from %s: %s", url, exc)
        return

    await message.reply_audio(
        audio=BufferedInputFile(audio_data, filename="erika.mp3"),
        caption=caption,
        parse_mode="HTML",
        disable_notification=True,
    )


@router.message(F.text.func(lambda value: bool(value and SHALOM_RE.search(value))))
async def on_shalom(message: Message) -> None:
    await message.answer("Shalom.", disable_notification=True)


@router.message(F.location)
async def on_location(message: Message) -> None:
    await message.answer("Localisation recue. Module localisation en migration.", disable_notification=True)


@router.message(F.text.func(lambda value: bool(value and QUOI_RE.search(value))))
async def on_quoi(message: Message) -> None:
    await message.answer("Feur.", disable_notification=True)


@router.message(F.text.func(lambda value: bool(value and PEUR_RE.search(value))))
async def on_peur(message: Message) -> None:
    await message.answer("Bleue.", disable_notification=True)


@router.message(F.text.func(lambda value: bool(value and WOMEN_RE.search(value))))
async def on_women(message: Message) -> None:
    await message.answer("Women module en migration.", disable_notification=True)


@router.message(
    F.sticker.emoji.func(lambda value: bool(value and "⏰" in value))
    | F.sticker.set_name.func(lambda value: bool(value and "suisse52" in value))
)
async def on_heure_sticker(message: Message) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    await message.answer(f"Il est {now}.", disable_notification=True)


@router.callback_query(F.data == "timenowplease")
async def on_heure_callback(callback: CallbackQuery) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    if callback.message:
        await callback.message.answer(f"Il est {now}.", disable_notification=True)
    await callback.answer()
