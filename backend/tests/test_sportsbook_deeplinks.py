from services.sportsbook_deeplinks import normalize_sportsbook_link, resolve_sportsbook_deeplink


def test_normalize_sportsbook_link_accepts_http_and_https():
    assert normalize_sportsbook_link("https://sportsbook.example/path") == "https://sportsbook.example/path"
    assert normalize_sportsbook_link("http://sportsbook.example/path") == "http://sportsbook.example/path"


def test_normalize_sportsbook_link_preserves_real_betmgm_state_host():
    assert (
        normalize_sportsbook_link("https://sports.nj.betmgm.com/en/sports/events/evt-123")
        == "https://sports.nj.betmgm.com/en/sports/events/evt-123"
    )


def test_normalize_sportsbook_link_leaves_non_betmgm_urls_unchanged():
    assert normalize_sportsbook_link("https://sportsbook.example/path?tab=props#today") == (
        "https://sportsbook.example/path?tab=props#today"
    )


def test_normalize_sportsbook_link_rejects_non_http_and_template_placeholders():
    assert normalize_sportsbook_link("javascript:alert(1)") is None
    assert normalize_sportsbook_link("https://sports.{state}.betmgm.com/en/sports/events/evt-123") is None
    assert normalize_sportsbook_link("https://sports.{state}.betmgm.com:8443/en/sports/events/evt-123") is None
    assert normalize_sportsbook_link("https://sports.{region}.betmgm.com/en/sports") is None


def test_normalize_sportsbook_link_rejects_partial_betmgm_template_embeddings():
    assert normalize_sportsbook_link("https://sports.{state}.betmgm.com.evil.com/en/sports") is None
    assert normalize_sportsbook_link("https://example.com/path/sports.{state}.betmgm.com/en/sports") is None


def test_resolve_sportsbook_deeplink_prefers_most_specific_provider_link():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="DraftKings",
        selection_link="https://sportsbook.example/selection",
        market_link="https://sportsbook.example/market",
        event_link="https://sportsbook.example/event",
    )

    assert url == "https://sportsbook.example/selection"
    assert level == "selection"


def test_resolve_sportsbook_deeplink_preserves_real_betmgm_selection_link():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="https://sports.nj.betmgm.com/en/sports/events/selection-123",
        market_link="https://sports.pa.betmgm.com/en/sports/events/market-123",
        event_link="https://sports.co.betmgm.com/en/sports/events/event-123",
    )

    assert url == "https://sports.nj.betmgm.com/en/sports/events/selection-123"
    assert level == "selection"


def test_resolve_sportsbook_deeplink_preserves_real_betmgm_market_link():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="https://sports.{state}.betmgm.com/en/sports/events/placeholder",
        market_link="https://sports.nj.betmgm.com/en/sports/events/market-123",
        event_link="https://sports.pa.betmgm.com/en/sports/events/event-123",
    )

    assert url == "https://sports.nj.betmgm.com/en/sports/events/market-123"
    assert level == "market"


def test_resolve_sportsbook_deeplink_preserves_real_betmgm_event_link():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="javascript:alert(1)",
        market_link="https://sports.{state}.betmgm.com/en/sports/events/placeholder",
        event_link="https://sports.nj.betmgm.com/en/sports/events/event-123",
    )

    assert url == "https://sports.nj.betmgm.com/en/sports/events/event-123"
    assert level == "event"


def test_resolve_sportsbook_deeplink_falls_back_to_homepage_when_provider_links_invalid():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="https://sports.{state}.betmgm.com/en/sports/events/placeholder",
        market_link="javascript:alert(1)",
        event_link="not-a-url",
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
