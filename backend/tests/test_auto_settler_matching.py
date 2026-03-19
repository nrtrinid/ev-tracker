import importlib
import sys
import types


def _reload_odds_api():
    if "supabase" not in sys.modules:
        supabase_stub = types.ModuleType("supabase")
        setattr(supabase_stub, "create_client", lambda *args, **kwargs: None)
        setattr(supabase_stub, "Client", object)
        sys.modules["supabase"] = supabase_stub
    import services.odds_api as mod
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
