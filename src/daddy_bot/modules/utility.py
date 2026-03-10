import asyncio
import base64
import html
import json
import logging

import httpx
import trafilatura
import re

from aiogram import Bot, F, Router
from aiogram.enums import MessageEntityType
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyParameters,
)
from openai import AsyncOpenAI

from daddy_bot.core.config import get_settings
from daddy_bot.utils.patterns import I2T_RE, RESUME_RE, S2T_RE, T2I_RE, T2S_RE, UNLOCK_RE

logger = logging.getLogger(__name__)

router = Router(name="utility")


def _full_text(message: Message) -> str:
    return f"{message.text or ''}{message.caption or ''}".strip()


async def _send_stub(message: Message, module_name: str) -> None:
    await message.answer(
        f"Le module `{module_name}` est en cours de migration depuis n8n.",
        disable_notification=True,
    )


_UNLOCK_SUFFIX = "\n\n<i>Unlock par @daddy_v2_bot</i>"


@router.message(Command("unlock"))
@router.message(F.text.func(lambda value: bool(value and UNLOCK_RE.search(value))))
async def on_unlock(message: Message) -> None:
    replied = message.reply_to_message
    if not replied:
        await message.reply(
            "Merci de faire la commande en répondant au message à débloquer.",
            parse_mode="HTML",
        )
        return

    reply_params = ReplyParameters(message_id=replied.message_id)

    if replied.photo:
        photo = max(replied.photo, key=lambda p: p.width * p.height)
        caption = (replied.caption or "") + _UNLOCK_SUFFIX
        await message.answer_photo(
            photo=photo.file_id,
            caption=caption,
            parse_mode="HTML",
            reply_parameters=reply_params,
        )
    elif replied.video:
        caption = (replied.caption or "") + _UNLOCK_SUFFIX
        await message.answer_video(
            video=replied.video.file_id,
            caption=caption,
            parse_mode="HTML",
            reply_parameters=reply_params,
        )
    elif replied.document:
        caption = (replied.caption or "") + _UNLOCK_SUFFIX
        await message.answer_document(
            document=replied.document.file_id,
            caption=caption,
            parse_mode="HTML",
            reply_parameters=reply_params,
        )
    elif replied.text:
        await message.answer(
            replied.text + _UNLOCK_SUFFIX,
            parse_mode="HTML",
            reply_parameters=reply_params,
        )
    else:
        await message.reply(
            "Merci de faire la commande en utilisant la fonction répondre sur le message à débloquer.",
            parse_mode="HTML",
        )


_TG_MAX_LEN = 4096
_S2T_HEADER = "<b>Transcription de l'audio :</b>\n\n"
_MIME_TO_EXT: dict[str, str] = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


_I2T_MAX_BYTES = 20 * 1024 * 1024  # Telegram Bot API hard limit
_I2T_PROMPT = (
    "Décrit le plus précisément possible l'image. "
    "Si il y a du texte autre que du français traduit le en français. "
    "S'il semble y avoir des interrogations, essaye d'y répondre. "
    "Après ce message aucune interaction ne sera possible avec toi, "
    "ta réponse ne doit donc pas être ouverte."
)
_IMAGE_MIMES: dict[str, str] = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _detect_image_mime(raw: bytes) -> str | None:
    """Return the MIME type from magic bytes, or None if unsupported."""
    if raw[:2] == b"\xff\xd8":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _detect_ext(raw: bytes, fallback: str) -> str:
    """Detect audio format from magic bytes, falling back to MIME-derived ext."""
    if raw[4:8] == b"ftyp":
        return "m4a"
    if raw[:3] == b"ID3" or raw[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    if raw[:4] == b"OggS":
        return "ogg"
    if raw[:4] == b"RIFF":
        return "wav"
    if raw[:4] == b"fLaC":
        return "flac"
    if raw[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return fallback


_RESUME_MODEL = "gpt-5-mini"
_RESUME_AUDIO_SYSTEM = (
    "Tu dois résumer en français le message que tu reçois, "
    "ce message est une transcription audio."
)
_RESUME_URL_SYSTEM = "Tu dois résumer de façon très brève en français le contenu que tu reçois."
_WHISPER_COST_PER_SEC = 0.0001  # $0.006/min = $0.0001/sec


def _extract_url(msg: Message) -> str | None:
    """Extract the first URL from message entities (text or caption)."""
    text = msg.text or msg.caption or ""
    entities = msg.entities or msg.caption_entities or []
    for entity in entities:
        if entity.type == MessageEntityType.URL:
            return text[entity.offset : entity.offset + entity.length]
        if entity.type == MessageEntityType.TEXT_LINK and entity.url:
            return entity.url
    return None


async def _transcribe_audio(file_id: str, mime_type: str, bot: Bot, api_key: str) -> str:
    """Download audio from Telegram and transcribe with Whisper. Returns transcript text."""
    tg_file = await bot.get_file(file_id)
    assert tg_file.file_path is not None
    buf = await bot.download_file(tg_file.file_path)
    assert buf is not None
    if hasattr(buf, "seek"):
        buf.seek(0)
    raw = buf.read() if hasattr(buf, "read") else bytes(buf)
    if not raw:
        raise ValueError("Downloaded audio file is empty")

    base_mime = mime_type.split(";")[0].strip().lower()
    mime_ext = _MIME_TO_EXT.get(base_mime) or base_mime.split("/")[-1] or "ogg"
    ext = _detect_ext(raw, mime_ext)
    logger.info("transcribe: ext=%s mime=%s size=%d magic=%s", ext, mime_type, len(raw), raw[:8].hex())

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": "whisper-1"},
            files={"file": (f"audio.{ext}", raw)},
        )
        if response.is_error:
            logger.error("Whisper response body: %s", response.text)
        response.raise_for_status()
    return response.json()["text"].strip()


def _split_transcription(text: str) -> list[str]:
    """Split transcription text into Telegram-safe HTML chunks."""
    first = f"{_S2T_HEADER}<i>{text}</i>"
    if len(first) <= _TG_MAX_LEN:
        return [first]

    parts: list[str] = []
    remaining = text
    part_num = 1
    while remaining:
        prefix = _S2T_HEADER if part_num == 1 else f"<b>Partie {part_num} :</b>\n\n"
        available = _TG_MAX_LEN - len(prefix) - len("<i></i>")
        if len(remaining) <= available:
            parts.append(f"{prefix}<i>{remaining}</i>")
            break
        cut = remaining.rfind(" ", 0, available)
        if cut == -1:
            cut = available
        parts.append(f"{prefix}<i>{remaining[:cut]}</i>")
        remaining = remaining[cut:].lstrip()
        part_num += 1
    return parts


@router.message(Command("s2t"))
@router.message(F.text.func(lambda value: bool(value and S2T_RE.search(value))))
async def on_s2t(message: Message) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        await message.reply("OPENAI_API_KEY non configurée.", parse_mode="HTML")
        return

    replied = message.reply_to_message
    if not replied:
        await message.reply(
            "Merci de faire la commande en utilisant la fonction répondre sur l'audio à transcrire.",
            parse_mode="HTML",
        )
        return

    # Resolve file_id and mime_type from audio / voice / document
    if replied.voice:
        file_id = replied.voice.file_id
        mime_type = replied.voice.mime_type or "audio/ogg"
    elif replied.audio:
        file_id = replied.audio.file_id
        mime_type = replied.audio.mime_type or "audio/mpeg"
    elif replied.document and (replied.document.mime_type or "").startswith("audio/"):
        file_id = replied.document.file_id
        mime_type = replied.document.mime_type or "audio/mpeg"
    else:
        await message.reply(
            "Merci de faire la commande en utilisant la fonction répondre sur l'audio à transcrire.",
            parse_mode="HTML",
        )
        return

    status_msg = await replied.reply(
        "<i>Transcription en cours...</i>",
        parse_mode="HTML",
        disable_notification=True,
    )

    try:
        bot = message.bot
        assert bot is not None
        text = await _transcribe_audio(file_id, mime_type, bot, settings.openai_api_key)
    except Exception as exc:
        logger.exception("s2t transcription failed: %s", exc)
        await status_msg.edit_text("Une erreur est survenue lors de la transcription.", parse_mode="HTML")
        return

    parts = _split_transcription(text)
    await status_msg.edit_text(parts[0], parse_mode="HTML")
    for part in parts[1:]:
        await message.answer(part, parse_mode="HTML", disable_notification=True)


@router.message(Command("i2t"))
@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(I2T_RE.search(_full_text(message))))
)
async def on_i2t(message: Message) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        await message.reply("OPENAI_API_KEY non configurée.", parse_mode="HTML")
        return

    # Resolve file_id: direct image on message, or replied-to message
    replied = message.reply_to_message
    file_id: str | None = None
    if replied:
        if replied.photo:
            file_id = max(replied.photo, key=lambda p: p.width * p.height).file_id
        elif replied.document and (replied.document.mime_type or "").startswith("image/"):
            file_id = replied.document.file_id
    if not file_id:
        if message.photo:
            file_id = max(message.photo, key=lambda p: p.width * p.height).file_id
        elif message.document and (message.document.mime_type or "").startswith("image/"):
            file_id = message.document.file_id
    if not file_id:
        await message.reply(
            "Merci de faire la commande en utilisant la fonction répondre sur l'image à décrire.",
            parse_mode="HTML",
        )
        return

    status_msg = await message.reply(
        "<i>Analyse en cours...</i>",
        parse_mode="HTML",
        disable_notification=True,
    )

    try:
        bot = message.bot
        assert bot is not None
        tg_file = await bot.get_file(file_id)
        if tg_file.file_size and tg_file.file_size > _I2T_MAX_BYTES:
            await status_msg.edit_text("Désolé le fichier est trop grand.", parse_mode="HTML")
            return
        assert tg_file.file_path is not None
        buf = await bot.download_file(tg_file.file_path)
        assert buf is not None
        if hasattr(buf, "seek"):
            buf.seek(0)
        raw = buf.read() if hasattr(buf, "read") else bytes(buf)

        mime = _detect_image_mime(raw)
        if not mime:
            await status_msg.edit_text("Désolé, format non pris en charge.", parse_mode="HTML")
            return

        image_b64 = base64.b64encode(raw).decode()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        {"type": "text", "text": _I2T_PROMPT},
                    ],
                }
            ],
        )

        description = html.escape(response.choices[0].message.content or "")
        usage = response.usage
        if usage:
            cost = (usage.prompt_tokens * 0.00015 + usage.completion_tokens * 0.00060) / 1000
            footer = f"\n\n🫰 - ${cost:.4f} | 🤖 - {response.model} | 💬 - {usage.total_tokens} tokens"
        else:
            footer = f"\n\n🤖 - {response.model}"

        await status_msg.edit_text(description + footer, parse_mode="HTML")

    except Exception as exc:
        logger.exception("i2t analysis failed: %s", exc)
        await status_msg.edit_text("Une erreur est survenue lors de l'analyse.", parse_mode="HTML")


@router.message(Command("resume"))
@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(RESUME_RE.search(_full_text(message))))
)
async def on_resume(message: Message) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        await message.reply("OPENAI_API_KEY non configurée.", parse_mode="HTML")
        return

    bot = message.bot
    assert bot is not None
    replied = message.reply_to_message
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # ── Mode audio ────────────────────────────────────────────────────────────
    audio_file_id: str | None = None
    audio_mime = "audio/ogg"
    audio_duration = 0
    audio_username: str | None = None

    if replied:
        if replied.voice:
            audio_file_id = replied.voice.file_id
            audio_mime = replied.voice.mime_type or "audio/ogg"
            audio_duration = replied.voice.duration or 0
        elif replied.audio:
            audio_file_id = replied.audio.file_id
            audio_mime = replied.audio.mime_type or "audio/mpeg"
            audio_duration = replied.audio.duration or 0
        elif replied.document and (replied.document.mime_type or "").startswith("audio/"):
            audio_file_id = replied.document.file_id
            audio_mime = replied.document.mime_type or "audio/mpeg"
        if audio_file_id and replied.from_user:
            audio_username = replied.from_user.username

    if audio_file_id:
        status_msg = await replied.reply(
            "<i>Résumé en cours...</i>", parse_mode="HTML", disable_notification=True
        )
        try:
            transcription = await _transcribe_audio(audio_file_id, audio_mime, bot, settings.openai_api_key)
            gpt_resp = await client.chat.completions.create(
                model=_RESUME_MODEL,
                messages=[
                    {"role": "system", "content": _RESUME_AUDIO_SYSTEM},
                    {"role": "system", "content": f"Message provenant de : {audio_username or 'inconnu'}"},
                    {"role": "user", "content": transcription},
                ],
            )
            summary = html.escape(gpt_resp.choices[0].message.content or "")
            whisper_cost = audio_duration * _WHISPER_COST_PER_SEC
            usage = gpt_resp.usage
            tokens = usage.total_tokens if usage else "?"
            footer = f"\n\n🎙️ - ${whisper_cost:.3f} | 🤖 - {gpt_resp.model} | 💬 - {tokens} tokens"
            await status_msg.edit_text(summary + footer, parse_mode="HTML")
        except Exception as exc:
            logger.exception("resume audio failed: %s", exc)
            await status_msg.edit_text("Erreur lors du résumé...", parse_mode="HTML")
        return

    # ── Mode URL ──────────────────────────────────────────────────────────────
    url = _extract_url(message)
    if not url and replied:
        url = _extract_url(replied)

    if not url:
        await message.reply(
            "Merci de faire la commande en utilisant la fonction répondre sur l'URL ou l'audio à résumer.",
            parse_mode="HTML",
        )
        return

    status_msg = await message.reply(
        "<i>Résumé en cours du lien...</i>", parse_mode="HTML", disable_notification=True
    )
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as http_client:
            resp = await http_client.get(url)
            resp.raise_for_status()
            page_html = resp.text

        result_json_str = await asyncio.to_thread(
            trafilatura.extract,
            page_html,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            include_tables=False,
        )
        meta: dict = json.loads(result_json_str) if result_json_str else {}
        plain_text = meta.get("text") or meta.get("raw_text") or page_html[:8000]
        title = meta.get("title") or ""
        site_name = meta.get("sitename") or ""
        image_url = meta.get("image") or ""

        messages_gpt = [{"role": "system", "content": _RESUME_URL_SYSTEM}]
        if title:
            messages_gpt.append({"role": "user", "content": f"Titre : {title}"})
        messages_gpt.append({"role": "user", "content": plain_text[:8000]})

        gpt_resp = await client.chat.completions.create(model=_RESUME_MODEL, messages=messages_gpt)
        summary = html.escape(gpt_resp.choices[0].message.content or "")
        usage = gpt_resp.usage
        tokens = usage.total_tokens if usage else "?"

        footer_parts = []
        if image_url:
            footer_parts.append(f'📸 - <a href="{html.escape(image_url)}">Photo</a>')
        footer_parts += [f"🤖 - {gpt_resp.model}", f"💬 - {tokens} tokens"]
        if site_name:
            footer_parts.append(f'🌐 - <a href="{html.escape(url)}">{html.escape(site_name)}</a>')

        await status_msg.edit_text(
            summary + "\n\n" + " | ".join(footer_parts),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.exception("resume URL failed: %s", exc)
        await status_msg.edit_text("Erreur lors du résumé du lien...", parse_mode="HTML")


class _T2iQuality(CallbackData, prefix="t2i_q"):
    quality: str  # "standard" | "hd"


class _T2iSize(CallbackData, prefix="t2i_s"):
    quality: str
    size: str  # "1024x1024" | "1024x1792" | "1792x1024"


_T2I_PROMPT_MARKER = "Description de l'image à générer ?"
_T2I_SIZES: list[tuple[str, str]] = [
    ("1024×1024", "1024x1024"),
    ("1024×1792", "1024x1792"),
    ("1792×1024", "1792x1024"),
]


def _t2i_is_owner(user_id: int) -> bool:
    owners = get_settings().owner_id_set()
    return not owners or user_id in owners


# ── Step 1: /t2i command ─────────────────────────────────────────────────────
@router.message(Command("t2i"))
@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(T2I_RE.search(_full_text(message))))
)
async def on_t2i_message(message: Message) -> None:
    if not message.from_user or not _t2i_is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML")
        return
    if not get_settings().openai_api_key:
        await message.reply("OPENAI_API_KEY non configurée.", parse_mode="HTML")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Standard", callback_data=_T2iQuality(quality="standard").pack()),
        InlineKeyboardButton(text="HD", callback_data=_T2iQuality(quality="hd").pack()),
    ]])
    await message.reply("Génération Standard ou HD ?", reply_markup=keyboard)


# ── Step 2: quality selected → edit to resolution keyboard ───────────────────
@router.callback_query(_T2iQuality.filter())
async def on_t2i_quality(callback: CallbackQuery, callback_data: _T2iQuality) -> None:
    if not _t2i_is_owner(callback.from_user.id):
        await callback.answer("⛔ Accès non autorisé.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=label,
            callback_data=_T2iSize(quality=callback_data.quality, size=api_size).pack(),
        )
        for label, api_size in _T2I_SIZES
    ]])
    if callback.message:
        await callback.message.edit_text("Résolution de l'image ?", reply_markup=keyboard)
    await callback.answer()


# ── Step 3: resolution selected → delete keyboard, send ForceReply ───────────
@router.callback_query(_T2iSize.filter())
async def on_t2i_size(callback: CallbackQuery, callback_data: _T2iSize) -> None:
    if not _t2i_is_owner(callback.from_user.id):
        await callback.answer("⛔ Accès non autorisé.", show_alert=True)
        return
    quality_label = "HD" if callback_data.quality == "hd" else "Standard"
    size_label = next((lbl for lbl, api in _T2I_SIZES if api == callback_data.size), callback_data.size)
    if callback.message:
        await callback.message.answer(
            f"{_T2I_PROMPT_MARKER}\n\nSéléction : {quality_label} {size_label}",
            reply_markup=ForceReply(selective=True),
        )
        await callback.message.delete()
    await callback.answer()


# ── Step 4: user replies to the ForceReply with their prompt ─────────────────
@router.message(
    F.func(
        lambda m: isinstance(m, Message)
        and bool(m.reply_to_message)
        and _T2I_PROMPT_MARKER in (m.reply_to_message.text or "")
    )
)
async def on_t2i_reply_chain(message: Message) -> None:
    if not message.from_user or not _t2i_is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML")
        return

    reply_text = message.reply_to_message.text or ""  # type: ignore[union-attr]
    quality = "hd" if "HD" in reply_text else "standard"
    size_match = re.search(r"(\d+[×x]\d+)", reply_text)
    size = size_match.group(1).replace("×", "x") if size_match else "1024x1024"
    prompt = (message.text or "").strip()
    if not prompt:
        await message.reply("Veuillez entrer une description.", parse_mode="HTML")
        return

    status_msg = await message.reply(
        "<i>Génération en cours...</i>", parse_mode="HTML", disable_notification=True
    )
    try:
        client = AsyncOpenAI(api_key=get_settings().openai_api_key)
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,  # type: ignore[arg-type]
            quality=quality,  # type: ignore[arg-type]
            n=1,
        )
        image_url = response.data[0].url
        revised = response.data[0].revised_prompt or prompt
        await status_msg.delete()
        await message.answer_photo(
            photo=image_url,
            caption=f"<i>{html.escape(revised)}</i>",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("t2i generation failed: %s", exc)
        await status_msg.edit_text("Erreur lors de la génération de l'image.", parse_mode="HTML")


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(T2S_RE.search(_full_text(message))))
)
async def on_t2s_message(message: Message) -> None:
    await _send_stub(message, "t2s")


@router.callback_query(F.data.contains("t2s"))
async def on_t2s_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer(
            "Le module `t2s` est en cours de migration depuis n8n.",
            disable_notification=True,
        )
    await callback.answer()
