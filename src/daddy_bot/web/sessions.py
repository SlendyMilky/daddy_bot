"""Session management helpers: cookie signing + admin_sessions DB operations."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer

from daddy_bot.core.db import get_connection


def _signer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="admin-session")


def sign_session_id(secret_key: str, sid: str) -> str:
    return _signer(secret_key).dumps(sid)


def unsign_session_id(secret_key: str, signed: str, max_age: int = 86400 * 7) -> str | None:
    try:
        return _signer(secret_key).loads(signed, max_age=max_age)
    except BadSignature:
        return None


async def create_session(user_id: int, ttl_hours: int) -> str:
    sid = secrets.token_urlsafe(32)
    expires_at = (datetime.now(tz=UTC) + timedelta(hours=ttl_hours)).isoformat()
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO admin_sessions(sid, user_id, expires_at) VALUES (?, ?, ?)",
        (sid, user_id, expires_at),
    )
    await conn.commit()
    return sid


async def get_session(sid: str) -> dict[str, Any] | None:
    conn = await get_connection()
    async with conn.execute(
        "SELECT user_id, expires_at FROM admin_sessions WHERE sid=?",
        (sid,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {"user_id": row[0], "expires_at": row[1]}


async def delete_session(sid: str) -> None:
    conn = await get_connection()
    await conn.execute("DELETE FROM admin_sessions WHERE sid=?", (sid,))
    await conn.commit()


async def purge_expired_sessions() -> int:
    conn = await get_connection()
    now = datetime.now(tz=UTC).isoformat()
    cur = await conn.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now,))
    await conn.commit()
    return cur.rowcount or 0
