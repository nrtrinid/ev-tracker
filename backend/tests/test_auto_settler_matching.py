import importlib
from .test_utils import ensure_supabase_stub, reload_service_module


def _reload_odds_api():
    ensure_supabase_stub()
    mod = reload_service_module("odds_api")
    return importlib.reload(mod)


def test_select_completed_event_for_bet_exact_commence_and_team_match():
    mod = _reload_odds_api()
    bet = {
        "clv_team": "Los Angeles Lakers",
        "commence_time": "2026-03-18T02:00:00Z",
    }
    completed_events = [
        {
            "home_team": "Boston Celtics",
            "away_team": "Los Angeles Lakers",
            "commence_time": "2026-03-18T02:00:00Z",
            "completed": True,
        }
    ]

    event, reason = mod._select_completed_event_for_bet(bet, completed_events)
    assert reason == "matched"
    assert event is not None
    assert event["home_team"] == "Boston Celtics"


def test_select_completed_event_for_bet_ambiguous_match_skips():
    mod = _reload_odds_api()
    bet = {
        "clv_team": "Duke Blue Devils",
        "commence_time": "2026-03-18T19:00:00Z",
    }
    completed_events = [
        {
            "home_team": "Duke Blue Devils",
            "away_team": "UNC",
            "commence_time": "2026-03-18T19:00:00Z",
            "completed": True,
        },
        {
            "home_team": "Kansas",
            "away_team": "Duke Blue Devils",
            "commence_time": "2026-03-18T19:00:00Z",
            "completed": True,
        },
    ]

    event, reason = mod._select_completed_event_for_bet(bet, completed_events)
    assert event is None
    assert reason == "ambiguous_match"


def test_select_completed_event_for_bet_matches_iso_variant_timestamps():
    mod = _reload_odds_api()
    bet = {
        "clv_team": "Utah Jazz",
        "commence_time": "2026-03-20T01:11:00+00:00",
    }
    completed_events = [
        {
            "home_team": "Utah Jazz",
            "away_team": "Milwaukee Bucks",
            "commence_time": "2026-03-20T01:11:00Z",
            "completed": True,
        }
    ]

    event, reason = mod._select_completed_event_for_bet(bet, completed_events)
    assert reason == "matched"
    assert event is not None


def test_select_completed_event_for_bet_matches_small_seconds_drift():
    mod = _reload_odds_api()
    bet = {
        "clv_team": "High Point Panthers",
        "commence_time": "2026-03-19T17:50:00Z",
    }
    completed_events = [
        {
            "home_team": "Wisconsin Badgers",
            "away_team": "High Point Panthers",
            "commence_time": "2026-03-19T17:50:34Z",
            "completed": True,
        }
    ]

    event, reason = mod._select_completed_event_for_bet(bet, completed_events)
    assert reason == "matched"
    assert event is not None


def test_select_completed_event_for_bet_rejects_large_time_drift():
    mod = _reload_odds_api()
    bet = {
        "clv_team": "Utah Jazz",
        "commence_time": "2026-03-20T01:11:00Z",
    }
    completed_events = [
        {
            "home_team": "Utah Jazz",
            "away_team": "Milwaukee Bucks",
            "commence_time": "2026-03-20T01:15:00Z",
            "completed": True,
        }
    ]

    event, reason = mod._select_completed_event_for_bet(bet, completed_events)
    assert event is None
    assert reason == "no_match"


def test_grade_ml_uses_canonicalized_team_names():
    mod = _reload_odds_api()
    grade = mod._grade_ml(
        clv_team="St. John's",
        home_team="St Johns",
        away_team="UConn",
        scores=[
            {"name": "St Johns", "score": "80"},
            {"name": "UConn", "score": "72"},
        ],
    )
    assert grade == "win"


def test_select_completed_event_for_bet_prefers_event_id_match():
    mod = _reload_odds_api()
    bet = {
        "clv_event_id": "evt_123",
        "clv_team": "Any Team",
        "commence_time": "2026-03-20T01:00:00Z",
    }
    completed_events = [
        {
            "id": "evt_123",
            "home_team": "Utah Jazz",
            "away_team": "Milwaukee Bucks",
            "commence_time": "2026-03-20T05:00:00Z",
            "completed": True,
        }
    ]

    event, reason = mod._select_completed_event_for_bet(bet, completed_events)
    assert reason == "matched"
    assert event is not None
    assert event["id"] == "evt_123"


def test_select_completed_event_for_bet_falls_back_when_event_id_missing():
    mod = _reload_odds_api()
    bet = {
        "clv_event_id": "evt_not_found",
        "clv_team": "Los Angeles Lakers",
        "commence_time": "2026-03-18T02:00:00Z",
    }
    completed_events = [
        {
            "id": "evt_other",
            "home_team": "Boston Celtics",
            "away_team": "Los Angeles Lakers",
            "commence_time": "2026-03-18T02:00:00Z",
            "completed": True,
        }
    ]

    event, reason = mod._select_completed_event_for_bet(bet, completed_events)
    assert reason == "matched"
    assert event is not None
    assert event["id"] == "evt_other"
