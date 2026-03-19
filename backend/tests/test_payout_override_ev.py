import importlib
import os
import sys
import types

import pytest


def _import_main_with_supabase_stub():
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "unit-test-key")

    # Allow importing main.py even if supabase isn't installed in the active interpreter.
    if "supabase" not in sys.modules:
        sys.modules["supabase"] = types.SimpleNamespace(
            create_client=lambda *args, **kwargs: None,
            Client=object,
        )
    if "main" in sys.modules:
        return importlib.reload(sys.modules["main"])
    return importlib.import_module("main")


def test_payout_override_recomputes_entry_ev_for_standard():
    main = _import_main_with_supabase_stub()

    row = {
        "id": "bet1",
        "created_at": "2026-03-17T00:00:00Z",
        "event_date": "2026-03-17",
        "settled_at": None,
        "sport": "NBA",
        "event": "A @ B",
        "market": "ML",
        "sportsbook": "FanDuel",
        "promo_type": "standard",
        "odds_american": -110,
        "stake": 100.0,
        "boost_percent": None,
        "winnings_cap": None,
        "notes": None,
        "opposing_odds": None,
        "result": "pending",
        "payout_override": 250.0,  # implies decimal 2.50
        "pinnacle_odds_at_entry": None,
        "pinnacle_odds_at_close": None,
        "clv_updated_at": None,
        "commence_time": None,
        "clv_team": None,
        "clv_sport_key": None,
        "true_prob_at_entry": 0.50,
    }

    bet = main.build_bet_response(row, k_factor=0.78)

    # With true_prob=0.5 and effective decimal=2.5:
    # EV per $ = 0.5*2.5 - 1 = 0.25
    assert bet.ev_per_dollar == pytest.approx(0.25, abs=1e-6)
    assert bet.ev_total == pytest.approx(25.0, abs=0.01)
    assert bet.win_payout == pytest.approx(250.0, abs=0.01)

