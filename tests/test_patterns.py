from daddy_bot.utils.patterns import (
    BRICOLEUR_RE,
    ERIKA_RE,
    INSTAGRAM_RE,
    PEUR_RE,
    QUOI_RE,
    SHALOM_RE,
    TIKTOK_RE,
    TWITTER_RE,
    WOMEN_RE,
)


def test_quoi_pattern_matches_expected_inputs():
    assert QUOI_RE.search("quoi")
    assert QUOI_RE.search("QUOI?")
    assert not QUOI_RE.search("quoique")


def test_basic_trigger_patterns():
    assert SHALOM_RE.search("ShAlOm")
    assert PEUR_RE.search("peur.")
    assert ERIKA_RE.search("Erika")
    assert not ERIKA_RE.search("ERIKA")
    assert WOMEN_RE.search("women")
    assert BRICOLEUR_RE.search("Le bricoleur!")


def test_social_url_patterns():
    assert TWITTER_RE.search("https://x.com/user/status/123")
    assert TWITTER_RE.search("https://twitter.com/user/status/456")
    assert TIKTOK_RE.search("https://www.tiktok.com/@user/video/123")
    assert INSTAGRAM_RE.search("https://instagram.com/example/")
