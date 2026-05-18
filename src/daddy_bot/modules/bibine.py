from __future__ import annotations

import asyncio
import html
import logging
import random
from collections import Counter
from datetime import datetime, time, timedelta
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from daddy_bot.core.config import get_settings
from daddy_bot.db.repositories import bibine_repo
from daddy_bot.db.repositories.bibine_repo import BibineSubscriber
from daddy_bot.utils.mentions import mention_html as _mention_html

logger = logging.getLogger(__name__)
router = Router(name="bibine")


async def _load_subscribers() -> dict[int, BibineSubscriber]:
    return {s.user_id: s for s in await bibine_repo.list_subscribers()}


async def _save_subscribers(subscribers: dict[int, BibineSubscriber]) -> None:
    """Reconcile DB with the in-memory dict (additions + removals)."""
    existing = {s.user_id for s in await bibine_repo.list_subscribers()}
    new_ids = set(subscribers.keys())
    for uid in existing - new_ids:
        await bibine_repo.remove_subscriber(uid)
    for sub in subscribers.values():
        await bibine_repo.add_subscriber(sub)


async def _load_state() -> dict[str, str]:
    return await bibine_repo.all_state()


async def _save_state(state: dict[str, str]) -> None:
    existing = await bibine_repo.all_state()
    for key in set(existing.keys()) - set(state.keys()):
        await bibine_repo.delete_state(key)
    for k, v in state.items():
        if v is None:
            continue
        if existing.get(k) != v:
            await bibine_repo.set_state(k, v)


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


def _parse_poll_key(key: str) -> tuple[int, int] | None:
    try:
        chat_str, msg_str = key.split(":", maxsplit=1)
        return int(chat_str), int(msg_str)
    except (ValueError, AttributeError):
        return None


async def _load_polls() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in await bibine_repo.list_active_polls():
        key = _poll_key(int(entry["chat_id"]), int(entry["message_id"]))
        payload = entry["payload"]
        if isinstance(payload, dict):
            payload.setdefault("type", entry["type"])
            out[key] = payload
    return out


async def _save_polls(polls: dict[str, dict]) -> None:
    for key, payload in polls.items():
        parsed = _parse_poll_key(key)
        if not parsed or not isinstance(payload, dict):
            continue
        chat_id, message_id = parsed
        poll_type = str(payload.get("type") or ("place" if "proposals" in payload else "ping"))
        await bibine_repo.save_poll(chat_id, message_id, poll_type, payload)


async def _load_place_state() -> dict[str, dict]:
    """Load all place-state rows into a dict keyed by 'chat_id:week_iso' for compatibility."""
    import json as _json

    from daddy_bot.core.db import get_connection as _get_conn
    conn = await _get_conn()
    out: dict[str, dict] = {}
    async with conn.execute(
        "SELECT chat_id, week_iso, poll_message_id, proposals FROM bibine_place_state"
    ) as cur:
        rows = await cur.fetchall()
    for r in rows:
        try:
            proposals = _json.loads(r[3])
        except _json.JSONDecodeError:
            proposals = []
        out[_week_key_for_chat(int(r[0]), str(r[1]))] = {
            "chat_id": int(r[0]),
            "week_iso": str(r[1]),
            "poll_message_id": r[2],
            "proposals": proposals if isinstance(proposals, list) else [],
        }
    return out


async def _save_place_state(place_state: dict[str, dict]) -> None:
    for week_state in place_state.values():
        if not isinstance(week_state, dict):
            continue
        try:
            chat_id = int(week_state["chat_id"])
            week_iso = str(week_state["week_iso"])
        except (KeyError, TypeError, ValueError):
            continue
        poll_message_id = week_state.get("poll_message_id")
        try:
            poll_message_id_int = int(poll_message_id) if poll_message_id is not None else None
        except (TypeError, ValueError):
            poll_message_id_int = None
        proposals = week_state.get("proposals")
        if not isinstance(proposals, list):
            proposals = []
        await bibine_repo.save_place_state(chat_id, week_iso, poll_message_id_int, proposals)


def _build_poll_keyboard(yes_count: int, no_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"✅ Chaud ({yes_count})", callback_data="bibine:yes"),
            InlineKeyboardButton(text=f"❌ Pas chaud ({no_count})", callback_data="bibine:no"),
        ]]
    )


def _build_poll_text(mentions_html: str, yes_votes: list[dict], no_votes: list[dict]) -> str:
    yes_mentions = " ".join(_mention_html(int(v["user_id"]), str(v["label"])) for v in yes_votes) or "Personne pour l'instant"
    no_mentions = " ".join(_mention_html(int(v["user_id"]), str(v["label"])) for v in no_votes) or "Personne"
    return (
        f"{_build_bibine_message(mentions_html)}\n\n"
        f"✅ Chauds ({len(yes_votes)}): {yes_mentions}\n"
        f"❌ Pas chauds ({len(no_votes)}): {no_mentions}"
    )


def _map_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(f'{lat},{lon}')}"


def _week_key_for_chat(chat_id: int, week_iso: str) -> str:
    return f"{chat_id}:{week_iso}"


def _normalize_place_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _build_place_keyboard(proposals: list[dict], votes: list[dict]) -> InlineKeyboardMarkup:
    counts = Counter(int(v.get("proposal_idx", -1)) for v in votes if isinstance(v, dict))
    rows: list[list[InlineKeyboardButton]] = []
    for idx, proposal in enumerate(proposals):
        name = str(proposal.get("name") or proposal.get("query") or f"Option {idx + 1}")
        rows.append([
            InlineKeyboardButton(
                text=f"📍 {name[:30]} ({counts.get(idx, 0)})",
                callback_data=f"bibine_place:{idx}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_place_poll_text(week_iso: str, proposals: list[dict], votes: list[dict]) -> str:
    counts = Counter(int(v.get("proposal_idx", -1)) for v in votes if isinstance(v, dict))
    lines = [
        f"🍺 Vote bibine - semaine du {week_iso}",
        "",
        "Choisissez le bar:",
    ]
    for idx, proposal in enumerate(proposals):
        name = html.escape(str(proposal.get("name") or proposal.get("query") or f"Option {idx + 1}"))
        address = html.escape(str(proposal.get("address") or "Adresse inconnue"))
        lat = float(proposal.get("lat", 0))
        lon = float(proposal.get("lon", 0))
        link = html.escape(_map_link(lat, lon))
        lines.append(
            f"{idx + 1}. <b>{name}</b> ({counts.get(idx, 0)} votes)\n"
            f"   {address}\n"
            f"   <a href=\"{link}\">Voir sur la map</a>"
        )
    return "\n".join(lines)


async def _search_place(query: str) -> dict | None:
    api_key = get_settings().google_maps_api_key
    if not api_key:
        logger.warning("GOOGLE_MAPS_API_KEY is not set — bibine place search skipped")
        return None

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "key": api_key,
        "language": "fr",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Place search failed for query=%s: %s", query, exc)
        return None

    payload = resp.json()
    if not isinstance(payload, dict):
        return None

    status = str(payload.get("status") or "UNKNOWN_ERROR")
    if status not in {"OK", "ZERO_RESULTS"}:
        logger.warning("Google Places API error for query=%s: status=%s", query, status)
        return None

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    top = results[0]
    try:
        geometry = top["geometry"]
        location = geometry["location"]
        lat = float(location["lat"])
        lon = float(location["lng"])
    except Exception:
        return None
    name = str(top.get("name") or query)
    address = str(top.get("formatted_address") or query)
    return {
        "query": query,
        "name": name,
        "address": address,
        "lat": lat,
        "lon": lon,
    }


async def _handle_bibine_place_proposal(message: Message, place_query: str) -> None:
    settings = get_settings()
    if not settings.google_maps_api_key:
        await message.reply(
            "⚠️ GOOGLE_MAPS_API_KEY n'est pas configuré. Impossible de rechercher un lieu.",
            disable_notification=True,
        )
        return

    try:
        tz = ZoneInfo(settings.bibine_timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Europe/Paris")
    week_iso = _target_friday_date(datetime.now(tz=tz)).isoformat()
    week_key = _week_key_for_chat(message.chat.id, week_iso)

    place = await _search_place(place_query)
    if not place:
        await message.reply(
            "Je n'ai pas trouvé cet endroit avec Google Maps. Essaie avec plus de détails (ville, rue, etc.).",
            disable_notification=True,
        )
        return

    place_state = await _load_place_state()
    week_state = place_state.get(week_key)
    if not isinstance(week_state, dict):
        week_state = {
            "chat_id": message.chat.id,
            "week_iso": week_iso,
            "proposals": [],
            "poll_message_id": None,
        }

    proposals = week_state.get("proposals")
    if not isinstance(proposals, list):
        proposals = []

    proposer = message.from_user
    proposer_id = proposer.id if proposer else 0
    proposer_label = (
        f"@{proposer.username}" if proposer and proposer.username else (proposer.first_name if proposer else "Utilisateur")
    )
    normalized = _normalize_place_name(str(place["name"]))
    existing_idx = next(
        (
            idx
            for idx, item in enumerate(proposals)
            if isinstance(item, dict) and _normalize_place_name(str(item.get("name", ""))) == normalized
        ),
        -1,
    )

    # Same user + same place => remove the proposal from this week's vote.
    if existing_idx >= 0:
        existing = proposals[existing_idx] if isinstance(proposals[existing_idx], dict) else {}
        proposed_by = int(existing.get("proposed_by", 0))
        if proposed_by != proposer_id:
            owner_label = str(existing.get("proposed_label") or "l'auteur initial")
            await message.reply(
                f"❌ Seul {html.escape(owner_label)} peut retirer cette proposition.",
                parse_mode="HTML",
                disable_notification=True,
            )
            return

        removed = proposals.pop(existing_idx)
        removed_name = str(removed.get("name") or place_query) if isinstance(removed, dict) else place_query

    week_state["proposals"] = proposals
    place_state[week_key] = week_state
    await _save_place_state(place_state)

    polls = await _load_polls()
    poll_message_id = week_state.get("poll_message_id")
    votes: list[dict] = []
    poll_key: str | None = None
    if isinstance(poll_message_id, int):
        candidate_key = _poll_key(message.chat.id, poll_message_id)
        candidate = polls.get(candidate_key)
        if isinstance(candidate, dict) and candidate.get("type") == "place":
            vote_payload = candidate.get("votes")
            if isinstance(vote_payload, list):
                votes = vote_payload
            poll_key = candidate_key

    if existing_idx >= 0:
        filtered_votes: list[dict] = []
        for vote in votes:
            if not isinstance(vote, dict):
                continue
            try:
                idx = int(vote.get("proposal_idx", -1))
            except Exception:
                continue
            if idx == existing_idx:
                continue
            if idx > existing_idx:
                idx -= 1
            updated_vote = dict(vote)
            updated_vote["proposal_idx"] = idx
            filtered_votes.append(updated_vote)
        votes = filtered_votes

        if poll_key is not None:
            poll = polls.get(poll_key, {})
            poll["type"] = "place"
            poll["week_iso"] = week_iso
            poll["proposals"] = proposals
            poll["votes"] = votes
            polls[poll_key] = poll
            await _save_polls(polls)

            if len(proposals) >= 2:
                text = _build_place_poll_text(week_iso=week_iso, proposals=proposals, votes=votes)
                keyboard = _build_place_keyboard(proposals=proposals, votes=votes)
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=int(week_state["poll_message_id"]),
                        text=text,
                        parse_mode="HTML",
                        reply_markup=keyboard,
                    )
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        logger.warning("Could not update bibine place poll after removal: %s", exc)
            elif len(proposals) == 1:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=int(week_state["poll_message_id"]),
                        text=(
                            f"✅ Une seule proposition restante: "
                            f"<b>{html.escape(str(proposals[0].get('name') or 'Bar'))}</b>\n"
                            f"<a href=\"{html.escape(_map_link(float(proposals[0]['lat']), float(proposals[0]['lon'])))}\">"
                            "Voir sur la map</a>"
                        ),
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        logger.warning("Could not update bibine place poll to single remaining place: %s", exc)
            else:
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=int(week_state["poll_message_id"]),
                        text="🧹 Toutes les propositions de lieu ont été retirées.",
                        reply_markup=None,
                    )
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        logger.warning("Could not update empty bibine place poll message: %s", exc)
        else:
            # No poll was ever created for this week (only this proposal existed); confirm removal explicitly.
            await message.reply(
                f"🗑️ Proposition retirée: <b>{html.escape(removed_name)}</b>.",
                parse_mode="HTML",
                disable_notification=True,
            )
        return

    proposals.append(
        {
            **place,
            "proposed_by": proposer_id,
            "proposed_label": proposer_label,
        }
    )

    week_state["proposals"] = proposals
    place_state[week_key] = week_state
    await _save_place_state(place_state)

    if len(proposals) == 1:
        only_place = proposals[0]
        await message.reply(
            f"✅ Une seule proposition pour l'instant: <b>{html.escape(str(only_place.get('name') or place_query))}</b>\n"
            f"<a href=\"{html.escape(_map_link(float(only_place['lat']), float(only_place['lon'])))}\">Voir sur la map</a>",
            parse_mode="HTML",
            disable_notification=True,
        )
        return

    # Refresh vote payload if an existing place poll was already found.
    if poll_key is not None:
        candidate = polls.get(poll_key)
        if isinstance(candidate, dict):
            vote_payload = candidate.get("votes")
            if isinstance(vote_payload, list):
                votes = vote_payload

    if poll_key is None:
        text = _build_place_poll_text(week_iso=week_iso, proposals=proposals, votes=votes)
        keyboard = _build_place_keyboard(proposals=proposals, votes=votes)
        sent = await message.reply(text, parse_mode="HTML", reply_markup=keyboard, disable_notification=False)
        poll_key = _poll_key(message.chat.id, sent.message_id)
        week_state["poll_message_id"] = sent.message_id
        place_state[week_key] = week_state
        polls[poll_key] = {
            "type": "place",
            "week_iso": week_iso,
            "proposals": proposals,
            "votes": votes,
        }
        await _save_place_state(place_state)
        await _save_polls(polls)
        return

    poll = polls.get(poll_key, {})
    poll["type"] = "place"
    poll["week_iso"] = week_iso
    poll["proposals"] = proposals
    poll["votes"] = votes
    polls[poll_key] = poll
    await _save_polls(polls)

    text = _build_place_poll_text(week_iso=week_iso, proposals=proposals, votes=votes)
    keyboard = _build_place_keyboard(proposals=proposals, votes=votes)
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=int(week_state["poll_message_id"]),
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not update bibine place poll: %s", exc)

    # No extra confirmation message: poll edit already reflects the new proposal.


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

    polls = await _load_polls()
    polls[_poll_key(channel_id, sent.message_id)] = {
        "mentions_html": mentions_html,
        "yes_votes": yes_votes,
        "no_votes": no_votes,
    }
    await _save_polls(polls)


@router.callback_query(F.data.startswith("bibine:"))
async def on_bibine_vote(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer()
        return

    action = (callback.data or "").split(":", maxsplit=1)[-1]
    if action not in {"yes", "no"}:
        await callback.answer()
        return

    polls = await _load_polls()
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
    await _save_polls(polls)

    new_text = _build_poll_text(mentions_html, yes_votes, no_votes)
    keyboard = _build_poll_keyboard(yes_count=len(yes_votes), no_count=len(no_votes))
    try:
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not update bibine poll message: %s", exc)
    await callback.answer("Vote enregistré 🍻")


@router.callback_query(F.data.startswith("bibine_place:"))
async def on_bibine_place_vote(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer()
        return

    action = (callback.data or "").split(":", maxsplit=1)[-1]
    try:
        proposal_idx = int(action)
    except ValueError:
        await callback.answer()
        return

    polls = await _load_polls()
    key = _poll_key(callback.message.chat.id, callback.message.message_id)
    poll = polls.get(key)
    if not isinstance(poll, dict) or poll.get("type") != "place":
        await callback.answer("Sondage introuvable ou expiré.", show_alert=True)
        return

    proposals = poll.get("proposals")
    votes = poll.get("votes")
    week_iso = str(poll.get("week_iso") or "")
    if not isinstance(proposals, list) or not isinstance(votes, list):
        await callback.answer("Sondage corrompu.", show_alert=True)
        return
    if proposal_idx < 0 or proposal_idx >= len(proposals):
        await callback.answer("Option invalide.", show_alert=True)
        return

    user_id = callback.from_user.id
    label = f"@{callback.from_user.username}" if callback.from_user.username else (
        callback.from_user.first_name or "Utilisateur"
    )
    votes = [v for v in votes if int(v.get("user_id", 0)) != user_id]
    votes.append({"user_id": user_id, "label": label, "proposal_idx": proposal_idx})

    poll["votes"] = votes
    polls[key] = poll
    await _save_polls(polls)

    text = _build_place_poll_text(week_iso=week_iso, proposals=proposals, votes=votes)
    keyboard = _build_place_keyboard(proposals=proposals, votes=votes)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Could not update bibine place poll message: %s", exc)

    await callback.answer("Vote lieu enregistré 🍻")


@router.message(Command("bibine"))
async def on_bibine(message: Message) -> None:
    if not message.from_user:
        return

    text = (message.text or "").strip()
    place_query = ""
    if " " in text:
        place_query = text.split(" ", maxsplit=1)[1].strip()

    if place_query:
        await _handle_bibine_place_proposal(message, place_query)
        return

    user = message.from_user
    subscribers = await _load_subscribers()

    if user.id in subscribers:
        subscribers.pop(user.id, None)
        await _save_subscribers(subscribers)
        await message.reply("Tu es retiré des pings bibine. 🫡", disable_notification=True)
        return

    subscribers[user.id] = BibineSubscriber(
        user_id=user.id,
        first_name=user.first_name or "Copain",
        username=user.username,
    )
    await _save_subscribers(subscribers)

    settings = get_settings()
    channel_txt = "\n⚠️ BIBINE_CHANNEL_ID n'est pas configuré."
    if settings.bibine_channel_id:
        chat_name = "le groupe bibine"
        channel_link: str | None = None
        try:
            chat = await message.bot.get_chat(settings.bibine_channel_id)
            chat_name = html.escape(chat.title or chat.full_name or "le groupe bibine")
            if chat.username:
                channel_link = f"https://t.me/{chat.username}"
            elif chat.invite_link:
                channel_link = chat.invite_link
        except Exception as exc:
            logger.warning("Could not resolve bibine channel metadata: %s", exc)

        if channel_link:
            channel_txt = (
                "\nLe ping aléatoire sera envoyé entre jeudi 15h-22h et vendredi 09h-17h dans "
                f'<a href="{html.escape(channel_link)}">{chat_name}</a>.'
            )
        else:
            channel_txt = (
                "\nLe ping aléatoire sera envoyé entre jeudi 15h-22h et vendredi 09h-17h dans "
                f"<b>{chat_name}</b>."
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

    subscribers = await _load_subscribers()
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
        state = await _load_state()

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
            await _save_state(state)
            logger.info("New bibine reminder scheduled for week %s at %s.", target_week, scheduled_at.isoformat())

        wait_seconds = (scheduled_at - now).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        subscribers = await _load_subscribers()
        if not subscribers:
            logger.info("No bibine subscribers, skipping reminder for week %s.", target_week)
            state["last_sent_week"] = target_week
            await _save_state(state)
            continue

        mentions = " ".join(sub.mention_html for sub in subscribers.values())

        try:
            await _send_bibine_ping(bot, settings.bibine_channel_id, mentions)
            state["last_sent_week"] = target_week
            await _save_state(state)
            logger.info("Bibine reminder sent for week %s.", target_week)
        except Exception as exc:
            logger.exception("Failed to send bibine reminder: %s", exc)
