"""Tests for JSON -> SQLite migration: roundtrip, archiving, idempotence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daddy_bot.db.json_migration import KNOWN_FILES, migrate_all
from daddy_bot.db.repositories import bibine_repo, chats_repo, princesse_repo


def _seed(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "bibine_subscribers.json").write_text(
        json.dumps([
            {"user_id": 10, "first_name": "Alice", "username": "alice"},
            {"user_id": 11, "first_name": "Bob", "username": None},
        ]),
        encoding="utf-8",
    )
    (data_dir / "bibine_state.json").write_text(
        json.dumps({"scheduled_week": "2026-05-15", "last_sent_week": "2026-05-08"}),
        encoding="utf-8",
    )
    (data_dir / "bibine_polls.json").write_text(
        json.dumps({
            "-100:42": {"mentions_html": "x", "yes_votes": [], "no_votes": []},
            "-100:43": {"type": "place", "week_iso": "2026-05-22", "proposals": [{"name": "Bar"}], "votes": []},
        }),
        encoding="utf-8",
    )
    (data_dir / "bibine_places.json").write_text(
        json.dumps({
            "-100:2026-05-22": {
                "chat_id": -100,
                "week_iso": "2026-05-22",
                "poll_message_id": 43,
                "proposals": [{"name": "Bar"}],
            }
        }),
        encoding="utf-8",
    )
    (data_dir / "princesse_morning_targets.json").write_text(
        json.dumps({
            "-1001": [
                {"user_id": 50, "first_name": "P1", "username": "p1"},
                {"user_id": 51, "first_name": "P2", "username": None},
            ]
        }),
        encoding="utf-8",
    )
    (data_dir / "princesse_morning_state.json").write_text(
        json.dumps({"last_sent_date": "2026-05-12"}),
        encoding="utf-8",
    )
    (data_dir / "chats.json").write_text(
        json.dumps({
            "-100": {"id": -100, "type": "supergroup", "title": "G1", "username": None,
                     "last_seen_at": "2026-05-12T10:00:00"},
        }),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_full_migration_and_idempotence(temp_db, tmp_path):
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    _seed(root / "data")

    summary = await migrate_all(root, force=False, dry_run=False)
    assert summary["bibine_subscribers.json"] == 2
    assert summary["bibine_state.json"] == 2
    assert summary["bibine_polls.json"] == 2
    assert summary["bibine_places.json"] == 1
    assert summary["princesse_morning_targets.json"] == 2
    assert summary["princesse_morning_state.json"] == 1
    assert summary["chats.json"] == 1

    # Source JSON files moved to data/archive/<ts>/.
    for name in KNOWN_FILES:
        assert not (root / "data" / name).exists(), f"{name} should be moved to archive"
    archives = list((root / "data" / "archive").rglob("*.json"))
    assert {p.name for p in archives} == set(KNOWN_FILES)

    # tar.gz safety net exists.
    tarballs = list((root / "data" / "archive").glob("_pre_migration_backup_*.tar.gz"))
    assert len(tarballs) == 1

    # Data lands in the right tables.
    subs = await bibine_repo.list_subscribers()
    assert {s.user_id for s in subs} == {10, 11}
    assert await bibine_repo.get_state("scheduled_week") == "2026-05-15"

    poll = await bibine_repo.get_poll(-100, 42)
    assert poll is not None and poll["mentions_html"] == "x"
    place_state = await bibine_repo.get_place_state(-100, "2026-05-22")
    assert place_state and place_state["poll_message_id"] == 43

    pools = await princesse_repo.list_pools_for_chats((-1001,))
    assert {m.user_id for m in pools[-1001]} == {50, 51}
    assert await princesse_repo.get_state("last_sent_date") == "2026-05-12"

    chats = await chats_repo.list_chats()
    assert [c.id for c in chats] == [-100]

    # Second run = no-op. Re-create empty data dir to ensure idempotence.
    summary2 = await migrate_all(root, force=False, dry_run=False)
    assert summary2 == {}


@pytest.mark.asyncio
async def test_dry_run_does_not_touch_disk_or_db(temp_db, tmp_path):
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    _seed(root / "data")

    summary = await migrate_all(root, force=False, dry_run=True)
    assert summary["bibine_subscribers.json"] == 2

    # JSON files still on disk
    assert (root / "data" / "bibine_subscribers.json").exists()
    # DB unchanged
    assert await bibine_repo.list_subscribers() == []
