"""Admin dashboard: summary stats."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from daddy_bot.db.repositories import bibine_repo, chats_repo, princesse_repo
from daddy_bot.web.csrf import generate_csrf_token
from daddy_bot.web.deps import SESSION_COOKIE, RequireOwner
from daddy_bot.web.sessions import unsign_session_id

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user_id: RequireOwner) -> HTMLResponse:
    chat_count = await chats_repo.count_chats()
    subscribers = await bibine_repo.list_subscribers()
    bibine_state = await bibine_repo.all_state()
    princesse_history = await princesse_repo.list_history(limit=5)

    sid = _get_sid(request)
    csrf = generate_csrf_token(request.app.state.secret_key, sid) if sid else ""

    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user_id": user_id,
            "chat_count": chat_count,
            "subscriber_count": len(subscribers),
            "bibine_state": bibine_state,
            "princesse_history": princesse_history,
            "csrf_token": csrf,
        },
    )


def _get_sid(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return unsign_session_id(request.app.state.secret_key, raw)
