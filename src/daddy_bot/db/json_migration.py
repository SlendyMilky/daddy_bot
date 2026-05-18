"""One-shot JSON -> SQLite migrator, run automatically at boot.

Design:

- Idempotent: each file is recorded in `json_imports` once successfully imported.
  Re-running the bot is a no-op for files already imported.
- Transactional per file: if any row in a JSON fails to import, the whole file is rolled back,
  the JSON stays in place on disk, and we move on to the next file. The bot still boots.
- Safety net: before any import, a tar.gz of all known JSONs (those that exist) is written
  to `data/archive/_pre_migration_backup_{ts}.tar.gz`. Never overwritten.
- After a successful import & commit, the source JSON is moved to
  `data/archive/{YYYY-MM-DD_HHMMSS}/<name>.json`. Collisions get `_1`, `_2`, etc.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from daddy_bot.core.db import get_connection, run_migrations

logger = logging.getLogger(__name__)

# Files we know how to import. Order matters only for log readability.
KNOWN_FILES: tuple[str, ...] = (
    "bibine_subscribers.json",
    "bibine_state.json",
    "bibine_polls.json",
    "bibine_places.json",
    "princesse_morning_targets.json",
    "princesse_morning_state.json",
    "chats.json",
)


def _data_dir(root: Path) -> Path:
    return root / "data"


def _archive_dir(root: Path) -> Path:
    return root / "data" / "archive"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d_%H%M%S")


def _build_safety_tarball(root: Path, ts: str) -> Path | None:
    data_dir = _data_dir(root)
    existing = [data_dir / name for name in KNOWN_FILES if (data_dir / name).is_file()]
    if not existing:
        return None
    archive = _archive_dir(root)
    archive.mkdir(parents=True, exist_ok=True)
    tar_path = archive / f"_pre_migration_backup_{ts}.tar.gz"
    if tar_path.exists():
        return tar_path
    with tarfile.open(tar_path, "w:gz") as tar:
        for fpath in existing:
            tar.add(fpath, arcname=fpath.name)
    logger.info("JSON migration safety tarball written: %s", tar_path)
    return tar_path


def _archive_json(root: Path, ts: str, filename: str) -> Path | None:
    src = _data_dir(root) / filename
    if not src.is_file():
        return None
    target_dir = _archive_dir(root) / ts
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    suffix = 1
    while target.exists():
        target = target_dir / f"{src.stem}_{suffix}{src.suffix}"
        suffix += 1
    shutil.move(str(src), str(target))
    return target


# --- Per-file import logic ------------------------------------------------------

async def _import_bibine_subscribers(conn, payload) -> int:
    if not isinstance(payload, list):
        return 0
    count = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            uid = int(item["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        await conn.execute(
            "INSERT OR REPLACE INTO bibine_subscribers(user_id, first_name, username) VALUES (?, ?, ?)",
            (uid, str(item.get("first_name") or "Copain"),
             str(item["username"]) if item.get("username") else None),
        )
        count += 1
    return count


async def _import_kv(conn, payload, table: str) -> int:
    if not isinstance(payload, dict):
        return 0
    count = 0
    for k, v in payload.items():
        if v is None:
            continue
        await conn.execute(
            f"INSERT OR REPLACE INTO {table}(key, value) VALUES (?, ?)",
            (str(k), str(v)),
        )
        count += 1
    return count


async def _import_bibine_polls(conn, payload) -> int:
    if not isinstance(payload, dict):
        return 0
    count = 0
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id_str, msg_id_str = str(key).split(":", maxsplit=1)
            chat_id = int(chat_id_str)
            message_id = int(msg_id_str)
        except (ValueError, AttributeError):
            continue
        poll_type = str(value.get("type") or ("place" if "proposals" in value else "ping"))
        await conn.execute(
            "INSERT OR REPLACE INTO bibine_polls(chat_id, message_id, type, payload) VALUES (?, ?, ?, ?)",
            (chat_id, message_id, poll_type, json.dumps(value, ensure_ascii=False)),
        )
        count += 1
    return count


async def _import_bibine_places(conn, payload) -> int:
    if not isinstance(payload, dict):
        return 0
    count = 0
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id_str, week_iso = str(key).split(":", maxsplit=1)
            chat_id = int(chat_id_str)
        except (ValueError, AttributeError):
            # Also accept value-side chat_id/week_iso when key is not the composite.
            chat_id = int(value.get("chat_id", 0))
            week_iso = str(value.get("week_iso") or "")
            if not chat_id or not week_iso:
                continue
        proposals = value.get("proposals")
        if not isinstance(proposals, list):
            proposals = []
        poll_message_id = value.get("poll_message_id")
        try:
            poll_message_id_int = int(poll_message_id) if poll_message_id is not None else None
        except (TypeError, ValueError):
            poll_message_id_int = None
        await conn.execute(
            "INSERT OR REPLACE INTO bibine_place_state(chat_id, week_iso, poll_message_id, proposals) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, week_iso, poll_message_id_int, json.dumps(proposals, ensure_ascii=False)),
        )
        count += 1
    return count


async def _import_princesse_targets(conn, payload) -> int:
    if not isinstance(payload, dict):
        return 0
    count = 0
    for chat_id_raw, members in payload.items():
        try:
            chat_id = int(chat_id_raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(members, list):
            continue
        for item in members:
            if not isinstance(item, dict):
                continue
            try:
                uid = int(item["user_id"])
            except (KeyError, TypeError, ValueError):
                continue
            await conn.execute(
                "INSERT OR REPLACE INTO princesse_pool(chat_id, user_id, first_name, username) "
                "VALUES (?, ?, ?, ?)",
                (
                    chat_id,
                    uid,
                    str(item.get("first_name") or "Copain"),
                    str(item["username"]) if item.get("username") else None,
                ),
            )
            count += 1
    return count


async def _import_chats(conn, payload) -> int:
    if not isinstance(payload, dict):
        return 0
    count = 0
    for _key, value in payload.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(value["id"])
        except (KeyError, TypeError, ValueError):
            continue
        await conn.execute(
            "INSERT OR REPLACE INTO chats(id, type, title, username, last_seen_at) VALUES (?, ?, ?, ?, ?)",
            (
                chat_id,
                str(value.get("type") or "group"),
                value.get("title"),
                value.get("username"),
                value.get("last_seen_at"),
            ),
        )
        count += 1
    return count


_IMPORTERS = {
    "bibine_subscribers.json": _import_bibine_subscribers,
    "bibine_state.json": lambda c, p: _import_kv(c, p, "bibine_state"),
    "bibine_polls.json": _import_bibine_polls,
    "bibine_places.json": _import_bibine_places,
    "princesse_morning_targets.json": _import_princesse_targets,
    "princesse_morning_state.json": lambda c, p: _import_kv(c, p, "princesse_state"),
    "chats.json": _import_chats,
}


async def _already_imported(conn, filename: str) -> bool:
    async with conn.execute("SELECT 1 FROM json_imports WHERE filename=?", (filename,)) as cur:
        return await cur.fetchone() is not None


async def _record_import(conn, filename: str, sha: str, rows: int) -> None:
    await conn.execute(
        "INSERT OR REPLACE INTO json_imports(filename, imported_at, sha256, row_count) VALUES (?, ?, ?, ?)",
        (filename, datetime.now(tz=UTC).isoformat(), sha, rows),
    )


async def migrate_all(root: Path, *, force: bool = False, dry_run: bool = False) -> dict[str, int]:
    """Run all known imports. Returns a {filename: rows_imported} summary.

    `force` re-imports files even if already marked. `dry_run` parses files and reports
    row counts without writing to the DB or touching the JSONs on disk.
    """
    conn = await get_connection()
    data_dir = _data_dir(root)
    summary: dict[str, int] = {}

    ts = _timestamp()
    if not dry_run:
        _build_safety_tarball(root, ts)

    for filename in KNOWN_FILES:
        src = data_dir / filename
        if not src.is_file():
            logger.debug("JSON migration: %s missing, skipping.", filename)
            continue

        if not force and not dry_run and await _already_imported(conn, filename):
            logger.debug("JSON migration: %s already imported, skipping.", filename)
            continue

        try:
            payload = json.loads(src.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("JSON migration: could not parse %s: %s", filename, exc)
            continue

        importer = _IMPORTERS[filename]
        sha = _sha256(src)

        if dry_run:
            # Count without touching the DB by importing inside a savepoint we always roll back.
            await conn.execute("SAVEPOINT json_dry_run")
            try:
                rows = await importer(conn, payload)
                summary[filename] = rows
                logger.info("JSON migration DRY-RUN: %s -> %d rows", filename, rows)
            finally:
                await conn.execute("ROLLBACK TO SAVEPOINT json_dry_run")
                await conn.execute("RELEASE SAVEPOINT json_dry_run")
            continue

        try:
            await conn.execute("BEGIN")
            rows = await importer(conn, payload)
            await _record_import(conn, filename, sha, rows)
            await conn.commit()
        except Exception:
            await conn.rollback()
            logger.exception("JSON migration: import of %s failed, rolled back", filename)
            continue

        archive_path = _archive_json(root, ts, filename)
        logger.info(
            "JSON migration: %s migrated=%d archived_to=%s sha256=%s",
            filename,
            rows,
            archive_path,
            sha,
        )
        summary[filename] = rows

    return summary


async def run_auto_migration(project_root: Path) -> dict[str, int]:
    """Convenience entry point: ensure DB schema then import any JSON found."""
    await run_migrations()
    return await migrate_all(project_root, force=False, dry_run=False)


def _project_root_default() -> Path:
    return Path(__file__).resolve().parents[3]


async def _amain(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else _project_root_default()
    await run_migrations()
    summary = await migrate_all(root, force=args.force, dry_run=args.dry_run)
    for k, v in summary.items():
        print(f"{k}: {v} rows")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="JSON -> SQLite migrator")
    parser.add_argument("--root", help="Project root (defaults to repo root)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not write")
    parser.add_argument("--force", action="store_true", help="Re-import even if already done")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
