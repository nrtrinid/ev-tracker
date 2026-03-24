from types import SimpleNamespace

import pytest

from services.parlay_slips import (
    build_parlay_logged_bet_payload,
    build_parlay_slip_insert_payload,
    build_parlay_slip_update_payload,
)


BASE_LEG = {
    "id": "straight:evt-1:lakers:draftkings",
    "surface": "straight_bets",
    "eventId": "evt-1",
    "marketKey": "h2h",
    "selectionKey": "evt-1:lakers",
    "sportsbook": "DraftKings",
    "oddsAmerican": 130,
    "referenceOddsAmerican": 108,
    "referenceSource": "pinnacle",
    "display": "Lakers ML",
    "event": "Lakers @ Warriors",
    "sport": "basketball_nba",
    "commenceTime": "2026-03-24T01:00:00Z",
    "correlationTags": ["evt-1", "lakers"],
    "team": "Lakers",
    "participantName": None,
    "participantId": None,
    "selectionSide": "Lakers",
    "lineValue": None,
    "marketDisplay": "Moneyline",
    "sourceEventId": "evt-1",
    "sourceMarketKey": "h2h",
    "sourceSelectionKey": "evt-1:lakers",
    "selectionMeta": None,
}


def test_build_parlay_slip_insert_payload_captures_json_snapshots():
    slip = SimpleNamespace(
        model_dump=lambda exclude_unset=False: {
            "sportsbook": "DraftKings",
            "stake": 10.0,
            "legs": [BASE_LEG],
            "warnings": [],
            "pricingPreview": {
                "legCount": 1,
                "sportsbook": "DraftKings",
                "combinedDecimalOdds": 2.3,
                "combinedAmericanOdds": 130,
                "stake": 10.0,
                "totalPayout": 23.0,
                "profit": 13.0,
                "estimatedFairDecimalOdds": 2.08,
                "estimatedFairAmericanOdds": 108,
                "estimatedTrueProbability": 0.48,
                "estimatedEvPercent": 10.4,
                "estimateAvailable": True,
                "estimateUnavailableReason": None,
                "hasBlockingCorrelation": False,
            },
        }
    )

    payload = build_parlay_slip_insert_payload(
        user_id="user-1",
        slip=slip,
        utc_now_iso=lambda: "2026-03-23T00:00:00Z",
    )

    assert payload["user_id"] == "user-1"
    assert payload["sportsbook"] == "DraftKings"
    assert payload["stake"] == 10.0
    assert payload["legs_json"] == [BASE_LEG]
    assert payload["warnings_json"] == []
    assert payload["pricing_preview_json"]["estimateAvailable"] is True


def test_build_parlay_slip_update_payload_uses_current_legs_for_book_validation():
    slip_update = SimpleNamespace(
        model_dump=lambda exclude_unset=True: {
            "sportsbook": "DraftKings",
            "stake": 15.0,
        }
    )

    payload = build_parlay_slip_update_payload(
        slip_update=slip_update,
        sportsbook="DraftKings",
        current_legs=[BASE_LEG],
        utc_now_iso=lambda: "2026-03-23T01:00:00Z",
    )

    assert payload == {
        "updated_at": "2026-03-23T01:00:00Z",
        "sportsbook": "DraftKings",
        "stake": 15.0,
    }


def test_build_parlay_slip_update_payload_rejects_mixed_books():
    slip_update = SimpleNamespace(
        model_dump=lambda exclude_unset=True: {
            "sportsbook": "FanDuel",
            "legs": [BASE_LEG],
        }
    )

    with pytest.raises(ValueError, match="same sportsbook"):
        build_parlay_slip_update_payload(
            slip_update=slip_update,
            sportsbook="DraftKings",
            current_legs=[BASE_LEG],
            utc_now_iso=lambda: "2026-03-23T01:00:00Z",
        )


def test_build_parlay_logged_bet_payload_uses_pricing_snapshot_for_true_prob():
    log_request = SimpleNamespace(
        sport=None,
        event=None,
        promo_type=SimpleNamespace(value="standard"),
        odds_american=425,
        stake=20.0,
        boost_percent=None,
        winnings_cap=None,
        notes="draft log",
        event_date=None,
        opposing_odds=None,
        payout_override=None,
    )
    slip_row = {
        "id": "slip-1",
        "sportsbook": "DraftKings",
        "legs_json": [BASE_LEG],
        "warnings_json": [],
        "pricing_preview_json": {
            "legCount": 1,
            "sportsbook": "DraftKings",
            "combinedDecimalOdds": 5.25,
            "combinedAmericanOdds": 425,
            "stake": 20.0,
            "totalPayout": 105.0,
            "profit": 85.0,
            "estimatedFairDecimalOdds": 4.5,
            "estimatedFairAmericanOdds": 350,
            "estimatedTrueProbability": 0.2222,
            "estimatedEvPercent": 16.7,
            "estimateAvailable": True,
            "estimateUnavailableReason": None,
            "hasBlockingCorrelation": False,
        },
    }

    payload = build_parlay_logged_bet_payload(
        slip_row=slip_row,
        log_request=log_request,
        utc_now_iso=lambda: "2026-03-23T02:00:00Z",
    )

    assert payload["surface"] == "parlay"
    assert payload["market"] == "Parlay"
    assert payload["sportsbook"] == "DraftKings"
    assert payload["true_prob_at_entry"] == pytest.approx(0.2222)
    assert payload["event"] == "1-leg Lakers @ Warriors parlay"
    assert payload["event_date"] == "2026-03-24"
    assert payload["selection_meta"]["slip_id"] == "slip-1"
    assert payload["selection_meta"]["pricingPreview"]["estimatedEvPercent"] == 16.7
