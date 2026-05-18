from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import FSInputFile, Message

from daddy_bot.core.config import get_settings
from daddy_bot.db.repositories import princesse_repo
from daddy_bot.db.repositories.princesse_repo import PoolMember

logger = logging.getLogger(__name__)
router = Router(name="princesse_morning")

_PRINCESSE_DIR = Path(__file__).parents[3] / "assets" / "princesse"
_CHAT_ACTION_REFRESH_SECONDS = 4


def _chat_ids() -> tuple[int, ...]:
    return get_settings().princesse_morning_chat_id_tuple()


def _is_owner(user_id: int) -> bool:
    owners = get_settings().owner_id_set()
    return not owners or user_id in owners


async def _load_targets() -> dict[int, list[PoolMember]]:
    return await princesse_repo.list_pools_for_chats(_chat_ids())


async def _save_targets(targets: dict[int, list[PoolMember]]) -> None:
    """Reconcile DB pool state with the given in-memory dict."""
    existing = await princesse_repo.list_pools_for_chats(tuple(targets.keys()))
    for chat_id, members in targets.items():
        existing_ids = {m.user_id for m in existing.get(chat_id, [])}
        new_ids = {m.user_id for m in members}
        for uid in existing_ids - new_ids:
            await princesse_repo.remove_member(chat_id, uid)
        for member in members:
            await princesse_repo.upsert_member(chat_id, member)


def _require_princesse_chat(message: Message) -> bool:
    return message.chat.id in _chat_ids()


async def _load_state() -> dict[str, str]:
    return await princesse_repo.all_state()


async def _save_state(state: dict[str, str]) -> None:
    """Reconcile DB state with the in-memory dict (full sync)."""
    existing = await princesse_repo.all_state()
    for key in set(existing.keys()) - set(state.keys()):
        await princesse_repo.delete_state(key)
    for k, v in state.items():
        if v is None:
            continue
        if existing.get(k) != v:
            await princesse_repo.set_state(k, v)


def _voice_candidates() -> list[Path]:
    if not _PRINCESSE_DIR.is_dir():
        return []
    exts = {".ogg", ".oga", ".opus"}
    return sorted(p for p in _PRINCESSE_DIR.iterdir() if p.is_file() and p.suffix.lower() in exts)


def _audio_duration_seconds(path: Path) -> float:
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if audio is not None and audio.info is not None and getattr(audio.info, "length", None):
            return max(0.5, float(audio.info.length))
    except Exception as exc:
        logger.debug("mutagen duration failed for %s: %s", path, exc)
    return 12.0


async def _hold_record_voice_action(bot: Bot, chat_id: int, duration_seconds: float) -> None:
    remaining = duration_seconds
    while remaining > 0:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        step = min(_CHAT_ACTION_REFRESH_SECONDS, remaining)
        await asyncio.sleep(step)
        remaining -= step


async def run_princesse_morning_ritual(bot: Bot, chat_id: int, member: PoolMember, voice_path: Path) -> None:
    duration = _audio_duration_seconds(voice_path)
    text = f"👑 Coucou {member.mention_html}"
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        disable_notification=False,
    )
    await _hold_record_voice_action(bot, chat_id, duration)
    await bot.send_voice(
        chat_id=chat_id,
        voice=FSInputFile(voice_path),
        duration=int(round(duration)) if duration <= 300 else None,
        disable_notification=False,
    )
    try:
        await princesse_repo.record_send(chat_id=chat_id, user_id=member.user_id, voice_file=voice_path.name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record princesse history: %s", exc)


def _morning_window_for_date(
    d: datetime.date,
    tz: ZoneInfo,
    start_hour: int,
    end_hour: int,
) -> tuple[datetime, datetime]:
    """Return [win_start, win_end) in local time; end_hour is exclusive (e.g. 6 and 10 → 06:00–10:00)."""
    win_start = datetime.combine(d, time(start_hour, 0, 0), tzinfo=tz)
    win_end = datetime.combine(d, time(end_hour, 0, 0), tzinfo=tz)
    return win_start, win_end


def _seconds_until_tomorrow_early(now: datetime, tz: ZoneInfo) -> float:
    wake = datetime.combine(now.date() + timedelta(days=1), time(0, 5, 0), tzinfo=tz)
    return max(60.0, (wake - now).total_seconds())


def _seconds_until_monday_early(now: datetime, tz: ZoneInfo) -> float:
    """Next Monday 00:05 local (used to skip Saturday/Sunday)."""
    wd = now.weekday()
    try:
        days_to_monday = {5: 2, 6: 1}[wd]
    except KeyError:
        logger.warning("Princesse morning: _seconds_until_monday_early called on weekday %s", wd)
        return 3600.0
    monday_date = now.date() + timedelta(days=days_to_monday)
    wake = datetime.combine(monday_date, time(0, 5, 0), tzinfo=tz)
    return max(60.0, (wake - now).total_seconds())


async def run_princesse_morning_scheduler(bot: Bot) -> None:
    settings = get_settings()
    if not settings.princesse_morning_enabled:
        logger.info("Princesse morning scheduler disabled (PRINCESSE_MORNING_ENABLED=0).")
        return

    try:
        tz = ZoneInfo(settings.princesse_morning_timezone)
    except ZoneInfoNotFoundError:
        logger.warning(
            "Invalid PRINCESSE_MORNING_TIMEZONE=%s, fallback to Europe/Paris.",
            settings.princesse_morning_timezone,
        )
        tz = ZoneInfo("Europe/Paris")

    start_h = settings.princesse_morning_start_hour
    end_h = settings.princesse_morning_end_hour
    logger.info(
        "Princesse morning scheduler enabled, window [%02d:00, %02d:00) %s, Mon–Fri only (voice dir=%s).",
        start_h,
        end_h,
        tz.key,
        _PRINCESSE_DIR,
    )

    while True:
        now = datetime.now(tz=tz)
        if now.weekday() >= 5:
            state = await _load_state()
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            await _save_state(state)
            logger.info(
                "Princesse morning: weekend (%s), sleeping until Monday 00:05.",
                now.date().isoformat(),
            )
            await asyncio.sleep(_seconds_until_monday_early(now, tz))
            continue

        day_key = now.date().isoformat()
        state = await _load_state()

        if state.get("last_sent_date") == day_key:
            await asyncio.sleep(_seconds_until_tomorrow_early(now, tz))
            continue

        win_start, win_end = _morning_window_for_date(now.date(), tz, start_h, end_h)

        if state.get("scheduled_date") != day_key:
            if now >= win_end:
                logger.info("Princesse morning: past window for %s, skipping until tomorrow.", day_key)
                state["last_sent_date"] = day_key
                state.pop("scheduled_date", None)
                state.pop("scheduled_at", None)
                await _save_state(state)
                await asyncio.sleep(_seconds_until_tomorrow_early(now, tz))
                continue

            effective_start = win_start if now < win_start else now

            span_sec = int((win_end - effective_start).total_seconds())
            if span_sec <= 0:
                scheduled_at = now + timedelta(seconds=5)
            else:
                scheduled_at = effective_start + timedelta(seconds=random.randint(0, span_sec - 1))

            state["scheduled_date"] = day_key
            state["scheduled_at"] = scheduled_at.isoformat()
            await _save_state(state)
            logger.info("Princesse morning scheduled for %s at %s.", day_key, scheduled_at.isoformat())

        scheduled_at = datetime.fromisoformat(state["scheduled_at"])
        wait_seconds = max(0.0, (scheduled_at - datetime.now(tz=tz)).total_seconds())
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        now = datetime.now(tz=tz)
        if now.weekday() >= 5:
            state = await _load_state()
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            await _save_state(state)
            logger.info(
                "Princesse morning: landed on weekend after wait (%s), sleeping until Monday.",
                now.date().isoformat(),
            )
            await asyncio.sleep(_seconds_until_monday_early(now, tz))
            continue

        day_key = now.date().isoformat()
        state = await _load_state()
        if state.get("last_sent_date") == day_key:
            continue

        targets = await _load_targets()
        chats_with_pool = [cid for cid in _chat_ids() if targets.get(cid)]
        if not chats_with_pool:
            logger.info("Princesse morning: no pool members for configured chats, skipping %s.", day_key)
            state["last_sent_date"] = day_key
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            await _save_state(state)
            continue

        voices = _voice_candidates()
        if not voices:
            logger.warning("Princesse morning: no .ogg voice files in %s, skipping %s.", _PRINCESSE_DIR, day_key)
            state["last_sent_date"] = day_key
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            await _save_state(state)
            continue

        chat_id = random.choice(chats_with_pool)
        pool = targets[chat_id]
        member = random.choice(pool)
        voice_path = random.choice(voices)

        try:
            await run_princesse_morning_ritual(bot, chat_id, member, voice_path)
            state["last_sent_date"] = day_key
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            await _save_state(state)
            logger.info(
                "Princesse morning sent for %s chat=%s user=%s file=%s",
                day_key,
                chat_id,
                member.user_id,
                voice_path.name,
            )
        except Exception as exc:
            logger.exception("Princesse morning failed: %s", exc)
            await asyncio.sleep(120)


@router.message(Command("princesse_pool"))
async def on_princesse_pool_list(message: Message) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML", disable_notification=True)
        return
    if not _require_princesse_chat(message):
        await message.reply(
            "À utiliser dans un des groupes princesse matin.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    pool = (await _load_targets()).get(message.chat.id, [])
    if not pool:
        await message.reply(
            "Pool vide. Les humains du groupe sont ajoutés automatiquement quand ils envoient un message.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    lines = [
        f"{i}. {m.mention_html} <code>{m.user_id}</code>"
        for i, m in enumerate(sorted(pool, key=lambda x: x.user_id), start=1)
    ]
    body = "\n".join(lines[:120])
    extra = ""
    if len(lines) > 120:
        extra = f"\n\n… et {len(lines) - 120} autre(s)."
    await message.reply(
        f"<b>Pool princesse matin</b> ({len(pool)})\n\n{body}{extra}\n\n"
        "<i>Retrait : réponse + /princesse_pool_remove · ID : /princesse_pool_remove_id · "
        "vider : /princesse_pool_clear ok</i>",
        parse_mode="HTML",
        disable_notification=True,
    )


@router.message(Command("princesse_pool_clear"))
async def on_princesse_pool_clear(message: Message, command: CommandObject) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML", disable_notification=True)
        return
    if not _require_princesse_chat(message):
        await message.reply(
            "À utiliser dans un des groupes princesse matin.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    arg = (command.args or "").strip().lower()
    if arg not in ("ok", "oui", "confirm", "sure"):
        await message.reply(
            "Pour vider le pool de <b>ce</b> groupe, envoie :\n"
            "<code>/princesse_pool_clear ok</code>",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    targets = await _load_targets()
    targets[message.chat.id] = []
    await _save_targets(targets)
    await message.reply("Pool vidé pour ce groupe. ✅", parse_mode="HTML", disable_notification=True)


@router.message(Command("princesse_pool_remove_id"))
async def on_princesse_pool_remove_id(message: Message, command: CommandObject) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML", disable_notification=True)
        return
    if not _require_princesse_chat(message):
        await message.reply(
            "À utiliser dans un des groupes princesse matin.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    raw = (command.args or "").strip().split(maxsplit=1)
    if not raw:
        await message.reply(
            "Usage : <code>/princesse_pool_remove_id &lt;user_id&gt;</code>",
            parse_mode="HTML",
            disable_notification=True,
        )
        return
    try:
        uid = int(raw[0])
    except ValueError:
        await message.reply("user_id invalide.", parse_mode="HTML", disable_notification=True)
        return

    targets = await _load_targets()
    pool = targets.setdefault(message.chat.id, [])
    new_pool = [m for m in pool if m.user_id != uid]
    if len(new_pool) == len(pool):
        await message.reply("Cet id n’est pas dans le pool.", parse_mode="HTML", disable_notification=True)
        return
    targets[message.chat.id] = new_pool
    await _save_targets(targets)
    await message.reply(f"Retiré : <code>{uid}</code> ✅", parse_mode="HTML", disable_notification=True)


@router.message(Command("princesse_pool_remove"))
async def on_princesse_pool_remove(message: Message) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML", disable_notification=True)
        return
    if not _require_princesse_chat(message):
        await message.reply(
            "À utiliser dans un des groupes princesse matin.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.reply(
            "Réponds à un message avec <code>/princesse_pool_remove</code>.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    uid = reply.from_user.id
    targets = await _load_targets()
    pool = targets.setdefault(message.chat.id, [])
    new_pool = [m for m in pool if m.user_id != uid]
    if len(new_pool) == len(pool):
        await message.reply("Pas dans le pool.", parse_mode="HTML", disable_notification=True)
        return
    targets[message.chat.id] = new_pool
    await _save_targets(targets)
    await message.reply("Retiré du pool. ✅", parse_mode="HTML", disable_notification=True)


@router.message(Command("princesse_morning_test"))
async def on_princesse_morning_test(message: Message) -> None:
    if not message.from_user or not _is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML", disable_notification=True)
        return
    if message.chat.type != ChatType.PRIVATE:
        await message.reply(
            "Cette commande ne fonctionne qu’en <b>message privé</b> avec le bot.",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    voices = _voice_candidates()
    if not voices:
        await message.reply(f"Aucun vocal dans {_PRINCESSE_DIR}", parse_mode="HTML", disable_notification=True)
        return

    u = message.from_user
    member = PoolMember(
        user_id=u.id,
        first_name=u.first_name or "Copain",
        username=u.username,
    )
    voice_path = random.choice(voices)
    try:
        await run_princesse_morning_ritual(message.bot, message.chat.id, member, voice_path)
        await message.reply("Test terminé (ping + vocal sur toi). ✅", parse_mode="HTML", disable_notification=True)
    except Exception as exc:
        logger.exception("princesse_morning_test failed: %s", exc)
        await message.reply("Erreur à l'envoi.", parse_mode="HTML", disable_notification=True)


@router.message(F.chat.id.func(lambda cid: cid in _chat_ids()))
async def on_autopool_activity(message: Message) -> None:
    if (message.text or "").startswith("/"):
        return
    if not message.from_user or message.from_user.is_bot:
        return
    u = message.from_user
    await princesse_repo.upsert_member(
        message.chat.id,
        PoolMember(
            user_id=u.id,
            first_name=u.first_name or "Copain",
            username=u.username,
        ),
    )

