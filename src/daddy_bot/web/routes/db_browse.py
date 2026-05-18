"""Admin db_browse screen: paginated read-only table view."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from daddy_bot.core.db import get_connection
from daddy_bot.web.deps import RequireOwner

router = APIRouter()

_ALLOWED_TABLES = {
    "chats",
    "bibine_subscribers",
    "bibine_state",
    "bibine_polls",
    "bibine_place_state",
    "princesse_pool",
    "princesse_state",
    "princesse_history",
    "admin_sessions",
    "broadcast_log",
    "schema_migrations",
}
_PAGE_SIZE = 50


@router.get("", response_class=HTMLResponse)
async def db_browse(
    request: Request,
    user_id: RequireOwner,
    table: str = Query(default=""),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    conn = await get_connection()

    # List all tables from sqlite_master as allowed
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as cur:
        all_tables = [r[0] for r in await cur.fetchall()]

    rows: list[tuple] = []
    columns: list[str] = []
    total = 0
    error: str | None = None

    if table and table in _ALLOWED_TABLES and table in all_tables:
        try:
            async with conn.execute(f"SELECT COUNT(*) FROM [{table}]") as cur:  # noqa: S608
                row = await cur.fetchone()
                total = int(row[0]) if row else 0

            offset = (page - 1) * _PAGE_SIZE
            async with conn.execute(
                f"SELECT * FROM [{table}] LIMIT ? OFFSET ?",
                (_PAGE_SIZE, offset),  # noqa: S608
            ) as cur:
                rows = await cur.fetchall()
                if cur.description:
                    columns = [d[0] for d in cur.description]
        except Exception as exc:
            error = str(exc)

    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    return request.app.state.templates.TemplateResponse(
        request,
        "db_browse.html",
        {
            "user_id": user_id,
            "all_tables": all_tables,
            "table": table,
            "columns": columns,
            "rows": rows,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "error": error,
        },
    )
