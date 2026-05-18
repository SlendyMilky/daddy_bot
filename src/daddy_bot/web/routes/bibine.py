"""Admin bibine screen: subscribers, polls, manual ping, reset state."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from daddy_bot.db.repositories import bibine_repo
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
async def bibine_page(request: Request, user_id: RequireOwner) -> HTMLResponse:
    subscribers = await bibine_repo.list_subscribers()
    polls = await bibine_repo.list_active_polls()
    state = await bibine_repo.all_state()

    return request.app.state.templates.TemplateResponse(
        "bibine.html",
        {
            "request": request,
            "user_id": user_id,
            "subscribers": subscribers,
            "polls": polls,
            "state": state,
            "csrf_token": _csrf(request),
        },
    )


@router.post("/remove_subscriber")
async def remove_subscriber(
    request: Request,
    user_id: RequireOwner,
    target_user_id: int = Form(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _check_csrf(request, csrf_token)
    removed = await bibine_repo.remove_subscriber(target_user_id)
    logger.info("Admin %d removed bibine subscriber %d (found=%s)", user_id, target_user_id, removed)
    return RedirectResponse("/admin/bibine", status_code=303)


@router.post("/ping")
async def manual_ping(
    request: Request,
    user_id: RequireOwner,
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _check_csrf(request, csrf_token)
    bot = request.app.state.bot
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not available.")

    # Trigger bibine ping by importing the scheduler trigger function
    try:
        from daddy_bot.modules.bibine import send_bibine_ping

        await send_bibine_ping(bot)
        logger.info("Admin %d triggered manual bibine ping.", user_id)
    except Exception as exc:
        logger.exception("Manual bibine ping failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RedirectResponse("/admin/bibine", status_code=303)


@router.post("/reset_state")
async def reset_state(
    request: Request,
    user_id: RequireOwner,
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _check_csrf(request, csrf_token)
    for key in ("scheduled_week", "scheduled_at", "last_sent_week"):
        await bibine_repo.delete_state(key)
    logger.info("Admin %d reset bibine weekly state.", user_id)
    return RedirectResponse("/admin/bibine", status_code=303)
