"""Admin live-chat screen: relay Telegram group messages to the browser via SSE
and allow the admin to send replies through the bot — all in real time, with
zero persistence (in-memory only, cleared on restart).
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from daddy_bot.db.repositories import chats_repo
from daddy_bot.web.csrf import generate_csrf_token, validate_csrf_token
from daddy_bot.web.deps import SESSION_COOKIE, RequireOwner
from daddy_bot.web.message_hub import hub
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
async def chat_index(request: Request, user_id: RequireOwner) -> HTMLResponse:
    chats = await chats_repo.list_chats()
    return request.app.state.templates.TemplateResponse(
        request,
        "chat.html",
        {
            "user_id": user_id,
            "chats": chats,
            "active_chat": None,
            "recent_messages": [],
            "csrf_token": _csrf(request),
        },
    )


@router.get("/{chat_id}", response_class=HTMLResponse)
async def chat_room(request: Request, chat_id: int, user_id: RequireOwner) -> HTMLResponse:
    chats = await chats_repo.list_chats()
    active = next((c for c in chats if c.id == chat_id), None)
    if active is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    recent = hub.get_recent(chat_id)

    return request.app.state.templates.TemplateResponse(
        request,
        "chat.html",
        {
            "user_id": user_id,
            "chats": chats,
            "active_chat": active,
            "recent_messages": recent,
            "csrf_token": _csrf(request),
        },
    )


@router.get("/stream/{chat_id}")
async def chat_stream(request: Request, chat_id: int, user_id: RequireOwner) -> StreamingResponse:
    """SSE endpoint — streams live Telegram messages for a given chat to the browser."""
    q = hub.subscribe(chat_id)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20.0)
                    if msg is None:
                        break
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n".encode()
                except TimeoutError:
                    yield b'data: {"keep":"alive"}\n\n'
        finally:
            hub.unsubscribe(chat_id, q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/send")
async def chat_send(
    request: Request,
    user_id: RequireOwner,
    chat_id: int = Form(...),
    text: str = Form(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _check_csrf(request, csrf_token)
    bot = request.app.state.bot
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available.")

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        await bot.send_message(chat_id=chat_id, text=text)
        logger.info("Admin %d sent message to chat %d via live-chat", user_id, chat_id)
    except Exception as exc:
        logger.warning("Failed to send message to chat %d: %s", chat_id, exc)
        raise HTTPException(status_code=502, detail=f"Telegram error: {exc}") from exc

    return RedirectResponse(f"/admin/chat/{chat_id}", status_code=303)
