from services.paper_autolog_utils import cohort_for_side, sport_display, autolog_key_for_side


def test_cohort_for_side_selects_low_and_high_edge_and_handles_invalid():
    base = {
        "sport": "basketball_nba",
        "ev_percentage": 1.0,
        "book_odds": 100,
        "commence_time": "2026-03-19T20:00:00Z",
        "team": "Lakers",
        "sportsbook": "DraftKings",
    }

    low = cohort_for_side(
        base,
        supported_sports={"basketball_nba"},
        low_edge_cohort="low",
        high_edge_cohort="high",
        low_edge_ev_min=0.5,
        low_edge_ev_max=1.5,
        low_edge_odds_min=-200,
        low_edge_odds_max=300,
        high_edge_ev_min=10.0,
        high_edge_odds_min=700,
    )
    assert low == "low"

    high = cohort_for_side(
        {**base, "ev_percentage": 10.0, "book_odds": 700},
        supported_sports={"basketball_nba"},
        low_edge_cohort="low",
        high_edge_cohort="high",
        low_edge_ev_min=0.5,
        low_edge_ev_max=1.5,
        low_edge_odds_min=-200,
        low_edge_odds_max=300,
        high_edge_ev_min=10.0,
        high_edge_odds_min=700,
    )
    assert high == "high"

    unsupported = cohort_for_side(
        {**base, "sport": "soccer_epl"},
        supported_sports={"basketball_nba"},
        low_edge_cohort="low",
        high_edge_cohort="high",
        low_edge_ev_min=0.5,
        low_edge_ev_max=1.5,
        low_edge_odds_min=-200,
        low_edge_odds_max=300,
        high_edge_ev_min=10.0,
        high_edge_odds_min=700,
    )
    assert unsupported is None

    invalid = cohort_for_side(
        {**base, "ev_percentage": None},
        supported_sports={"basketball_nba"},
        low_edge_cohort="low",
        high_edge_cohort="high",
        low_edge_ev_min=0.5,
        low_edge_ev_max=1.5,
        low_edge_odds_min=-200,
        low_edge_odds_max=300,
        high_edge_ev_min=10.0,
        high_edge_odds_min=700,
    )
    assert invalid is None


def test_sport_display_and_autolog_key_for_side():
    assert sport_display("basketball_nba") == "NBA"
    assert sport_display("other") == "other"

    key = autolog_key_for_side(
        {
            "sport": "Basketball_NBA",
            "commence_time": "2026-03-19T20:00:00Z",
            "team": "Lakers",
            "sportsbook": "DraftKings",
        },
        "high_edge",
    )
    assert key == "v1|high_edge|basketball_nba|2026-03-19T20:00:00Z|lakers|draftkings|ml"
