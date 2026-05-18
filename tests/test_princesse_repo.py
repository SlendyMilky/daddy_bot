"""Tests for princesse_repo: pool upsert/remove, state KV, history."""

from __future__ import annotations

import pytest

from daddy_bot.db.repositories import princesse_repo
from daddy_bot.db.repositories.princesse_repo import PoolMember


@pytest.mark.asyncio
async def test_pool_upsert_and_remove(temp_db):
    chat = -100
    member = PoolMember(user_id=1, first_name="A", username="alpha")
    changed = await princesse_repo.upsert_member(chat, member)
    assert changed is True

    # Same data -> no change reported.
    changed = await princesse_repo.upsert_member(chat, member)
    assert changed is False

    # Profile change -> change reported.
    changed = await princesse_repo.upsert_member(
        chat, PoolMember(user_id=1, first_name="A2", username="alpha")
    )
    assert changed is True

    pool = await princesse_repo.list_pool(chat)
    assert len(pool) == 1
    assert pool[0].first_name == "A2"

    assert await princesse_repo.remove_member(chat, 1) is True
    assert await princesse_repo.remove_member(chat, 1) is False


@pytest.mark.asyncio
async def test_pool_multi_chat_listing(temp_db):
    await princesse_repo.upsert_member(-1, PoolMember(user_id=1, first_name="A", username=None))
    await princesse_repo.upsert_member(-1, PoolMember(user_id=2, first_name="B", username=None))
    await princesse_repo.upsert_member(-2, PoolMember(user_id=3, first_name="C", username=None))

    out = await princesse_repo.list_pools_for_chats((-1, -2, -999))
    assert {m.user_id for m in out[-1]} == {1, 2}
    assert [m.user_id for m in out[-2]] == [3]
    assert out[-999] == []


@pytest.mark.asyncio
async def test_state_and_history(temp_db):
    await princesse_repo.set_state("last_sent_date", "2026-05-12")
    assert await princesse_repo.get_state("last_sent_date") == "2026-05-12"

    await princesse_repo.record_send(chat_id=-1, user_id=7, voice_file="hello.ogg")
    await princesse_repo.record_send(chat_id=-1, user_id=8, voice_file="world.ogg")

    hist = await princesse_repo.list_history(limit=10)
    assert len(hist) == 2
    assert hist[0]["voice_file"] == "world.ogg"  # latest first
    assert hist[1]["voice_file"] == "hello.ogg"
