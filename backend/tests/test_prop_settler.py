"""Unit tests for prop auto-settle helpers (ESPN / Odds cross-check)."""

from datetime import datetime, timezone

from services.espn_scoreboard import build_auto_settle_scoreboard_dates
from services.prop_settler import (
    _espn_home_away_matches_odds,
    _espn_resolve_cache_key,
    _scores_align_odds_espn,
    _stat_label_to_key,
    build_player_stat_map,
    grade_prop,
)


def test_scores_align_odds_espn_accepts_matching_finals():
    odds_event = {
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "scores": [
            {"name": "Los Angeles Lakers", "score": "112"},
            {"name": "Boston Celtics", "score": "105"},
        ],
    }
    espn_event = {
        "competitions": [
            {
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {"displayName": "Los Angeles Lakers"},
                        "score": "112",
                    },
                    {
                        "homeAway": "away",
                        "team": {"displayName": "Boston Celtics"},
                        "score": "105",
                    },
                ]
            }
        ]
    }
    assert _scores_align_odds_espn(odds_event, espn_event)


def test_scores_align_odds_espn_rejects_wrong_final():
    odds_event = {
        "scores": [
            {"name": "Los Angeles Lakers", "score": "112"},
            {"name": "Boston Celtics", "score": "105"},
        ],
    }
    espn_event = {
        "competitions": [
            {
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {"displayName": "Los Angeles Lakers"},
                        "score": "99",
                    },
                    {
                        "homeAway": "away",
                        "team": {"displayName": "Boston Celtics"},
                        "score": "105",
                    },
                ]
            }
        ]
    }
    assert not _scores_align_odds_espn(odds_event, espn_event)


def test_espn_resolve_cache_key_splits_by_commence_day():
    k1 = _espn_resolve_cache_key("Lakers", "Celtics", "2026-03-18T02:00:00Z")
    k2 = _espn_resolve_cache_key("Lakers", "Celtics", "2026-04-02T02:00:00Z")
    assert k1 != k2


def test_espn_home_away_matches_odds():
    espn_event = {
        "competitions": [
            {
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {"displayName": "Los Angeles Lakers"},
                    },
                    {
                        "homeAway": "away",
                        "team": {"displayName": "Boston Celtics"},
                    },
                ]
            }
        ]
    }
    assert _espn_home_away_matches_odds(
        espn_event,
        "Los Angeles Lakers",
        "Boston Celtics",
    )
    assert not _espn_home_away_matches_odds(
        espn_event,
        "Boston Celtics",
        "Los Angeles Lakers",
    )


def test_grade_prop_exact_player_and_over():
    stat_map = {"lebronjames": {"PTS": 30.0}}
    g, d = grade_prop(
        "LeBron James",
        "player_points",
        25.5,
        "over",
        stat_map,
    )
    assert g == "win"
    assert d["player_match"] == "exact"
    assert d["stat_present"] is True


def test_grade_prop_player_not_found():
    stat_map = {"otherplayer": {"PTS": 10.0}}
    g, d = grade_prop(
        "LeBron James",
        "player_points",
        25.5,
        "over",
        stat_map,
    )
    assert g is None
    assert d["player_match"] == "none"


def test_grade_prop_fuzzy_generational_suffix():
    stat_map = {"robertwilliamsiii": {"REB": 8.0}}
    g, d = grade_prop(
        "Robert Williams",
        "player_rebounds",
        6.5,
        "over",
        stat_map,
    )
    assert g == "win"
    assert d["player_match"] == "fuzzy"
    assert d["stat_present"] is True


def test_grade_prop_fuzzy_initial_and_last_name():
    stat_map = {"robertwilliams": {"REB": 8.0}}
    g, d = grade_prop(
        "R. Williams",
        "player_rebounds",
        6.5,
        "over",
        stat_map,
    )
    assert g == "win"
    assert d["player_match"] == "fuzzy"


def test_grade_prop_ambiguous_initial_last_name_skips():
    stat_map = {
        "johnsmith": {"PTS": 10.0},
        "janesmith": {"PTS": 12.0},
    }
    g, d = grade_prop(
        "J. Smith",
        "player_points",
        11.5,
        "over",
        stat_map,
    )
    assert g is None
    assert d["player_match"] == "none"


def test_stat_label_to_key_maps_espn_3pt_column():
    """ESPN NBA summary boxscore uses label '3PT' for three-pointers made-attempted."""
    assert _stat_label_to_key("3PT") == "3PM"


def test_build_player_stat_map_parses_3pt_column_to_3pm():
    summary = {
        "boxscore": {
            "players": [
                {
                    "statistics": [
                        {
                            "names": ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST"],
                            "athletes": [
                                {
                                    "athlete": {"displayName": "James Harden"},
                                    "stats": ["36", "17", "6-15", "5-12", "0-0", "5", "14"],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    }
    m = build_player_stat_map(summary)
    assert m["jamesharden"]["3PM"] == 5.0


def test_build_auto_settle_scoreboard_dates_includes_commence_window():
    commence = datetime(2026, 3, 18, 2, 0, tzinfo=timezone.utc)
    now = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    dates = build_auto_settle_scoreboard_dates(commence, now=now)
    assert "20260317" in dates
    assert "20260318" in dates
    assert "20260319" in dates
