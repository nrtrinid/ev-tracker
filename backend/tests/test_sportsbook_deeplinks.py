from services.sportsbook_deeplinks import (
    _normalize_sportsbook_link_with_reason,
    debug_resolve_sportsbook_deeplink,
    normalize_sportsbook_link,
    resolve_sportsbook_deeplink,
)


def test_normalize_sportsbook_link_accepts_http_and_https():
    assert normalize_sportsbook_link("https://sportsbook.example/path") == "https://sportsbook.example/path"
    assert normalize_sportsbook_link("http://sportsbook.example/path") == "http://sportsbook.example/path"


def test_normalize_sportsbook_link_preserves_real_betmgm_state_host():
    assert (
        normalize_sportsbook_link("https://sports.nj.betmgm.com/en/sports/events/evt-123")
        == "https://sports.nj.betmgm.com/en/sports/events/evt-123"
    )


def test_normalize_sportsbook_link_canonicalizes_exact_betmgm_template_host():
    assert (
        normalize_sportsbook_link("https://sports.{state}.betmgm.com/en/sports/events/evt-123?tab=props#today")
        == "https://sports.betmgm.com/en/sports/events/evt-123?tab=props#today"
    )


def test_normalize_sportsbook_link_canonicalizes_exact_betmgm_template_host_with_port():
    assert (
        normalize_sportsbook_link("https://sports.{state}.betmgm.com:8443/en/sports/events/evt-123")
        == "https://sports.betmgm.com:8443/en/sports/events/evt-123"
    )


def test_normalize_sportsbook_link_leaves_non_betmgm_urls_unchanged():
    assert normalize_sportsbook_link("https://sportsbook.example/path?tab=props#today") == (
        "https://sportsbook.example/path?tab=props#today"
    )


def test_normalize_sportsbook_link_rejects_non_http_and_unknown_template_placeholders():
    assert normalize_sportsbook_link("javascript:alert(1)") is None
    assert normalize_sportsbook_link("https://sportsbook.{state}.example.com/path") is None
    assert normalize_sportsbook_link("https://sports.{region}.betmgm.com/en/sports") is None


def test_normalize_sportsbook_link_rejects_partial_betmgm_template_embeddings():
    assert normalize_sportsbook_link("https://sports.{state}.betmgm.com.evil.com/en/sports") is None
    assert normalize_sportsbook_link("https://example.com/path/sports.{state}.betmgm.com/en/sports") is None


def test_normalize_sportsbook_link_debug_reasons_cover_common_failures():
    assert _normalize_sportsbook_link_with_reason(None) == (None, "missing_input")
    assert _normalize_sportsbook_link_with_reason("   ") == (None, "blank_input")
    assert _normalize_sportsbook_link_with_reason("javascript:alert(1)") == (None, "invalid_scheme")
    assert _normalize_sportsbook_link_with_reason("https://sports.{region}.betmgm.com/en/sports") == (
        None,
        "unresolved_template",
    )


def test_normalize_sportsbook_link_debug_reason_marks_canonicalized_betmgm_template_as_ok():
    assert _normalize_sportsbook_link_with_reason("https://sports.{state}.betmgm.com/en/sports/events/evt-123") == (
        "https://sports.betmgm.com/en/sports/events/evt-123",
        "ok",
    )


def test_resolve_sportsbook_deeplink_prefers_most_specific_provider_link():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="DraftKings",
        selection_link="https://sportsbook.example/selection",
        market_link="https://sportsbook.example/market",
        event_link="https://sportsbook.example/event",
    )

    assert url == "https://sportsbook.example/selection"
    assert level == "selection"


def test_resolve_sportsbook_deeplink_uses_betmgm_template_selection_link_as_selection():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="https://sports.{state}.betmgm.com/en/sports/events/selection-123?foo=bar",
        market_link="https://sports.pa.betmgm.com/en/sports/events/market-123",
        event_link="https://sports.co.betmgm.com/en/sports/events/event-123",
    )

    assert url == "https://sports.betmgm.com/en/sports/events/selection-123?foo=bar"
    assert level == "selection"


def test_resolve_sportsbook_deeplink_uses_betmgm_template_market_link_as_market():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="javascript:alert(1)",
        market_link="https://sports.{state}.betmgm.com/en/sports/events/market-123",
        event_link="https://sports.pa.betmgm.com/en/sports/events/event-123",
    )

    assert url == "https://sports.betmgm.com/en/sports/events/market-123"
    assert level == "market"


def test_resolve_sportsbook_deeplink_uses_betmgm_template_event_link_as_event():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="javascript:alert(1)",
        market_link="https://sports.{region}.betmgm.com/en/sports/events/placeholder",
        event_link="https://sports.{state}.betmgm.com/en/sports/events/event-123",
    )

    assert url == "https://sports.betmgm.com/en/sports/events/event-123"
    assert level == "event"


def test_resolve_sportsbook_deeplink_falls_back_to_homepage_when_provider_links_invalid():
    url, level = resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="https://sports.{region}.betmgm.com/en/sports/events/placeholder",
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


def test_debug_resolve_sportsbook_deeplink_exposes_attempt_reasons_for_homepage_fallback():
    trace = debug_resolve_sportsbook_deeplink(
        sportsbook="BetMGM",
        selection_link="https://sports.{region}.betmgm.com/en/sports/events/placeholder",
        market_link="javascript:alert(1)",
        event_link="not-a-url",
    )

    assert trace["selected_level"] == "homepage"
    assert trace["selected_url"] == "https://sports.betmgm.com/"
    assert trace["attempts"] == [
        {
            "level": "selection",
            "input": "https://sports.{region}.betmgm.com/en/sports/events/placeholder",
            "normalized": None,
            "reason": "unresolved_template",
        },
        {
            "level": "market",
            "input": "javascript:alert(1)",
            "normalized": None,
            "reason": "invalid_scheme",
        },
        {
            "level": "event",
            "input": "not-a-url",
            "normalized": None,
            "reason": "invalid_scheme",
        },
        {
            "level": "homepage",
            "input": "https://sports.betmgm.com/",
            "normalized": "https://sports.betmgm.com/",
            "reason": "ok",
        },
    ]
