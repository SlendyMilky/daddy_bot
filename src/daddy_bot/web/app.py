"""FastAPI admin panel app factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from daddy_bot.web.routes import auth, bibine, broadcast, dashboard, db_browse, logs, princesse
from daddy_bot.web.sessions import purge_expired_sessions

if TYPE_CHECKING:
    from aiogram import Bot

    from daddy_bot.core.config import Settings

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def _resolve_secret_key(settings: Settings) -> str:
    """Return secret key from config or generate+persist one in data/.secret_key."""
    if settings.admin_web_secret_key:
        return settings.admin_web_secret_key
    key_file = Path("data") / ".secret_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_text().strip()
    import secrets

    key = secrets.token_urlsafe(48)
    key_file.write_text(key)
    key_file.chmod(0o600)
    logger.info("Generated new admin secret key at %s", key_file)
    return key


def create_admin_app(*, bot: Bot | None, settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        purged = await purge_expired_sessions()
        if purged:
            logger.info("Purged %d expired admin sessions.", purged)
        yield

    app = FastAPI(title="Daddy Bot Admin", docs_url=None, redoc_url=None, lifespan=lifespan)

    secret_key = _resolve_secret_key(settings)

    # Build OIDC client if credentials are configured
    oidc_client = None
    if settings.telegram_oidc_client_id and settings.telegram_oidc_client_secret:
        from daddy_bot.services.telegram_oidc import TelegramOIDCClient

        redirect_uri = f"{settings.admin_web_public_url.rstrip('/')}/admin/auth/callback"
        oidc_client = TelegramOIDCClient(
            client_id=settings.telegram_oidc_client_id,
            client_secret=settings.telegram_oidc_client_secret,
            discovery_url=settings.telegram_oidc_discovery_url,
            redirect_uri=redirect_uri,
            cache_path=Path("data") / "oidc_metadata.json",
        )

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Expose app-wide state
    app.state.bot = bot
    app.state.settings = settings
    app.state.secret_key = secret_key
    app.state.oidc_client = oidc_client
    app.state.templates = templates

    # Mount static files if dir exists (created by Dockerfile tailwind build)
    if _STATIC_DIR.exists():
        app.mount("/admin/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Install ring-buffer log handler
    logs.install_log_handler()

    # Include routers under /admin prefix
    app.include_router(auth.router, prefix="/admin")
    app.include_router(dashboard.router, prefix="/admin")
    app.include_router(bibine.router, prefix="/admin/bibine")
    app.include_router(princesse.router, prefix="/admin/princesse")
    app.include_router(broadcast.router, prefix="/admin/broadcast")
    app.include_router(logs.router, prefix="/admin/logs")
    app.include_router(db_browse.router, prefix="/admin/db")

    @app.get("/admin/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse("/admin/", status_code=302)

    return app
