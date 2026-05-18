"""Async SQLite engine and migration runner.

A single module-global aiosqlite connection is kept open for the lifetime of the
process. WAL mode allows the bot and the (future) admin web server to read
concurrently without blocking each other.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "daddy_bot.db"

_VERSION_RE = re.compile(r"^(\d+)_")

_connection: aiosqlite.Connection | None = None
_db_path: Path = _DEFAULT_DB_PATH


def set_db_path(path: Path | str) -> None:
    """Override the database file location. Must be called before `get_connection`."""
    global _db_path, _connection
    if _connection is not None:
        raise RuntimeError("Cannot change DB path after connection has been opened")
    _db_path = Path(path)


def get_db_path() -> Path:
    return _db_path


async def get_connection() -> aiosqlite.Connection:
    """Return the singleton aiosqlite connection, opening it on first call."""
    global _connection
    if _connection is None:
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(_db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.commit()
        _connection = conn
    return _connection


async def close_connection() -> None:
    global _connection
    if _connection is not None:
        try:
            await _connection.close()
        finally:
            _connection = None


def _migration_files() -> list[tuple[int, Path]]:
    if not _MIGRATIONS_DIR.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        m = _VERSION_RE.match(path.name)
        if not m:
            continue
        out.append((int(m.group(1)), path))
    out.sort(key=lambda item: item[0])
    return out


async def run_migrations() -> None:
    """Apply all migration files in `db/migrations/` not yet recorded in `schema_migrations`."""
    conn = await get_connection()
    # The very first migration creates schema_migrations itself, so handle the bootstrap.
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    await conn.commit()

    async with conn.execute("SELECT version FROM schema_migrations") as cur:
        applied = {row[0] async for row in cur}

    for version, path in _migration_files():
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        logger.info("Applying migration %s (%s)", version, path.name)
        try:
            await conn.executescript(sql)
            await conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(tz=UTC).isoformat()),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            logger.exception("Migration %s failed", version)
            raise
