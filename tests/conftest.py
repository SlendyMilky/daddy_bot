"""Shared pytest fixtures: each test gets a fresh aiosqlite connection pointing at a temp DB."""
from __future__ import annotations

from pathlib import Path

import pytest_asyncio

from daddy_bot.core import db as db_module


@pytest_asyncio.fixture
async def temp_db(tmp_path: Path):
    """Reset the global aiosqlite connection to a fresh file inside `tmp_path` and run migrations."""
    # Reset module-level singletons so set_db_path is allowed.
    await db_module.close_connection()
    db_module._connection = None  # type: ignore[attr-defined]
    db_path = tmp_path / "test.db"
    db_module.set_db_path(db_path)
    await db_module.run_migrations()
    try:
        yield db_path
    finally:
        await db_module.close_connection()
        db_module._connection = None  # type: ignore[attr-defined]
        db_module._db_path = db_module._DEFAULT_DB_PATH  # type: ignore[attr-defined]
