import logging

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyParameters

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

    # Send status message (will be edited in-place with the result)
    status_msg = await replied.reply(
        "<i>Transcription en cours...</i>",
        parse_mode="HTML",
        disable_notification=True,
    )

    try:
        bot = message.bot
        assert bot is not None
        tg_file = await bot.get_file(file_id)
        assert tg_file.file_path is not None
        buf = await bot.download_file(tg_file.file_path)
        assert buf is not None

        base_mime = mime_type.split(";")[0].strip().lower()
        mime_ext = _MIME_TO_EXT.get(base_mime) or base_mime.split("/")[-1] or "ogg"
        if hasattr(buf, "seek"):
            buf.seek(0)
        raw = buf.read() if hasattr(buf, "read") else bytes(buf)
        ext = _detect_ext(raw, mime_ext)
        logger.info(
            "s2t: ext=%s (mime_ext=%s) mime=%s size=%d bytes magic=%s",
            ext, mime_ext, mime_type, len(raw), raw[:8].hex(),
        )
        if not raw:
            raise ValueError("Downloaded file is empty")

        async with httpx.AsyncClient(timeout=120) as http_client:
            response = await http_client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data={"model": "whisper-1"},
                files={"file": (f"audio.{ext}", raw)},
            )
            if response.is_error:
                logger.error("s2t OpenAI response body: %s", response.text)
            response.raise_for_status()
        text = response.json()["text"].strip()
    except Exception as exc:
        logger.exception("s2t transcription failed: %s", exc)
        await status_msg.edit_text(
            "Une erreur est survenue lors de la transcription.",
            parse_mode="HTML",
        )
        return

    parts = _split_transcription(text)
    await status_msg.edit_text(parts[0], parse_mode="HTML")
    for part in parts[1:]:
        await message.answer(part, parse_mode="HTML", disable_notification=True)


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(I2T_RE.search(_full_text(message))))
)
async def on_i2t(message: Message) -> None:
    await _send_stub(message, "i2t")


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(RESUME_RE.search(_full_text(message))))
)
async def on_resume(message: Message) -> None:
    await _send_stub(message, "resume")


@router.message(
    F.func(lambda message: isinstance(message, Message) and bool(T2I_RE.search(_full_text(message))))
)
async def on_t2i_message(message: Message) -> None:
    await _send_stub(message, "t2i")


@router.callback_query(F.data.contains("t2i"))
async def on_t2i_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer(
            "Le module `t2i` est en cours de migration depuis n8n.",
            disable_notification=True,
        )
    await callback.answer()


@router.message(
    F.func(
        lambda message: isinstance(message, Message)
        and bool(message.reply_to_message)
        and "Description de l'image a generer ?" in ((message.reply_to_message.text or ""))
    )
)
async def on_t2i_reply_chain(message: Message) -> None:
    await _send_stub(message, "t2i")


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
