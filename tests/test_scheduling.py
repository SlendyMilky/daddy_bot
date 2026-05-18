"""Tests for pure scheduling helpers (no IO)."""
from __future__ import annotations

import random
from datetime import datetime, time
from zoneinfo import ZoneInfo

from daddy_bot.modules.bibine import _random_window_datetime, _target_friday_date
from daddy_bot.modules.princesse_morning import _morning_window_for_date

TZ = ZoneInfo("Europe/Paris")


def test_target_friday_date_from_monday():
    monday = datetime(2026, 5, 11, 10, 0, tzinfo=TZ)  # Mon
    assert _target_friday_date(monday).isoformat() == "2026-05-15"


def test_target_friday_date_from_friday():
    friday = datetime(2026, 5, 15, 8, 0, tzinfo=TZ)
    # Same week's Friday returned.
    assert _target_friday_date(friday).isoformat() == "2026-05-15"


def test_target_friday_date_from_saturday_rolls_to_next_friday():
    saturday = datetime(2026, 5, 16, 8, 0, tzinfo=TZ)
    # Should roll to *next* Friday, not the same week (since the bibine has already passed).
    result = _target_friday_date(saturday).isoformat()
    assert result == "2026-05-22"


def test_random_window_datetime_in_allowed_ranges():
    rng = random.Random(42)
    saved = random.random
    try:
        random.random = rng.random  # type: ignore[assignment]
        random.randint = rng.randint  # type: ignore[assignment]
        friday = datetime(2026, 5, 15, tzinfo=TZ).date()
        for _ in range(50):
            dt = _random_window_datetime(friday, TZ)
            # Must land Thu 15:00-22:00 or Fri 09:00-17:00
            if dt.weekday() == 3:  # Thursday
                assert time(15, 0) <= dt.timetz().replace(tzinfo=None) < time(22, 0)
            else:
                assert dt.weekday() == 4
                assert time(9, 0) <= dt.timetz().replace(tzinfo=None) < time(17, 0)
    finally:
        random.random = saved  # type: ignore[assignment]


def test_morning_window_for_date():
    d = datetime(2026, 5, 12, tzinfo=TZ).date()
    win_start, win_end = _morning_window_for_date(d, TZ, 6, 10)
    assert win_start.hour == 6
    assert win_end.hour == 10
    assert win_end - win_start == (win_end - win_start)
    assert win_start.tzinfo == TZ
