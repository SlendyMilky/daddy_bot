"""SQLite-backed repository for princesse morning pool, state and send history."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime

from daddy_bot.core.db import get_connection


@dataclass(slots=True)
class PoolMember:
    user_id: int
    first_name: str
    username: str | None

    @property
    def mention_html(self) -> str:
        label = f"@{self.username}" if self.username else self.first_name
        return f'<a href="tg://user?id={self.user_id}">{html.escape(label)}</a>'


# --- Pool ------------------------------------------------------------------------


async def upsert_member(chat_id: int, member: PoolMember) -> bool:
    """Insert or update a pool member; returns True if anything changed."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT first_name, username FROM princesse_pool WHERE chat_id=? AND user_id=?",
        (chat_id, member.user_id),
    ) as cur:
        row = await cur.fetchone()

    if row is not None and row[0] == member.first_name and row[1] == member.username:
        return False

    await conn.execute(
        """
        INSERT INTO princesse_pool(chat_id, user_id, first_name, username, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            first_name=excluded.first_name,
            username=excluded.username,
            updated_at=excluded.updated_at
        """,
        (chat_id, member.user_id, member.first_name, member.username, datetime.now(tz=UTC).isoformat()),
    )
    await conn.commit()
    return True


async def remove_member(chat_id: int, user_id: int) -> bool:
    conn = await get_connection()
    cur = await conn.execute(
        "DELETE FROM princesse_pool WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
    )
    await conn.commit()
    return (cur.rowcount or 0) > 0


async def clear_pool(chat_id: int) -> int:
    conn = await get_connection()
    cur = await conn.execute("DELETE FROM princesse_pool WHERE chat_id=?", (chat_id,))
    await conn.commit()
    return cur.rowcount or 0


async def list_pool(chat_id: int) -> list[PoolMember]:
    conn = await get_connection()
    async with conn.execute(
        "SELECT user_id, first_name, username FROM princesse_pool WHERE chat_id=? ORDER BY user_id",
        (chat_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [PoolMember(user_id=r[0], first_name=r[1], username=r[2]) for r in rows]


async def list_pools_for_chats(chat_ids: tuple[int, ...]) -> dict[int, list[PoolMember]]:
    out: dict[int, list[PoolMember]] = {cid: [] for cid in chat_ids}
    if not chat_ids:
        return out
    conn = await get_connection()
    placeholders = ",".join("?" for _ in chat_ids)
    async with conn.execute(
        f"SELECT chat_id, user_id, first_name, username FROM princesse_pool WHERE chat_id IN ({placeholders}) ORDER BY chat_id, user_id",
        chat_ids,
    ) as cur:
        rows = await cur.fetchall()
    for r in rows:
        out.setdefault(r[0], []).append(PoolMember(user_id=r[1], first_name=r[2], username=r[3]))
    return out


# --- State ----------------------------------------------------------------------


async def get_state(key: str) -> str | None:
    conn = await get_connection()
    async with conn.execute("SELECT value FROM princesse_state WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def set_state(key: str, value: str) -> None:
    conn = await get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO princesse_state(key, value) VALUES (?, ?)",
        (key, value),
    )
    await conn.commit()


async def delete_state(key: str) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM princesse_state WHERE key=?", (key,))
    await conn.commit()


async def all_state() -> dict[str, str]:
    conn = await get_connection()
    async with conn.execute("SELECT key, value FROM princesse_state") as cur:
        rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


# --- History --------------------------------------------------------------------


async def record_send(chat_id: int, user_id: int, voice_file: str) -> None:
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO princesse_history(sent_at, chat_id, user_id, voice_file) VALUES (?, ?, ?, ?)",
        (datetime.now(tz=UTC).isoformat(), chat_id, user_id, voice_file),
    )
    await conn.commit()


async def list_history(limit: int = 50) -> list[dict]:
    conn = await get_connection()
    async with conn.execute(
        "SELECT id, sent_at, chat_id, user_id, voice_file FROM princesse_history ORDER BY id DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [{"id": r[0], "sent_at": r[1], "chat_id": r[2], "user_id": r[3], "voice_file": r[4]} for r in rows]
