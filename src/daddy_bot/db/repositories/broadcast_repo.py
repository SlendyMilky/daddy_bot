"""SQLite-backed repository for the broadcast audit log."""

from __future__ import annotations

from datetime import UTC, datetime

from daddy_bot.core.db import get_connection


async def record(
    sent_by: int,
    target_chat_id: int,
    message_preview: str,
    success: bool,
) -> None:
    conn = await get_connection()
    preview = message_preview[:200]
    await conn.execute(
        "INSERT INTO broadcast_log(sent_at, sent_by, target_chat_id, message_preview, success) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(tz=UTC).isoformat(),
            sent_by,
            target_chat_id,
            preview,
            1 if success else 0,
        ),
    )
    await conn.commit()


async def list_recent(limit: int = 100) -> list[dict]:
    conn = await get_connection()
    async with conn.execute(
        "SELECT id, sent_at, sent_by, target_chat_id, message_preview, success "
        "FROM broadcast_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "id": r[0],
            "sent_at": r[1],
            "sent_by": r[2],
            "target_chat_id": r[3],
            "message_preview": r[4],
            "success": bool(r[5]),
        }
        for r in rows
    ]
