import pytest
from services.bet_crud import build_bet_response


def test_payout_override_recomputes_entry_ev_for_standard(monkeypatch):
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

    bet = build_bet_response(row, k_factor=0.78)

    # With true_prob=0.5 and effective decimal=2.5:
    # EV per $ = 0.5*2.5 - 1 = 0.25
    assert bet.ev_per_dollar == pytest.approx(0.25, abs=1e-6)
    assert bet.ev_total == pytest.approx(25.0, abs=0.01)
    assert bet.win_payout == pytest.approx(250.0, abs=0.01)
