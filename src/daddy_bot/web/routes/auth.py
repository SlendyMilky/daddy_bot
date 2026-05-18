"""Admin panel auth routes: login (OIDC redirect), callback, logout."""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from daddy_bot.core.config import get_settings
from daddy_bot.web.deps import SESSION_COOKIE
from daddy_bot.web.sessions import create_session, delete_session, sign_session_id, unsign_session_id

logger = logging.getLogger(__name__)

router = APIRouter()

_PKCE_COOKIE = "admin_pkce"
_PKCE_COOKIE_MAX_AGE = 300  # 5 minutes


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> HTMLResponse:
    """Redirect user to Telegram OIDC authorization endpoint."""
    oidc = request.app.state.oidc_client
    if oidc is None:
        return HTMLResponse(
            "<h1>Admin panel not configured</h1>"
            "<p>Set TELEGRAM_OIDC_CLIENT_ID and TELEGRAM_OIDC_CLIENT_SECRET to enable login.</p>",
            status_code=503,
        )

    state = secrets.token_urlsafe(32)
    from daddy_bot.services.telegram_oidc import generate_pkce_pair

    code_verifier, _ = generate_pkce_pair()

    secret_key = request.app.state.secret_key
    # Store state+verifier in a short-lived signed cookie
    signer = __import__("itsdangerous").URLSafeTimedSerializer(secret_key, salt="pkce")
    pkce_value = signer.dumps({"state": state, "verifier": code_verifier})

    auth_url = await oidc.build_authorization_url(state=state, code_verifier=code_verifier)
    response = RedirectResponse(auth_url, status_code=302)
    response.set_cookie(
        _PKCE_COOKIE,
        pkce_value,
        max_age=_PKCE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response  # type: ignore[return-value]


@router.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(request: Request, code: str = "", state: str = "") -> HTMLResponse:
    """Handle Telegram OIDC callback, validate id_token, create session."""
    oidc = request.app.state.oidc_client
    if oidc is None:
        raise HTTPException(status_code=503, detail="OIDC not configured.")

    secret_key = request.app.state.secret_key
    signer = __import__("itsdangerous").URLSafeTimedSerializer(secret_key, salt="pkce")

    pkce_cookie = request.cookies.get(_PKCE_COOKIE)
    if not pkce_cookie:
        raise HTTPException(status_code=400, detail="Missing PKCE cookie. Please try logging in again.")

    try:
        pkce_data = signer.loads(pkce_cookie, max_age=_PKCE_COOKIE_MAX_AGE)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="PKCE cookie expired or invalid.") from exc

    if not secrets.compare_digest(pkce_data.get("state", ""), state):
        raise HTTPException(status_code=400, detail="State mismatch. Possible CSRF.")

    code_verifier: str = pkce_data["verifier"]

    try:
        identity = await oidc.exchange_code(code=code, code_verifier=code_verifier)
    except Exception as exc:
        logger.warning("OIDC token exchange failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}") from exc

    settings = get_settings()
    if identity.user_id not in settings.owner_id_set():
        logger.warning("Unauthorized login attempt by Telegram user %d", identity.user_id)
        raise HTTPException(status_code=403, detail="Access denied.")

    sid = await create_session(identity.user_id, settings.admin_session_ttl_hours)
    signed_sid = sign_session_id(secret_key, sid)

    response = RedirectResponse("/admin/", status_code=302)
    response.delete_cookie(_PKCE_COOKIE)
    response.set_cookie(
        SESSION_COOKIE,
        signed_sid,
        max_age=settings.admin_session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response  # type: ignore[return-value]


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Invalidate the current session and clear the cookie."""
    secret_key = request.app.state.secret_key
    raw_cookie = request.cookies.get(SESSION_COOKIE)
    if raw_cookie:
        sid = unsign_session_id(secret_key, raw_cookie)
        if sid:
            await delete_session(sid)

    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response
