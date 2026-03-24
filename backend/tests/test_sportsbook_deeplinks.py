from services.sportsbook_deeplinks import normalize_sportsbook_link, resolve_sportsbook_deeplink


def test_normalize_sportsbook_link_accepts_http_and_https():
    assert normalize_sportsbook_link("https://sportsbook.example/path") == "https://sportsbook.example/path"
    assert normalize_sportsbook_link("http://sportsbook.example/path") == "http://sportsbook.example/path"


def test_normalize_sportsbook_link_rejects_non_http_and_unresolved_templates():
    assert normalize_sportsbook_link("javascript:alert(1)") is None
    assert normalize_sportsbook_link("https://sports.{state}.betmgm.com/en/sports") is None


def test_resolve_sportsbook_deeplink_prefers_most_specific_provider_link():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="DraftKings",
        selection_link="https://sportsbook.example/selection",
        market_link="https://sportsbook.example/market",
        event_link="https://sportsbook.example/event",
    )

    assert url == "https://sportsbook.example/selection"
    assert level == "selection"


def test_resolve_sportsbook_deeplink_falls_back_to_homepage_when_provider_links_unusable():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="https://sports.{state}.betmgm.com/en/sports?options=bad",
        market_link=None,
        event_link="https://sports.{state}.betmgm.com/en/sports/events/bad",
    )

    assert url == "https://sports.betmgm.com/"
    assert level == "homepage"


def test_resolve_sportsbook_deeplink_returns_none_without_provider_or_homepage_link():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="Unknown Book",
        selection_link=None,
        market_link=None,
        event_link=None,
    )

    assert url is None
    assert level is None
