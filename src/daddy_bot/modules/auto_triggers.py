import asyncio
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReactionTypeEmoji,
)

from daddy_bot.core.config import get_settings
from daddy_bot.utils.patterns import (
    ANTI_DPRK_INSULT_RE,
    ANTI_COMMUNISM_INSULT_RE,
    BRICOLEUR_RE,
    COMMUNISM_RE,
    DPRK_RE,
    ERIKA_RE,
    JEW_AUDIO_TRIGGER_RE,
    PEUR_RE,
    QUOI_RE,
    SHALOM_RE,
    WOMEN_RE,
)

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
_JEW_DIR = Path(__file__).parents[3] / "assets" / "jew"
_JEW_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".m4a", ".wav"}
_PLANETE_RAP_MIN_DURATION_SECONDS = 5 * 60
_PLANETE_RAP_CHANCE = 0.25
_PLANETE_RAP_STICKER_IDS = [
    "CAACAgQAAxkBAAII1mm28mt29wOs5D-tjDr4Uq4SJjD-AAJLEwACbykpUbtS94QKTr4uOgQ",
    "CAACAgQAAxkBAAII12m28nD1h_j-c2qXn9H9qPFg2WJHAAInEwACQDX5U1RlrIugctdyOgQ",
    "CAACAgQAAxkBAAII2Gm28nkGlLXyT9yGf653UyYjQorbAAL8FAACNHMpU3TZfj1KkDwtOgQ",
    "CAACAgQAAxkBAAII32m28z34F-YAAWVnzTy--0Gjx0dfugACBQIAAtlWtBhl22rMoVsO2ToE",
]
_PLANETE_RAP_DOUBLE_STICKER_TRIGGER_ID = "CAACAgQAAxkBAAII32m28z34F-YAAWVnzTy--0Gjx0dfugACBQIAAtlWtBhl22rMoVsO2ToE"
_PLANETE_RAP_DOUBLE_STICKER_FOLLOWUP_ID = "CAACAgQAAxkBAAII4Gm28z562JUUkSNXsvMORVTz3siVAAIGAgAC2Va0GDCs1_RXiBLVOgQ"
_PLANETE_RAP_TEXT = "Ptain vlà planète rap qui débarque..."
_PLANETE_RAP_COOLDOWN = timedelta(hours=6)
_planete_rap_last_sent_at: datetime | None = None
_planete_rap_pending = False
_planete_rap_lock = asyncio.Lock()


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


@router.message(F.text.func(lambda value: bool(value and JEW_AUDIO_TRIGGER_RE.search(value))))
async def on_jew_audio_trigger(message: Message) -> None:
    if random.random() >= 0.0025:
        return

    audio_candidates = [
        file_path
        for file_path in _JEW_DIR.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in _JEW_AUDIO_EXTENSIONS
    ]
    if not audio_candidates:
        logger.warning("No jew audio files found in %s", _JEW_DIR)
        return

    await message.reply_audio(
        audio=FSInputFile(random.choice(audio_candidates)),
        disable_notification=True,
    )


async def _reserve_planete_rap_slot(now: datetime) -> bool:
    global _planete_rap_pending
    async with _planete_rap_lock:
        if _planete_rap_pending:
            return False
        if _planete_rap_last_sent_at and now - _planete_rap_last_sent_at < _PLANETE_RAP_COOLDOWN:
            return False
        _planete_rap_pending = True
        return True


async def _release_planete_rap_slot(*, sent: bool) -> None:
    global _planete_rap_last_sent_at, _planete_rap_pending
    async with _planete_rap_lock:
        if sent:
            _planete_rap_last_sent_at = datetime.utcnow()
        _planete_rap_pending = False


@router.message(F.audio)
@router.message(F.voice)
async def on_long_audio_planete_rap(message: Message) -> None:
    duration = 0
    if message.audio:
        duration = message.audio.duration or 0
    elif message.voice:
        duration = message.voice.duration or 0

    if duration < _PLANETE_RAP_MIN_DURATION_SECONDS:
        return
    if random.random() >= _PLANETE_RAP_CHANCE:
        return

    now = datetime.utcnow()
    if not await _reserve_planete_rap_slot(now):
        return

    sent = False
    try:
        if random.randint(0, len(_PLANETE_RAP_STICKER_IDS)) < len(_PLANETE_RAP_STICKER_IDS):
            selected_sticker = random.choice(_PLANETE_RAP_STICKER_IDS)
            await message.reply_sticker(
                sticker=selected_sticker,
                disable_notification=True,
            )
            if selected_sticker == _PLANETE_RAP_DOUBLE_STICKER_TRIGGER_ID:
                await message.answer_sticker(
                    sticker=_PLANETE_RAP_DOUBLE_STICKER_FOLLOWUP_ID,
                    disable_notification=True,
                )
            sent = True
            return

        await message.reply(_PLANETE_RAP_TEXT, disable_notification=True)
        sent = True
    finally:
        await _release_planete_rap_slot(sent=sent)


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


_BRICOLEUR_DIR = Path(__file__).parents[3] / "assets" / "bricoleur"


@router.message(F.text.func(lambda value: bool(value and BRICOLEUR_RE.search(value))))
async def on_bricoleur(message: Message) -> None:
    audio = FSInputFile(_BRICOLEUR_DIR / "Le Bricoleur.mp3")

    # If the trigger message is itself a reply, send the audio as a reply to that parent message
    if message.reply_to_message:
        await message.reply_to_message.reply_audio(
            audio=audio,
            disable_notification=True,
        )
    else:
        await message.reply_audio(
            audio=audio,
            disable_notification=True,
        )


_COMMUNISTE_DIR = Path(__file__).parents[3] / "assets" / "communiste"
_COMMUNISTE_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".m4a", ".wav"}


@router.message(F.text.func(lambda value: bool(value and COMMUNISM_RE.search(value))))
async def on_anti_communism(message: Message) -> None:
    text = message.text or ""
    if not ANTI_COMMUNISM_INSULT_RE.search(text):
        return

    audio_candidates = [
        file_path
        for file_path in _COMMUNISTE_DIR.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in _COMMUNISTE_AUDIO_EXTENSIONS
    ]
    if not audio_candidates:
        logger.warning("No communist audio files found in %s", _COMMUNISTE_DIR)
        await message.reply("Au moins eux, ils font de la bonne musique.", disable_notification=True)
        return

    selected_audio = random.choice(audio_candidates)
    await message.reply("Au moins eux, ils font de la bonne musique.", disable_notification=True)
    await message.reply_audio(
        audio=FSInputFile(selected_audio),
        disable_notification=True,
    )


_DPRK_DIR = Path(__file__).parents[3] / "assets" / "DPRK"
_DPRK_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".m4a", ".wav"}


@router.message(F.text.func(lambda value: bool(value and DPRK_RE.search(value))))
async def on_anti_dprk(message: Message) -> None:
    text = message.text or ""
    if not ANTI_DPRK_INSULT_RE.search(text):
        return

    audio_candidates = [
        file_path
        for file_path in _DPRK_DIR.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in _DPRK_AUDIO_EXTENSIONS
    ]
    if not audio_candidates:
        logger.warning("No DPRK audio files found in %s", _DPRK_DIR)
        await message.reply("Au moins eux, ils font de la bonne musique.", disable_notification=True)
        return

    selected_audio = random.choice(audio_candidates)
    await message.reply("Au moins eux, ils font de la bonne musique.", disable_notification=True)
    await message.reply_audio(
        audio=FSInputFile(selected_audio),
        disable_notification=True,
    )


_HEURE_STICKER_ID = "CAACAgQAAxkBAAIBtmSkc2K1hZnzDn5-6H3KASo3L9UcAAI2DgACJ3LhU_Eaikb-lJIJLwQ"
_HEURE_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Connaître l'heure.", callback_data="timenowplease")]]
)

_MAISCSUPERSA_AUDIO_FILE = Path(__file__).parents[3] / "assets" / "maiscsupersa" / "maiscsupersa.ogg"
_MAISCSUPERSA_BASE_CHANCE = 0.0001  # 0.01% per text message
_MAISCSUPERSA_STREAK_WINDOW = timedelta(seconds=45)
_MAISCSUPERSA_MAX_CHANCE = 0.0005  # cap at 0.05%
_MAISCSUPERSA_COOLDOWN = timedelta(hours=24)
_MAISCSUPERSA_RECORDING_SECONDS = 8
_MAISCSUPERSA_CHAT_ACTION_REFRESH = 4
_maiscsupersa_last_sent_at: datetime | None = None
_maiscsupersa_pending = False
_maiscsupersa_lock = asyncio.Lock()
_maiscsupersa_user_streaks: dict[int, tuple[int, datetime]] = {}
_HUH_AUDIO_FILE = Path(__file__).parents[3] / "assets" / "huh" / "huh.ogg"
_HUH_RECORDING_SECONDS = 1
_HUH_TRIGGER_STICKER_ID = "CAACAgQAAx0CRL_kIwABAogHabaWjN8KTJMYkAMhOa4fUBbjSS0AAlgSAAKCyiBTEYkPL_XLGb06BA"


def _maiscsupersa_multiplier(streak: int) -> float:
    if streak >= 6:
        return 5.0
    if streak == 5:
        return 3.0
    if streak == 4:
        return 2.0
    return 1.0


def _update_maiscsupersa_streak(user_id: int, now: datetime) -> int:
    previous = _maiscsupersa_user_streaks.get(user_id)
    if previous is None:
        streak = 1
    else:
        previous_streak, previous_at = previous
        if now - previous_at <= _MAISCSUPERSA_STREAK_WINDOW:
            streak = min(previous_streak + 1, 12)
        else:
            streak = 1

    _maiscsupersa_user_streaks[user_id] = (streak, now)
    return streak


async def _reserve_maiscsupersa_slot(now: datetime) -> bool:
    global _maiscsupersa_pending
    async with _maiscsupersa_lock:
        if _maiscsupersa_pending:
            return False
        if _maiscsupersa_last_sent_at and now - _maiscsupersa_last_sent_at < _MAISCSUPERSA_COOLDOWN:
            return False
        _maiscsupersa_pending = True
        return True


async def _release_maiscsupersa_slot(*, sent: bool) -> None:
    global _maiscsupersa_last_sent_at, _maiscsupersa_pending
    async with _maiscsupersa_lock:
        if sent:
            _maiscsupersa_last_sent_at = datetime.utcnow()
        _maiscsupersa_pending = False


async def _simulate_recording(message: Message) -> None:
    remaining = _MAISCSUPERSA_RECORDING_SECONDS
    while remaining > 0:
        await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.RECORD_VOICE)
        step = min(_MAISCSUPERSA_CHAT_ACTION_REFRESH, remaining)
        await asyncio.sleep(step)
        remaining -= step


def _is_huh_trigger_sticker(message: Message) -> bool:
    sticker = message.sticker
    if not sticker:
        return False

    trigger_id = _HUH_TRIGGER_STICKER_ID.strip()
    if not trigger_id:
        return False

    matched = sticker.file_id == trigger_id or sticker.file_unique_id == trigger_id
    if not matched:
        logger.debug(
            "HUH sticker mismatch: got file_id=%s file_unique_id=%s set_name=%s emoji=%s",
            sticker.file_id,
            sticker.file_unique_id,
            sticker.set_name,
            sticker.emoji,
        )
    return matched


async def _send_huh_voice(message: Message) -> None:
    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.RECORD_VOICE)
    await asyncio.sleep(_HUH_RECORDING_SECONDS)

    voice = FSInputFile(_HUH_AUDIO_FILE)
    if message.reply_to_message:
        await message.reply_to_message.reply_voice(
            voice=voice,
            disable_notification=True,
        )
        return

    await message.answer_voice(
        voice=voice,
        disable_notification=True,
    )


@router.message(Command("stickerid"))
async def on_stickerid(message: Message) -> None:
    target = message.sticker
    if target is None and message.reply_to_message:
        target = message.reply_to_message.sticker

    if target is None:
        await message.reply(
            "Envoie <code>/stickerid</code> en reply d'un sticker (ou avec un sticker).",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    await message.reply(
        "IDs du sticker:\n"
        f"- <code>file_id</code>: <code>{target.file_id}</code>\n"
        f"- <code>file_unique_id</code>: <code>{target.file_unique_id}</code>\n"
        f"- set: <code>{target.set_name or 'n/a'}</code>\n"
        f"- emoji: <code>{target.emoji or 'n/a'}</code>",
        parse_mode="HTML",
        disable_notification=True,
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


@router.message(F.sticker)
async def on_huh_sticker(message: Message) -> None:
    if not _is_huh_trigger_sticker(message):
        return
    await _send_huh_voice(message)


@router.message(F.text)
async def on_maiscsupersa_random_voice(message: Message) -> None:
    user = message.from_user
    if user is None or user.is_bot:
        return

    now = datetime.utcnow()
    streak = _update_maiscsupersa_streak(user.id, now)
    multiplier = _maiscsupersa_multiplier(streak)
    chance = min(_MAISCSUPERSA_BASE_CHANCE * multiplier, _MAISCSUPERSA_MAX_CHANCE)
    roll = random.random()

    if multiplier > 1:
        logger.info(
            "Maiscsupersa streak bonus for user=%s streak=%s multiplier=%.2f chance=%.5f",
            user.id,
            streak,
            multiplier,
            chance,
        )

    if roll >= chance:
        return

    if not await _reserve_maiscsupersa_slot(now):
        logger.info("Maiscsupersa skipped: pending trigger or 24h cooldown active")
        return

    sent = False
    try:
        logger.info("Maiscsupersa trigger accepted for user=%s roll=%.6f chance=%.5f", user.id, roll, chance)
        await _simulate_recording(message)
        await message.reply_audio(
            audio=FSInputFile(_MAISCSUPERSA_AUDIO_FILE),
            disable_notification=True,
        )
        sent = True
        logger.info("Maiscsupersa audio sent in chat=%s as reply to message=%s", message.chat.id, message.message_id)
    finally:
        await _release_maiscsupersa_slot(sent=sent)
