from unittest.mock import patch

from daddy_bot.core.rate_limit import SlidingWindowRateLimiter


def test_under_limit_returns_false():
    limiter = SlidingWindowRateLimiter(max_events=3, window_seconds=10)

    with patch("daddy_bot.core.rate_limit.time.monotonic", side_effect=[100.0, 101.0]):
        assert limiter.is_limited(42) is False
        assert limiter.is_limited(42) is False


def test_at_limit_returns_true():
    limiter = SlidingWindowRateLimiter(max_events=2, window_seconds=10)

    with patch("daddy_bot.core.rate_limit.time.monotonic", side_effect=[100.0, 101.0, 102.0]):
        assert limiter.is_limited(42) is False
        assert limiter.is_limited(42) is False
        assert limiter.is_limited(42) is True


def test_window_expiry_allows_events_again():
    limiter = SlidingWindowRateLimiter(max_events=2, window_seconds=10)

    with patch("daddy_bot.core.rate_limit.time.monotonic", side_effect=[100.0, 101.0, 102.0, 111.0]):
        assert limiter.is_limited(42) is False
        assert limiter.is_limited(42) is False
        assert limiter.is_limited(42) is True
        assert limiter.is_limited(42) is False
