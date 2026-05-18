import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, FSInputFile, Message

from daddy_bot.core.config import get_settings
from daddy_bot.db.repositories import chats_repo

logger = logging.getLogger(__name__)

router = Router(name="admin")

_ASSETS_PATH = Path(__file__).parents[3] / "assets"

_CHAT_TYPE_ICON = {
    "private": "💬",
    "group": "👥",
    "supergroup": "👥",
    "channel": "📢",
}

_ACTIVE_STATUSES = {"member", "administrator", "creator"}
_TRACKED_GROUP_TYPES = {"group", "supergroup"}
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_VIDEO_EXTENSIONS = {".mp4"}
_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac"}
_VOICE_EXTENSIONS = {".ogg"}


@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated) -> None:
    if update.new_chat_member.status in _ACTIVE_STATUSES:
        title = update.chat.title or update.chat.full_name or str(update.chat.id)
        await chats_repo.upsert_chat(
            chat_id=update.chat.id,
            chat_type=update.chat.type,
            title=title,
            username=update.chat.username,
        )
        logger.info("Bot joined chat %s (%s)", update.chat.id, update.chat.type)
    else:
        await chats_repo.remove_chat(update.chat.id)
        logger.info("Bot left chat %s", update.chat.id)


@router.message(F.chat.type.in_(_TRACKED_GROUP_TYPES))
async def on_group_interaction(message: Message) -> None:
    chat = message.chat
    title = chat.title or chat.full_name or str(chat.id)
    await chats_repo.upsert_chat(
        chat_id=chat.id,
        chat_type=chat.type,
        title=title,
        username=chat.username,
    )
    # Keep this tracker non-blocking so other group handlers can run.
    raise SkipHandler()


# ---------------------------------------------------------------------------
# /server command (owner only)
# ---------------------------------------------------------------------------


@router.message(Command("server"))
async def on_server(message: Message) -> None:
    if not message.from_user:
        return

    settings = get_settings()
    if message.from_user.id not in settings.owner_id_set():
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML")
        return

    entries = await chats_repo.list_chats()
    if not entries:
        await message.reply(
            "Aucun groupe enregistré. Le bot ajoutera automatiquement les groupes où il y a des interactions.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    lines: list[str] = [f"<b>🤖 Bot présent dans {len(entries)} chat(s) :</b>\n"]
    for entry in entries:
        icon = _CHAT_TYPE_ICON.get(entry.type, "💬")
        title = entry.title or str(entry.id)
        mention = f" @{entry.username}" if entry.username else ""
        lines.append(f"{icon} <b>{title}</b>{mention}\n   <code>{entry.id}</code>")

    await message.reply(
        "\n".join(lines),
        parse_mode="HTML",
        disable_notification=True,
    )


def _is_owner(user_id: int) -> bool:
    return user_id in get_settings().owner_id_set()


@router.message(Command("assets"))
async def on_assets(message: Message) -> None:
    if not message.from_user:
        return
    if not _is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML")
        return

    if not _ASSETS_PATH.exists():
        await message.reply("Dossier assets introuvable.", parse_mode="HTML")
        return

    files = sorted(path for path in _ASSETS_PATH.rglob("*") if path.is_file())
    if not files:
        await message.reply("Aucun asset trouvé.", parse_mode="HTML")
        return

    await message.reply(
        f"📦 Envoi de {len(files)} asset(s) pour test de lecture...",
        parse_mode="HTML",
        disable_notification=True,
    )

    sent_count = 0
    failed: list[str] = []
    for file_path in files:
        relative_path = file_path.relative_to(_ASSETS_PATH.parent).as_posix()
        input_file = FSInputFile(path=str(file_path))
        ext = file_path.suffix.lower()
        caption = f"<code>{relative_path}</code>"
        try:
            if ext in _PHOTO_EXTENSIONS:
                await message.answer_photo(photo=input_file, caption=caption, parse_mode="HTML")
            elif ext in _VIDEO_EXTENSIONS:
                await message.answer_video(video=input_file, caption=caption, parse_mode="HTML")
            elif ext in _AUDIO_EXTENSIONS:
                await message.answer_audio(audio=input_file, caption=caption, parse_mode="HTML")
            elif ext in _VOICE_EXTENSIONS:
                await message.answer_voice(voice=input_file, caption=caption, parse_mode="HTML")
            else:
                await message.answer_document(document=input_file, caption=caption, parse_mode="HTML")
            sent_count += 1
        except Exception as exc:
            logger.warning("Failed to send asset %s: %s", file_path, exc)
            failed.append(relative_path)

    if failed:
        preview = "\n".join(failed[:10])
        suffix = "\n..." if len(failed) > 10 else ""
        await message.answer(
            "✅ Test assets terminé.\n"
            f"Envoyés : <b>{sent_count}</b>\n"
            f"Erreurs : <b>{len(failed)}</b>\n\n"
            f"<b>Fichiers en erreur :</b>\n<code>{preview}{suffix}</code>",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    await message.answer(
        f"✅ Test assets terminé. Tous les fichiers ({sent_count}) ont été envoyés.",
        parse_mode="HTML",
        disable_notification=True,
    )
