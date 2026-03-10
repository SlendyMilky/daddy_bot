import json
import logging
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message

from daddy_bot.core.config import get_settings

logger = logging.getLogger(__name__)

router = Router(name="admin")

_DATA_PATH = Path(__file__).parents[3] / "data" / "chats.json"

_CHAT_TYPE_ICON = {
    "private": "💬",
    "group": "👥",
    "supergroup": "👥",
    "channel": "📢",
}

_ACTIVE_STATUSES = {"member", "administrator", "creator"}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_registry() -> dict[str, dict]:
    if _DATA_PATH.exists():
        try:
            return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read chat registry: %s", exc)
    return {}


def _save_registry(registry: dict[str, dict]) -> None:
    try:
        _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DATA_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save chat registry: %s", exc)


# ---------------------------------------------------------------------------
# Track bot membership changes
# ---------------------------------------------------------------------------

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated) -> None:
    registry = _load_registry()
    chat_id = str(update.chat.id)

    if update.new_chat_member.status in _ACTIVE_STATUSES:
        registry[chat_id] = {
            "id": update.chat.id,
            "type": update.chat.type,
            "title": update.chat.title or update.chat.full_name or str(update.chat.id),
            "username": update.chat.username,
        }
        logger.info("Bot joined chat %s (%s)", update.chat.id, update.chat.type)
    else:
        registry.pop(chat_id, None)
        logger.info("Bot left chat %s", update.chat.id)

    _save_registry(registry)


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

    registry = _load_registry()
    if not registry:
        await message.reply(
            "Aucun chat enregistré. Le bot trackera automatiquement les prochaines entrées.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    lines: list[str] = [f"<b>🤖 Bot présent dans {len(registry)} chat(s) :</b>\n"]
    for entry in sorted(registry.values(), key=lambda e: e.get("type", "")):
        icon = _CHAT_TYPE_ICON.get(entry.get("type", ""), "💬")
        title = entry.get("title") or str(entry.get("id"))
        chat_id = entry.get("id")
        username = entry.get("username")
        mention = f" @{username}" if username else ""
        lines.append(f"{icon} <b>{title}</b>{mention}\n   <code>{chat_id}</code>")

    await message.reply(
        "\n".join(lines),
        parse_mode="HTML",
        disable_notification=True,
    )
