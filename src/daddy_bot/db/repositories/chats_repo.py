"""SQLite-backed repository for the chats registry (replaces chats.json)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from daddy_bot.core.db import get_connection


@dataclass(slots=True)
class ChatEntry:
    id: int
    type: str
    title: str | None
    username: str | None
    last_seen_at: str | None


async def upsert_chat(
    chat_id: int,
    chat_type: str,
    title: str | None,
    username: str | None,
    touch_last_seen: bool = True,
) -> bool:
    """Insert or update a chat row. Returns True if data actually changed."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT type, title, username FROM chats WHERE id=?",
        (chat_id,),
    ) as cur:
        existing = await cur.fetchone()

    last_seen = datetime.now(tz=UTC).isoformat(timespec="seconds") if touch_last_seen else None
    changed = existing is None or (existing[0], existing[1], existing[2]) != (chat_type, title, username)

    await conn.execute(
        """
        INSERT INTO chats(id, type, title, username, last_seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            type=excluded.type,
            title=excluded.title,
            username=excluded.username,
            last_seen_at=COALESCE(excluded.last_seen_at, chats.last_seen_at)
        """,
        (chat_id, chat_type, title, username, last_seen),
    )
    await conn.commit()
    return changed


async def remove_chat(chat_id: int) -> bool:
    conn = await get_connection()
    cur = await conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    await conn.commit()
    return (cur.rowcount or 0) > 0


async def list_chats() -> list[ChatEntry]:
    conn = await get_connection()
    async with conn.execute(
        "SELECT id, type, title, username, last_seen_at FROM chats ORDER BY type, id"
    ) as cur:
        rows = await cur.fetchall()
    return [ChatEntry(id=r[0], type=r[1], title=r[2], username=r[3], last_seen_at=r[4]) for r in rows]


async def count_chats() -> int:
    conn = await get_connection()
    async with conn.execute("SELECT COUNT(*) FROM chats") as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0
