"""Admin dashboard: summary stats."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from daddy_bot.db.repositories import bibine_repo, broadcast_repo, chats_repo, princesse_repo
from daddy_bot.web.csrf import generate_csrf_token
from daddy_bot.web.deps import SESSION_COOKIE, RequireOwner
from daddy_bot.web.sessions import unsign_session_id

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user_id: RequireOwner) -> HTMLResponse:
    chat_count = await chats_repo.count_chats()
    chats = await chats_repo.list_chats()
    subscribers = await bibine_repo.list_subscribers()
    bibine_state = await bibine_repo.all_state()
    active_polls = await bibine_repo.list_active_polls()
    princesse_history = await princesse_repo.list_history(limit=10)
    recent_broadcasts = await broadcast_repo.list_recent(limit=5)

    broadcast_success = sum(1 for b in recent_broadcasts if b["success"])
    broadcast_fail = len(recent_broadcasts) - broadcast_success

    sid = _get_sid(request)
    csrf = generate_csrf_token(request.app.state.secret_key, sid) if sid else ""

    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user_id": user_id,
            "chat_count": chat_count,
            "chats": chats,
            "subscriber_count": len(subscribers),
            "bibine_state": bibine_state,
            "active_poll_count": len(active_polls),
            "active_polls": active_polls[:3],
            "princesse_history": princesse_history,
            "recent_broadcasts": recent_broadcasts,
            "broadcast_success": broadcast_success,
            "broadcast_fail": broadcast_fail,
            "csrf_token": csrf,
        },
    )


def _get_sid(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return unsign_session_id(request.app.state.secret_key, raw)
