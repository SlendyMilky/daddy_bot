"""SQLite-backed repository for bibine subscribers, scheduler state, polls and place votes."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass

from daddy_bot.core.db import get_connection


@dataclass(slots=True)
class BibineSubscriber:
    user_id: int
    first_name: str
    username: str | None

    @property
    def mention_html(self) -> str:
        label = f"@{self.username}" if self.username else self.first_name
        return f'<a href="tg://user?id={self.user_id}">{html.escape(label)}</a>'


# --- Subscribers -----------------------------------------------------------------


async def add_subscriber(subscriber: BibineSubscriber) -> None:
    conn = await get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO bibine_subscribers(user_id, first_name, username) VALUES (?, ?, ?)",
        (subscriber.user_id, subscriber.first_name, subscriber.username),
    )
    await conn.commit()


async def remove_subscriber(user_id: int) -> bool:
    conn = await get_connection()
    cur = await conn.execute("DELETE FROM bibine_subscribers WHERE user_id=?", (user_id,))
    await conn.commit()
    return (cur.rowcount or 0) > 0


async def has_subscriber(user_id: int) -> bool:
    conn = await get_connection()
    async with conn.execute("SELECT 1 FROM bibine_subscribers WHERE user_id=?", (user_id,)) as cur:
        row = await cur.fetchone()
    return row is not None


async def list_subscribers() -> list[BibineSubscriber]:
    conn = await get_connection()
    async with conn.execute(
        "SELECT user_id, first_name, username FROM bibine_subscribers ORDER BY user_id"
    ) as cur:
        rows = await cur.fetchall()
    return [BibineSubscriber(user_id=r[0], first_name=r[1], username=r[2]) for r in rows]


# --- Scheduler state (key/value) -------------------------------------------------


async def get_state(key: str) -> str | None:
    conn = await get_connection()
    async with conn.execute("SELECT value FROM bibine_state WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def set_state(key: str, value: str) -> None:
    conn = await get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO bibine_state(key, value) VALUES (?, ?)",
        (key, value),
    )
    await conn.commit()


async def delete_state(key: str) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM bibine_state WHERE key=?", (key,))
    await conn.commit()


async def all_state() -> dict[str, str]:
    conn = await get_connection()
    async with conn.execute("SELECT key, value FROM bibine_state") as cur:
        rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


# --- Polls (ping or place) -------------------------------------------------------


async def get_poll(chat_id: int, message_id: int) -> dict | None:
    conn = await get_connection()
    async with conn.execute(
        "SELECT type, payload FROM bibine_polls WHERE chat_id=? AND message_id=?",
        (chat_id, message_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[1])
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        payload.setdefault("type", row[0])
    return payload if isinstance(payload, dict) else None


async def save_poll(chat_id: int, message_id: int, poll_type: str, payload: dict) -> None:
    conn = await get_connection()
    serialized = json.dumps(payload, ensure_ascii=False)
    await conn.execute(
        """
        INSERT INTO bibine_polls(chat_id, message_id, type, payload)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET type=excluded.type, payload=excluded.payload
        """,
        (chat_id, message_id, poll_type, serialized),
    )
    await conn.commit()


async def list_active_polls() -> list[dict]:
    conn = await get_connection()
    async with conn.execute(
        "SELECT chat_id, message_id, type, payload, created_at FROM bibine_polls ORDER BY created_at DESC"
    ) as cur:
        rows = await cur.fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            payload = json.loads(r[3])
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        out.append(
            {
                "chat_id": r[0],
                "message_id": r[1],
                "type": r[2],
                "payload": payload,
                "created_at": r[4],
            }
        )
    return out


# --- Place state (per chat/week) -------------------------------------------------


async def get_place_state(chat_id: int, week_iso: str) -> dict | None:
    conn = await get_connection()
    async with conn.execute(
        "SELECT poll_message_id, proposals FROM bibine_place_state WHERE chat_id=? AND week_iso=?",
        (chat_id, week_iso),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    try:
        proposals = json.loads(row[1])
    except json.JSONDecodeError:
        proposals = []
    return {
        "chat_id": chat_id,
        "week_iso": week_iso,
        "poll_message_id": row[0],
        "proposals": proposals if isinstance(proposals, list) else [],
    }


async def save_place_state(chat_id: int, week_iso: str, poll_message_id: int | None, proposals: list) -> None:
    conn = await get_connection()
    serialized = json.dumps(proposals, ensure_ascii=False)
    await conn.execute(
        """
        INSERT INTO bibine_place_state(chat_id, week_iso, poll_message_id, proposals)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, week_iso) DO UPDATE SET
            poll_message_id=excluded.poll_message_id,
            proposals=excluded.proposals
        """,
        (chat_id, week_iso, poll_message_id, serialized),
    )
    await conn.commit()
