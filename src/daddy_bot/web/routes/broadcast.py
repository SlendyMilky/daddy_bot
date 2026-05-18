"""Admin broadcast screen: send message to a selected chat, view log."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from daddy_bot.db.repositories import broadcast_repo, chats_repo
from daddy_bot.web.csrf import generate_csrf_token, validate_csrf_token
from daddy_bot.web.deps import SESSION_COOKIE, RequireOwner
from daddy_bot.web.sessions import unsign_session_id

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_sid(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return unsign_session_id(request.app.state.secret_key, raw)


def _csrf(request: Request) -> str:
    sid = _get_sid(request)
    return generate_csrf_token(request.app.state.secret_key, sid or "")


def _check_csrf(request: Request, token: str) -> None:
    sid = _get_sid(request)
    if not sid or not validate_csrf_token(request.app.state.secret_key, sid, token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


@router.get("", response_class=HTMLResponse)
async def broadcast_page(request: Request, user_id: RequireOwner) -> HTMLResponse:
    chats = await chats_repo.list_chats()
    log = await broadcast_repo.list_recent(limit=50)

    return request.app.state.templates.TemplateResponse(
        "broadcast.html",
        {
            "request": request,
            "user_id": user_id,
            "chats": chats,
            "log": log,
            "csrf_token": _csrf(request),
        },
    )


@router.post("/send")
async def send_broadcast(
    request: Request,
    user_id: RequireOwner,
    chat_id: int = Form(...),
    text: str = Form(...),
    parse_mode: str = Form(default="HTML"),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _check_csrf(request, csrf_token)
    bot = request.app.state.bot
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available.")

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text cannot be empty.")

    success = True
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode or None)
        logger.info("Admin %d broadcast to chat %d: %.80r", user_id, chat_id, text)
    except Exception as exc:
        success = False
        logger.warning("Broadcast to %d failed: %s", chat_id, exc)

    await broadcast_repo.record(
        sent_by=user_id,
        target_chat_id=chat_id,
        message_preview=text[:200],
        success=success,
    )
    return RedirectResponse("/admin/broadcast", status_code=303)
