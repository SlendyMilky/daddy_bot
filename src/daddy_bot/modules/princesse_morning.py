from __future__ import annotations

import asyncio
import html
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import FSInputFile, Message

from daddy_bot.core.config import get_settings

logger = logging.getLogger(__name__)
router = Router(name="princesse_morning")

_PRINCESSE_DIR = Path(__file__).parents[3] / "assets" / "princesse"
_TARGETS_PATH = Path(__file__).parents[3] / "data" / "princesse_morning_targets.json"
_STATE_PATH = Path(__file__).parents[3] / "data" / "princesse_morning_state.json"

_CHAT_IDS: tuple[int, ...] = (-1001153426467, -1001805681499)
_CHAT_ACTION_REFRESH_SECONDS = 4


@dataclass(slots=True)
class PoolMember:
    user_id: int
    first_name: str
    username: str | None

    @property
    def mention_html(self) -> str:
        label = f"@{self.username}" if self.username else self.first_name
        return f'<a href="tg://user?id={self.user_id}">{html.escape(label)}</a>'


def _is_owner(user_id: int) -> bool:
    owners = get_settings().owner_id_set()
    return not owners or user_id in owners


def _load_targets() -> dict[int, list[PoolMember]]:
    if not _TARGETS_PATH.exists():
        return {cid: [] for cid in _CHAT_IDS}
    try:
        raw = json.loads(_TARGETS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read princesse morning targets: %s", exc)
        return {cid: [] for cid in _CHAT_IDS}

    out: dict[int, list[PoolMember]] = {cid: [] for cid in _CHAT_IDS}
    if not isinstance(raw, dict):
        return out

    for key, members_raw in raw.items():
        try:
            chat_id = int(key)
        except (TypeError, ValueError):
            continue
        if chat_id not in out:
            out[chat_id] = []
        if not isinstance(members_raw, list):
            continue
        for item in members_raw:
            if not isinstance(item, dict):
                continue
            try:
                uid = int(item["user_id"])
            except Exception:
                continue
            out[chat_id].append(
                PoolMember(
                    user_id=uid,
                    first_name=str(item.get("first_name") or "Copain"),
                    username=(str(item["username"]) if item.get("username") else None),
                )
            )
    return out


def _save_targets(targets: dict[int, list[PoolMember]]) -> None:
    try:
        _TARGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, list[dict[str, object]]] = {}
        for cid in sorted({*_CHAT_IDS, *targets.keys()}):
            members = targets.get(cid, [])
            payload[str(cid)] = [
                {"user_id": m.user_id, "first_name": m.first_name, "username": m.username}
                for m in sorted(members, key=lambda x: x.user_id)
            ]
        _TARGETS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save princesse morning targets: %s", exc)


def _upsert_pool_member(targets: dict[int, list[PoolMember]], chat_id: int, user_id: int, first_name: str, username: str | None) -> bool:
    """Returns True if the JSON file should be saved (new member or profile changed)."""
    member = PoolMember(user_id=user_id, first_name=first_name or "Copain", username=username)
    pool = targets.setdefault(chat_id, [])
    for i, existing in enumerate(pool):
        if existing.user_id != member.user_id:
            continue
        if existing.first_name != member.first_name or existing.username != member.username:
            pool[i] = member
            return True
        return False
    pool.append(member)
    return True


def _require_princesse_chat(message: Message) -> bool:
    return message.chat.id in _CHAT_IDS


def _load_state() -> dict[str, str]:
    if not _STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read princesse morning state: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _save_state(state: dict[str, str]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save princesse morning state: %s", exc)


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
            state = _load_state()
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            _save_state(state)
            logger.info(
                "Princesse morning: weekend (%s), sleeping until Monday 00:05.",
                now.date().isoformat(),
            )
            await asyncio.sleep(_seconds_until_monday_early(now, tz))
            continue

        day_key = now.date().isoformat()
        state = _load_state()

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
                _save_state(state)
                await asyncio.sleep(_seconds_until_tomorrow_early(now, tz))
                continue

            if now < win_start:
                effective_start = win_start
            else:
                effective_start = now

            span_sec = int((win_end - effective_start).total_seconds())
            if span_sec <= 0:
                scheduled_at = now + timedelta(seconds=5)
            else:
                scheduled_at = effective_start + timedelta(seconds=random.randint(0, span_sec - 1))

            state["scheduled_date"] = day_key
            state["scheduled_at"] = scheduled_at.isoformat()
            _save_state(state)
            logger.info("Princesse morning scheduled for %s at %s.", day_key, scheduled_at.isoformat())

        scheduled_at = datetime.fromisoformat(state["scheduled_at"])
        wait_seconds = max(0.0, (scheduled_at - datetime.now(tz=tz)).total_seconds())
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        now = datetime.now(tz=tz)
        if now.weekday() >= 5:
            state = _load_state()
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            _save_state(state)
            logger.info(
                "Princesse morning: landed on weekend after wait (%s), sleeping until Monday.",
                now.date().isoformat(),
            )
            await asyncio.sleep(_seconds_until_monday_early(now, tz))
            continue

        day_key = now.date().isoformat()
        state = _load_state()
        if state.get("last_sent_date") == day_key:
            continue

        targets = _load_targets()
        chats_with_pool = [cid for cid in _CHAT_IDS if targets.get(cid)]
        if not chats_with_pool:
            logger.info("Princesse morning: no pool members for configured chats, skipping %s.", day_key)
            state["last_sent_date"] = day_key
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            _save_state(state)
            continue

        voices = _voice_candidates()
        if not voices:
            logger.warning("Princesse morning: no .ogg voice files in %s, skipping %s.", _PRINCESSE_DIR, day_key)
            state["last_sent_date"] = day_key
            state.pop("scheduled_date", None)
            state.pop("scheduled_at", None)
            _save_state(state)
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
            _save_state(state)
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

    pool = _load_targets().get(message.chat.id, [])
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

    targets = _load_targets()
    targets[message.chat.id] = []
    _save_targets(targets)
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

    targets = _load_targets()
    pool = targets.setdefault(message.chat.id, [])
    new_pool = [m for m in pool if m.user_id != uid]
    if len(new_pool) == len(pool):
        await message.reply("Cet id n’est pas dans le pool.", parse_mode="HTML", disable_notification=True)
        return
    targets[message.chat.id] = new_pool
    _save_targets(targets)
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
    targets = _load_targets()
    pool = targets.setdefault(message.chat.id, [])
    new_pool = [m for m in pool if m.user_id != uid]
    if len(new_pool) == len(pool):
        await message.reply("Pas dans le pool.", parse_mode="HTML", disable_notification=True)
        return
    targets[message.chat.id] = new_pool
    _save_targets(targets)
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


@router.message(F.chat.id.in_(_CHAT_IDS), ~Command())
async def on_autopool_activity(message: Message) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    targets = _load_targets()
    u = message.from_user
    if _upsert_pool_member(
        targets,
        message.chat.id,
        u.id,
        u.first_name or "Copain",
        u.username,
    ):
        _save_targets(targets)
