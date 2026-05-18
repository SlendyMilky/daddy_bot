"""Admin princesse screen: pool per chat, history, test ritual."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from daddy_bot.core.config import get_settings
from daddy_bot.db.repositories import princesse_repo
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
async def princesse_page(request: Request, user_id: RequireOwner) -> HTMLResponse:
    settings = get_settings()
    chat_ids = settings.princesse_morning_chat_id_tuple()
    pools = await princesse_repo.list_pools_for_chats(chat_ids)
    history = await princesse_repo.list_history(limit=20)
    state = await princesse_repo.all_state()

    return request.app.state.templates.TemplateResponse(
        request,
        "princesse.html",
        {
            "user_id": user_id,
            "pools": pools,
            "history": history,
            "state": state,
            "csrf_token": _csrf(request),
        },
    )


@router.post("/remove_member")
async def remove_member(
    request: Request,
    user_id: RequireOwner,
    chat_id: int = Form(...),
    target_user_id: int = Form(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _check_csrf(request, csrf_token)
    removed = await princesse_repo.remove_member(chat_id, target_user_id)
    logger.info(
        "Admin %d removed user %d from princesse pool (chat=%d, found=%s)",
        user_id,
        target_user_id,
        chat_id,
        removed,
    )
    return RedirectResponse("/admin/princesse", status_code=303)


@router.post("/test_ritual")
async def test_ritual(
    request: Request,
    user_id: RequireOwner,
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _check_csrf(request, csrf_token)
    bot = request.app.state.bot
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available.")

    try:
        from daddy_bot.modules.princesse_morning import send_princesse_morning

        await send_princesse_morning(bot, target_chat_id=user_id)
        logger.info("Admin %d triggered princesse ritual test.", user_id)
    except Exception as exc:
        logger.exception("Princesse test ritual failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RedirectResponse("/admin/princesse", status_code=303)
