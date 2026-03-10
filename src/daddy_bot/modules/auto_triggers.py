import asyncio
import logging
import random
from datetime import datetime
from pathlib import Path

import httpx
from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReactionTypeEmoji,
)

from daddy_bot.core.config import get_settings
from daddy_bot.utils.patterns import ERIKA_RE, PEUR_RE, QUOI_RE, SHALOM_RE, WOMEN_RE

logger = logging.getLogger(__name__)

router = Router(name="auto_triggers")

_ERIKA_DIR = Path(__file__).parents[3] / "assets" / "erika"


@router.message(F.text.func(lambda value: bool(value and ERIKA_RE.search(value))))
async def on_erika(message: Message) -> None:
    text = message.text or ""
    is_hardbass = "hardbass" in text.lower()

    audio_file = _ERIKA_DIR / ("erika_hard_bass.mp3" if is_hardbass else "erika.mp3")
    caption = "<i>C'était le vrai bon temps...</i>" if is_hardbass else "<i>C'était le bon temps...</i>"

    await message.reply_audio(
        audio=FSInputFile(audio_file),
        caption=caption,
        parse_mode="HTML",
        disable_notification=True,
    )


_SHALOM_DIR = Path(__file__).parents[3] / "assets" / "shalom"


@router.message(F.text.func(lambda value: bool(value and SHALOM_RE.search(value))))
async def on_shalom(message: Message) -> None:
    is_friday = datetime.now().weekday() == 4  # Monday=0, Friday=4

    await message.reply(
        "Shalom mon frère ✡️",
        disable_notification=True,
        parse_mode="HTML",
    )

    if not is_friday:
        await message.answer_sticker(
            sticker=FSInputFile(_SHALOM_DIR / "gigajew.webp"),
            disable_notification=True,
        )
        return

    # Friday: full Shabbat sequence with random delays
    await asyncio.sleep(random.uniform(1, 6))
    await message.answer(
        "Wait wait wait... on est vendredi ?",
        disable_notification=True,
        parse_mode="HTML",
    )

    await asyncio.sleep(random.uniform(1, 6))
    await message.answer(
        "MAIS OUI PUTAIN ON EST VENDREDI !!! SHABBAT SHALOM",
        disable_notification=True,
        parse_mode="HTML",
    )
    await message.answer_sticker(
        sticker=FSInputFile(_SHALOM_DIR / "gigashalom.webp"),
        disable_notification=True,
    )

    song = random.randint(0, 1)
    await message.answer_audio(
        audio=FSInputFile(_SHALOM_DIR / f"shabbat{song}.mp3"),
        disable_notification=True,
    )


@router.message(F.location)
async def on_location(message: Message) -> None:
    location = message.location
    if not location:
        return

    settings = get_settings()
    if not settings.rapidapi_key:
        logger.warning("RAPIDAPI_KEY is not set — location handler skipped")
        return

    lat, lng = location.latitude, location.longitude

    try:
        async with (
            httpx.AsyncClient(timeout=10, verify=False) as rapidapi_client,
            httpx.AsyncClient(timeout=10) as meteo_client,
        ):
            address_resp, meteo_resp = await asyncio.gather(
                rapidapi_client.get(
                    "https://address-from-to-latitude-longitude.p.rapidapi.com/geolocationapi",
                    params={"lat": lat, "lng": lng},
                    headers={
                        "X-RapidAPI-Host": "address-from-to-latitude-longitude.p.rapidapi.com",
                        "X-RapidAPI-Key": settings.rapidapi_key,
                    },
                ),
                meteo_client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lng,
                        "hourly": "temperature_2m,apparent_temperature,precipitation_probability,precipitation,rain,showers,snowfall",
                        "current_weather": "true",
                        "timezone": "Europe/Berlin",
                        "forecast_days": "1",
                    },
                ),
            )
        address_resp.raise_for_status()
        meteo_resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Location API call failed: %s", exc)
        return

    addr = address_resp.json()["Results"][0]
    meteo = meteo_resp.json()
    current = meteo["current_weather"]
    temp_unit = meteo["hourly_units"]["temperature_2m"]

    text = (
        f"<b>🗺️ - Résumé de la localisation</b>\n"
        f"📍 Ville : <b>{addr['postalcode']} {addr['city']}</b>\n"
        f"🏔️ Altitude : <b>{meteo['elevation']} m</b>\n"
        f"🌴 Région : <b>{addr['region']}</b>\n"
        f"🏝️ Sous-région : <b>{addr['subregion']}</b>\n"
        f"🌍 Pays : <b>{addr['country']}</b>\n\n"
        f"<b>🌤️ - Météo</b>\n"
        f"🌡️ Température : {current['temperature']} {temp_unit}\n"
        f"💨 V. Vent : {current['windspeed']} km/h"
    )

    await message.reply(text, parse_mode="HTML")


@router.message(F.text.func(lambda value: bool(value and QUOI_RE.search(value))))
async def on_quoi(message: Message) -> None:
    roll = random.random()
    if roll < 0.01:
        await message.reply("coubeh !", disable_notification=True, parse_mode="HTML")
    elif roll < 0.05:
        await message.reply("feur.", disable_notification=True, parse_mode="HTML")


_PEUR_DIR = Path(__file__).parents[3] / "assets" / "peur"


@router.message(F.text.func(lambda value: bool(value and PEUR_RE.search(value))))
async def on_peur(message: Message) -> None:
    if random.random() >= 0.05:
        return
    await message.reply_audio(
        audio=FSInputFile(_PEUR_DIR / "peur.ogg"),
        disable_notification=True,
    )


_WOMEN_DIR = Path(__file__).parents[3] / "assets" / "women"


@router.message(F.text.func(lambda value: bool(value and WOMEN_RE.search(value))))
async def on_women(message: Message) -> None:
    choice = random.randint(0, 2)

    if choice == 0:
        await message.answer_sticker(
            sticker=FSInputFile(_WOMEN_DIR / "gigachad.webp"),
            disable_notification=True,
        )
        await message.answer_audio(
            audio=FSInputFile(_WOMEN_DIR / "gigachad.ogg"),
            disable_notification=True,
        )
    elif choice == 1:
        await message.answer_video(
            video=FSInputFile(_WOMEN_DIR / "women.mp4"),
            caption="☕",
            disable_notification=True,
        )
    else:
        await message.answer_audio(
            audio=FSInputFile(_WOMEN_DIR / "kouizine.ogg"),
            caption="<i>Koui Koui Kouizine !</i>",
            parse_mode="HTML",
            disable_notification=True,
        )


_HEURE_STICKER_ID = "CAACAgQAAxkBAAIBtmSkc2K1hZnzDn5-6H3KASo3L9UcAAI2DgACJ3LhU_Eaikb-lJIJLwQ"
_HEURE_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Connaître l'heure.", callback_data="timenowplease")]]
)


@router.message(
    F.sticker.emoji.func(lambda value: bool(value and "⏰" in value))
    & F.sticker.set_name.func(lambda value: bool(value and "suisse52" in value))
)
async def on_heure_sticker(message: Message) -> None:
    await message.react([ReactionTypeEmoji(emoji="🤓")])
    await message.reply_sticker(
        sticker=_HEURE_STICKER_ID,
        reply_markup=_HEURE_KEYBOARD,
        disable_notification=True,
    )


@router.callback_query(F.data == "timenowplease")
async def on_heure_callback(callback: CallbackQuery) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    username = callback.from_user.username if callback.from_user else "?"
    await callback.answer(text=f"Il est {now} @{username} 😐", show_alert=False)
