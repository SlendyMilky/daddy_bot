"""FastAPI dependencies for admin panel authentication."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from daddy_bot.core.config import get_settings
from daddy_bot.web.sessions import get_session, unsign_session_id

logger = logging.getLogger(__name__)

SESSION_COOKIE = "admin_session"


async def _get_owner_id(request: Request) -> int:
    """Validate the session cookie and return the authenticated owner user_id."""
    settings = get_settings()
    secret_key = request.app.state.secret_key

    raw_cookie: str | None = request.cookies.get(SESSION_COOKIE)
    if not raw_cookie:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

    sid = unsign_session_id(secret_key, raw_cookie)
    if not sid:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

    session = await get_session(sid)
    if not session:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

    # Check expiry
    expires_at = session["expires_at"]
    try:
        if datetime.fromisoformat(expires_at) < datetime.now(tz=UTC):
            raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    except ValueError as exc:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"}) from exc

    user_id: int = session["user_id"]
    # Re-verify owner on every request (so revoking OWNER_IDS takes effect immediately)
    if user_id not in settings.owner_id_set():
        logger.warning("Session user %d is no longer in OWNER_IDS; denying access.", user_id)
        raise HTTPException(status_code=403, detail="Access revoked.")

    return user_id


RequireOwner = Annotated[int, Depends(_get_owner_id)]
