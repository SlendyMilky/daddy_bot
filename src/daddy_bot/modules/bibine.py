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
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from daddy_bot.core.config import get_settings

logger = logging.getLogger(__name__)
router = Router(name="bibine")

_SUBSCRIBERS_PATH = Path(__file__).parents[3] / "data" / "bibine_subscribers.json"
_STATE_PATH = Path(__file__).parents[3] / "data" / "bibine_state.json"
_POLLS_PATH = Path(__file__).parents[3] / "data" / "bibine_polls.json"


@dataclass(slots=True)
class BibineSubscriber:
    user_id: int
    first_name: str
    username: str | None

    @property
    def mention_html(self) -> str:
        label = f"@{self.username}" if self.username else self.first_name
        return f'<a href="tg://user?id={self.user_id}">{html.escape(label)}</a>'


def _load_subscribers() -> dict[int, BibineSubscriber]:
    if not _SUBSCRIBERS_PATH.exists():
        return {}
    try:
        raw = json.loads(_SUBSCRIBERS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read bibine subscribers: %s", exc)
        return {}

    subscribers: dict[int, BibineSubscriber] = {}
    if not isinstance(raw, list):
        return subscribers
    for item in raw:
        try:
            user_id = int(item["user_id"])
        except Exception:
            continue
        subscribers[user_id] = BibineSubscriber(
            user_id=user_id,
            first_name=str(item.get("first_name") or "Copain"),
            username=(str(item["username"]) if item.get("username") else None),
        )
    return subscribers


def _save_subscribers(subscribers: dict[int, BibineSubscriber]) -> None:
    try:
        _SUBSCRIBERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "user_id": s.user_id,
                "first_name": s.first_name,
                "username": s.username,
            }
            for s in sorted(subscribers.values(), key=lambda x: x.user_id)
        ]
        _SUBSCRIBERS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save bibine subscribers: %s", exc)


def _load_state() -> dict[str, str]:
    if not _STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read bibine state: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value is not None}


def _save_state(state: dict[str, str]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save bibine state: %s", exc)


def _target_friday_date(now: datetime) -> datetime.date:
    days_until_friday = (4 - now.weekday()) % 7
    target = now + timedelta(days=days_until_friday)
    if now.weekday() >= 5:  # Saturday/Sunday -> next Friday
        target = now + timedelta(days=(11 - now.weekday()))
    return target.date()


def _random_window_datetime(friday_date: datetime.date, tz: ZoneInfo) -> datetime:
    thursday_date = friday_date - timedelta(days=1)

    thu_start = datetime.combine(thursday_date, time(hour=15, minute=0), tzinfo=tz)
    thu_end = datetime.combine(thursday_date, time(hour=22, minute=0), tzinfo=tz)

    fri_start = datetime.combine(friday_date, time(hour=9, minute=0), tzinfo=tz)
    fri_end = datetime.combine(friday_date, time(hour=17, minute=0), tzinfo=tz)

    thu_seconds = int((thu_end - thu_start).total_seconds())
    fri_seconds = int((fri_end - fri_start).total_seconds())
    total_seconds = thu_seconds + fri_seconds

    offset = random.randint(0, max(1, total_seconds - 1))
    if offset < thu_seconds:
        return thu_start + timedelta(seconds=offset)
    return fri_start + timedelta(seconds=(offset - thu_seconds))


def _build_bibine_message(mentions_html: str) -> str:
    return (
        "🍺 Bibine vendredi soir ?\n"
        f"\n👀 Ping: {mentions_html}"
    )


def _poll_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _load_polls() -> dict[str, dict]:
    if not _POLLS_PATH.exists():
        return {}
    try:
        raw = json.loads(_POLLS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read bibine polls: %s", exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_polls(polls: dict[str, dict]) -> None:
    try:
        _POLLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _POLLS_PATH.write_text(json.dumps(polls, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save bibine polls: %s", exc)


def _build_poll_keyboard(yes_count: int, no_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"✅ Chaud ({yes_count})", callback_data="bibine:yes"),
            InlineKeyboardButton(text=f"❌ Pas chaud ({no_count})", callback_data="bibine:no"),
        ]]
    )


def _mention_html(user_id: int, label: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(label)}</a>'


def _build_poll_text(mentions_html: str, yes_votes: list[dict], no_votes: list[dict]) -> str:
    yes_mentions = " ".join(_mention_html(int(v["user_id"]), str(v["label"])) for v in yes_votes) or "Personne pour l'instant"
    no_mentions = " ".join(_mention_html(int(v["user_id"]), str(v["label"])) for v in no_votes) or "Personne"
    return (
        f"{_build_bibine_message(mentions_html)}\n\n"
        f"✅ Chauds ({len(yes_votes)}): {yes_mentions}\n"
        f"❌ Pas chauds ({len(no_votes)}): {no_mentions}"
    )


def _is_owner(user_id: int) -> bool:
    owners = get_settings().owner_id_set()
    return not owners or user_id in owners


async def _send_bibine_ping(bot: Bot, channel_id: int, mentions_html: str) -> None:
    yes_votes: list[dict] = []
    no_votes: list[dict] = []
    text = _build_poll_text(mentions_html, yes_votes, no_votes)
    keyboard = _build_poll_keyboard(yes_count=0, no_count=0)
    sent = await bot.send_message(
        chat_id=channel_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_notification=False,
    )

    polls = _load_polls()
    polls[_poll_key(channel_id, sent.message_id)] = {
        "mentions_html": mentions_html,
        "yes_votes": yes_votes,
        "no_votes": no_votes,
    }
    _save_polls(polls)


@router.callback_query(F.data.startswith("bibine:"))
async def on_bibine_vote(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer()
        return

    action = (callback.data or "").split(":", maxsplit=1)[-1]
    if action not in {"yes", "no"}:
        await callback.answer()
        return

    polls = _load_polls()
    key = _poll_key(callback.message.chat.id, callback.message.message_id)
    poll = polls.get(key)
    if not isinstance(poll, dict):
        await callback.answer("Sondage introuvable ou expiré.", show_alert=True)
        return

    yes_votes = poll.get("yes_votes")
    no_votes = poll.get("no_votes")
    mentions_html = str(poll.get("mentions_html") or "")
    if not isinstance(yes_votes, list) or not isinstance(no_votes, list):
        await callback.answer("Sondage corrompu.", show_alert=True)
        return

    user_id = callback.from_user.id
    label = f"@{callback.from_user.username}" if callback.from_user.username else (
        callback.from_user.first_name or "Utilisateur"
    )
    voter = {"user_id": user_id, "label": label}

    yes_votes = [v for v in yes_votes if int(v.get("user_id", 0)) != user_id]
    no_votes = [v for v in no_votes if int(v.get("user_id", 0)) != user_id]
    if action == "yes":
        yes_votes.append(voter)
    else:
        no_votes.append(voter)

    poll["yes_votes"] = yes_votes
    poll["no_votes"] = no_votes
    polls[key] = poll
    _save_polls(polls)

    new_text = _build_poll_text(mentions_html, yes_votes, no_votes)
    keyboard = _build_poll_keyboard(yes_count=len(yes_votes), no_count=len(no_votes))
    try:
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not update bibine poll message: %s", exc)
    await callback.answer("Vote enregistré 🍻")


@router.message(Command("bibine"))
async def on_bibine(message: Message) -> None:
    if not message.from_user:
        return

    user = message.from_user
    subscribers = _load_subscribers()

    if user.id in subscribers:
        subscribers.pop(user.id, None)
        _save_subscribers(subscribers)
        await message.reply("Tu es retiré des pings bibine. 🫡", disable_notification=True)
        return

    subscribers[user.id] = BibineSubscriber(
        user_id=user.id,
        first_name=user.first_name or "Copain",
        username=user.username,
    )
    _save_subscribers(subscribers)

    settings = get_settings()
    channel_txt = (
        f"\nLe ping aléatoire sera envoyé entre jeudi 15h-22h et vendredi 09h-17h dans <code>{settings.bibine_channel_id}</code>."
        if settings.bibine_channel_id
        else "\n⚠️ BIBINE_CHANNEL_ID n'est pas configuré."
    )
    await message.reply(
        f"Tu es ajouté aux pings bibine. 🍻{channel_txt}",
        parse_mode="HTML",
        disable_notification=True,
    )


@router.message(Command("bibine_test"))
async def on_bibine_test(message: Message) -> None:
    if not message.from_user:
        return

    if not _is_owner(message.from_user.id):
        await message.reply("⛔ Accès non autorisé.", parse_mode="HTML")
        return

    settings = get_settings()
    if not settings.bibine_channel_id:
        await message.reply("⚠️ BIBINE_CHANNEL_ID n'est pas configuré.", parse_mode="HTML")
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await message.reply("Personne n'est inscrit aux pings bibine.", parse_mode="HTML")
        return

    mentions = " ".join(sub.mention_html for sub in subscribers.values())
    try:
        await _send_bibine_ping(message.bot, settings.bibine_channel_id, mentions)
        await message.reply("Test bibine envoyé dans le channel configuré. ✅", parse_mode="HTML")
    except Exception as exc:
        logger.exception("Failed to send bibine test ping: %s", exc)
        await message.reply("Erreur lors de l'envoi du test bibine.", parse_mode="HTML")


async def run_bibine_scheduler(bot: Bot) -> None:
    settings = get_settings()
    if not settings.bibine_channel_id:
        logger.info("Bibine scheduler disabled: BIBINE_CHANNEL_ID not configured.")
        return

    try:
        tz = ZoneInfo(settings.bibine_timezone)
    except ZoneInfoNotFoundError:
        logger.warning(
            "Invalid BIBINE_TIMEZONE=%s, fallback to Europe/Paris.",
            settings.bibine_timezone,
        )
        tz = ZoneInfo("Europe/Paris")

    logger.info(
        "Bibine scheduler enabled for channel=%s (%s).",
        settings.bibine_channel_id,
        tz.key,
    )

    while True:
        now = datetime.now(tz=tz)
        target_week = _target_friday_date(now).isoformat()
        state = _load_state()

        if state.get("last_sent_week") == target_week:
            # Already sent this week; wake up later and re-evaluate.
            await asyncio.sleep(6 * 3600)
            continue

        scheduled_week = state.get("scheduled_week")
        scheduled_at_raw = state.get("scheduled_at")
        scheduled_at: datetime | None = None
        if scheduled_week == target_week and scheduled_at_raw:
            try:
                parsed = datetime.fromisoformat(scheduled_at_raw)
                if parsed.tzinfo is not None:
                    scheduled_at = parsed
            except ValueError:
                scheduled_at = None

        if not scheduled_at:
            friday_date = _target_friday_date(now)
            scheduled_at = _random_window_datetime(friday_date, tz)
            state["scheduled_week"] = target_week
            state["scheduled_at"] = scheduled_at.isoformat()
            _save_state(state)
            logger.info("New bibine reminder scheduled for week %s at %s.", target_week, scheduled_at.isoformat())

        wait_seconds = (scheduled_at - now).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        subscribers = _load_subscribers()
        if not subscribers:
            logger.info("No bibine subscribers, skipping reminder for week %s.", target_week)
            state["last_sent_week"] = target_week
            _save_state(state)
            continue

        mentions = " ".join(sub.mention_html for sub in subscribers.values())

        try:
            await _send_bibine_ping(bot, settings.bibine_channel_id, mentions)
            state["last_sent_week"] = target_week
            _save_state(state)
            logger.info("Bibine reminder sent for week %s.", target_week)
        except Exception as exc:
            logger.exception("Failed to send bibine reminder: %s", exc)
