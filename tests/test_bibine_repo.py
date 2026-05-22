"""Tests for bibine_repo: subscribers, state KV, polls, place state."""

from __future__ import annotations

import pytest

from daddy_bot.db.repositories import bibine_repo
from daddy_bot.db.repositories.bibine_repo import BibineSubscriber


@pytest.mark.asyncio
async def test_subscribers_roundtrip(temp_db):
    assert await bibine_repo.list_subscribers() == []
    sub = BibineSubscriber(user_id=42, first_name="Alice", username="alice")
    await bibine_repo.add_subscriber(sub)
    assert await bibine_repo.has_subscriber(42) is True
    assert await bibine_repo.has_subscriber(99) is False

    out = await bibine_repo.list_subscribers()
    assert len(out) == 1
    assert out[0].user_id == 42
    assert out[0].mention_html == '<a href="tg://user?id=42">@alice</a>'

    # Updating same user_id should replace, not duplicate.
    await bibine_repo.add_subscriber(BibineSubscriber(user_id=42, first_name="Alice2", username=None))
    out = await bibine_repo.list_subscribers()
    assert len(out) == 1
    assert out[0].first_name == "Alice2"
    assert out[0].username is None

    assert await bibine_repo.remove_subscriber(42) is True
    assert await bibine_repo.remove_subscriber(42) is False
    assert await bibine_repo.list_subscribers() == []


@pytest.mark.asyncio
async def test_state_kv(temp_db):
    assert await bibine_repo.get_state("scheduled_week") is None
    await bibine_repo.set_state("scheduled_week", "2026-W20")
    await bibine_repo.set_state("scheduled_at", "2026-05-15T11:00:00+02:00")
    assert await bibine_repo.get_state("scheduled_week") == "2026-W20"
    snap = await bibine_repo.all_state()
    assert snap == {
        "scheduled_week": "2026-W20",
        "scheduled_at": "2026-05-15T11:00:00+02:00",
    }
    await bibine_repo.delete_state("scheduled_week")
    assert await bibine_repo.get_state("scheduled_week") is None


@pytest.mark.asyncio
async def test_poll_json_payload(temp_db):
    payload = {
        "mentions_html": "<a>x</a>",
        "yes_votes": [{"user_id": 1, "label": "@a"}],
        "no_votes": [],
    }
    await bibine_repo.save_poll(-100123, 7, "ping", payload)
    out = await bibine_repo.get_poll(-100123, 7)
    assert out is not None
    assert out["yes_votes"] == [{"user_id": 1, "label": "@a"}]
    assert out["type"] == "ping"

    polls = await bibine_repo.list_active_polls()
    assert len(polls) == 1
    assert polls[0]["chat_id"] == -100123


@pytest.mark.asyncio
async def test_save_poll_keeps_newest_when_created_at_ties(temp_db):
    """Retention must not drop the latest message when created_at has second precision."""
    cid = -1001153426467
    for mid in (10, 20, 30):
        await bibine_repo.save_poll(cid, mid, "ping", {"mentions_html": "x", "yes_votes": [], "no_votes": []})
    await bibine_repo.save_poll(cid, 40, "ping", {"mentions_html": "y", "yes_votes": [], "no_votes": []})
    assert await bibine_repo.get_poll(cid, 40) is not None


@pytest.mark.asyncio
async def test_place_state(temp_db):
    proposals = [{"name": "Bar A", "lat": 1.0, "lon": 2.0}]
    await bibine_repo.save_place_state(-1, "2026-05-22", 555, proposals)
    state = await bibine_repo.get_place_state(-1, "2026-05-22")
    assert state is not None
    assert state["poll_message_id"] == 555
    assert state["proposals"] == proposals

    # Overwrite with empty proposals + null poll
    await bibine_repo.save_place_state(-1, "2026-05-22", None, [])
    state2 = await bibine_repo.get_place_state(-1, "2026-05-22")
    assert state2 is not None
    assert state2["poll_message_id"] is None
    assert state2["proposals"] == []
