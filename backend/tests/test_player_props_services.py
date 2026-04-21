import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import httpx

from services.player_props import (
    ALT_PITCHER_K_LOOKUP_MAX_CANDIDATE_EVENTS,
    ALT_PITCHER_K_LOOKUP_MARKET_KEY,
    ALT_PITCHER_K_LOOKUP_NORMAL_MARKET_KEY,
    ALT_PITCHER_K_LOOKUP_TTL_SECONDS,
    PLAYER_PROP_REFERENCE_SOURCE,
    _alt_pitcher_k_lookup_cache_key,
    _aggregate_reference_estimates,
    _build_pickem_cards_from_candidates,
    _book_weight_for_model,
    _build_prizepicks_comparison_cards,
    _build_prop_side_candidates,
    _compute_confidence,
    _interpolate_logit_probability,
    _prop_cache_slot,
    _match_curated_events,
    _normalize_prop_outcomes,
    _parse_prop_sides,
    _shrink_probability_toward_even,
    _weighted_consensus_prob,
    get_cached_or_scan_player_props,
    get_player_prop_markets,
    lookup_alt_pitcher_k_exact_line,
    scan_player_props,
    scan_player_props_for_event_ids,
)
from services.prizepicks import _normalize_prizepicks_projection


def test_get_player_prop_markets_defaults_to_all_when_env_missing(monkeypatch):
    monkeypatch.delenv("PLAYER_PROP_MARKETS", raising=False)
    assert get_player_prop_markets() == [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_points_rebounds_assists",
        "player_threes",
    ]


def test_get_player_prop_markets_filters_to_supported_env_values(monkeypatch):
    monkeypatch.setenv("PLAYER_PROP_MARKETS", "player_points,player_assists,unknown_market")
    assert get_player_prop_markets() == ["player_points", "player_assists"]


def test_get_player_prop_markets_uses_mlb_defaults_for_baseball(monkeypatch):
    monkeypatch.delenv("PLAYER_PROP_MARKETS", raising=False)
    assert get_player_prop_markets("baseball_mlb") == [
        "pitcher_strikeouts",
        "batter_total_bases",
        "batter_total_bases_alternate",
        "batter_hits",
        "batter_hits_runs_rbis",
    ]


def test_get_player_prop_markets_filters_env_values_per_sport(monkeypatch):
    monkeypatch.setenv(
        "PLAYER_PROP_MARKETS",
        "player_points,pitcher_strikeouts,batter_hits,unknown_market",
    )
    assert get_player_prop_markets("baseball_mlb") == [
        "pitcher_strikeouts",
        "batter_hits",
    ]


def test_get_player_prop_markets_shadow_toggle_does_not_change_mlb_defaults(monkeypatch):
    monkeypatch.delenv("PLAYER_PROP_MARKETS", raising=False)
    monkeypatch.setenv("PLAYER_PROP_INCLUDE_SHADOW_MARKETS", "baseball_mlb")

    assert get_player_prop_markets("baseball_mlb") == [
        "pitcher_strikeouts",
        "batter_total_bases",
        "batter_total_bases_alternate",
        "batter_hits",
        "batter_hits_runs_rbis",
    ]


def test_get_player_prop_markets_specific_shadow_toggle_does_not_change_mlb_defaults(monkeypatch):
    monkeypatch.delenv("PLAYER_PROP_MARKETS", raising=False)
    monkeypatch.setenv("PLAYER_PROP_INCLUDE_SHADOW_MARKETS", "batter_strikeouts")

    assert get_player_prop_markets("baseball_mlb") == [
        "pitcher_strikeouts",
        "batter_total_bases",
        "batter_total_bases_alternate",
        "batter_hits",
        "batter_hits_runs_rbis",
    ]


def test_get_player_prop_markets_can_append_alternate_mlb_markets_via_sport_toggle(monkeypatch):
    monkeypatch.delenv("PLAYER_PROP_MARKETS", raising=False)
    monkeypatch.setenv("PLAYER_PROP_INCLUDE_ALTERNATE_MARKETS", "baseball_mlb")

    assert get_player_prop_markets("baseball_mlb") == [
        "pitcher_strikeouts",
        "batter_total_bases",
        "batter_total_bases_alternate",
        "batter_hits",
        "batter_hits_runs_rbis",
        "pitcher_strikeouts_alternate",
        "batter_hits_alternate",
    ]


def test_get_player_prop_markets_explicit_market_override_wins_over_shadow_toggle(monkeypatch):
    monkeypatch.setenv("PLAYER_PROP_INCLUDE_SHADOW_MARKETS", "all")
    monkeypatch.setenv("PLAYER_PROP_MARKETS", "batter_hits")

    assert get_player_prop_markets("baseball_mlb") == ["batter_hits"]


@pytest.mark.asyncio
async def test_scan_player_props_tracks_provider_vs_supported_book_coverage(monkeypatch):
    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "baseball_mlb"
        assert event_id == "evt-1"
        assert markets == ["batter_hits"]
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Los Angeles Dodgers",
            "away_team": "San Diego Padres",
            "commence_time": "2099-03-21T03:00:00Z",
            "bookmakers": [
                {
                    "key": "fanatics",
                    "markets": [
                        {
                            "key": "batter_hits",
                            "outcomes": [
                                {"name": "Over", "description": "Mookie Betts", "point": 1.5, "price": -110},
                                {"name": "Under", "description": "Mookie Betts", "point": 1.5, "price": -110},
                            ],
                        }
                    ],
                }
            ],
        }, response

    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)

    result = await scan_player_props_for_event_ids(
        sport="baseball_mlb",
        event_ids=["evt-1"],
        markets=["batter_hits"],
        source="manual_scan",
    )

    diagnostics = result["diagnostics"]
    assert diagnostics["events_with_provider_markets"] == 1
    assert diagnostics["events_with_supported_book_markets"] == 0
    assert diagnostics["events_provider_only"] == 1
    assert diagnostics["provider_market_event_counts"] == {"batter_hits": 1}
    assert diagnostics["supported_book_market_event_counts"] == {"batter_hits": 0}
    assert diagnostics["candidate_sides_count"] == 0


def test_normalize_prop_outcomes_keeps_complete_over_under_pairs():
    outcomes = [
        {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -110},
        {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -110},
        {"name": "Over", "description": "Jamal Murray", "point": 19.5, "price": -105},
    ]

    normalized = _normalize_prop_outcomes(outcomes)

    assert len(normalized) == 2
    assert {entry["name"] for entry in normalized} == {"Over", "Under"}


def test_normalize_prop_outcomes_maps_home_run_yes_no_to_over_under_with_point():
    outcomes = [
        {"name": "Yes", "description": "Shohei Ohtani", "price": 175},
        {"name": "No", "description": "Shohei Ohtani", "price": -230},
    ]

    normalized = _normalize_prop_outcomes(outcomes, market_key="batter_home_runs")

    assert len(normalized) == 2
    assert {entry["name"] for entry in normalized} == {"Over", "Under"}
    assert {entry.get("point") for entry in normalized} == {0.5}


def test_normalize_prop_outcomes_ignores_yes_no_for_non_yes_no_markets():
    outcomes = [
        {"name": "Yes", "description": "Nikola Jokic", "price": 105},
        {"name": "No", "description": "Nikola Jokic", "price": -125},
    ]

    normalized = _normalize_prop_outcomes(outcomes, market_key="player_points")

    assert normalized == []


def test_normalize_prop_outcomes_canonicalizes_alt_total_bases_thresholds():
    outcomes = [
        {"name": "Over", "description": "Mookie Betts", "point": 2, "price": 145},
    ]

    normalized = _normalize_prop_outcomes(
        outcomes,
        market_key="batter_total_bases_alternate",
        require_pairs=False,
    )

    assert len(normalized) == 1
    assert normalized[0]["name"] == "Over"
    assert normalized[0]["point"] == 1.5
    assert normalized[0]["source_point"] == 2.0


def test_match_curated_events_uses_canonical_team_pairs():
    curated_games = [
        {
            "home_team": "LA Clippers",
            "away_team": "New York Knicks",
            "home_team_key": "laclippers",
            "away_team_key": "newyorkknicks",
        }
    ]
    odds_events = [
        {
            "id": "evt-1",
            "home_team": "Los Angeles Clippers",
            "away_team": "New York Knicks",
        },
        {
            "id": "evt-2",
            "home_team": "Boston Celtics",
            "away_team": "Miami Heat",
        },
    ]

    matched = _match_curated_events(curated_games, odds_events)

    assert [event["id"] for event in matched] == ["evt-1"]


def test_parse_prop_sides_builds_consensus_reference_payload():
    event_payload = {
        "id": "evt-1",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "betmgm",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -120},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": 100},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "link": "https://example.test/jokic",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Nikola Jokic (Nuggets)",
                                "point": 24.5,
                                "price": 105,
                                "link": "https://example.test/jokic/over",
                            },
                            {
                                "name": "Under",
                                "description": "Nikola Jokic (Nuggets)",
                                "point": 24.5,
                                "price": -125,
                                "link": "https://example.test/jokic/under",
                            },
                        ],
                    }
                ],
            },
        ],
    }

    sides = _parse_prop_sides(
        sport="basketball_nba",
        event_payload=event_payload,
        target_markets=["player_points"],
        min_reference_bookmakers=2,
    )

    assert len(sides) == 6
    first_draftkings = next(side for side in sides if side["sportsbook"] == "DraftKings" and side["selection_side"] == "over")
    assert first_draftkings["surface"] == "player_props"
    assert first_draftkings["market_key"] == "player_points"
    assert first_draftkings["selection_key"].startswith("evt-1|player_points|nikola jokic")
    assert first_draftkings["display_name"] == "Nikola Jokic Over 24.5 PTS"
    assert first_draftkings["reference_source"] == PLAYER_PROP_REFERENCE_SOURCE
    assert first_draftkings["reference_bookmakers"] == ["bovada", "betmgm"]
    assert first_draftkings["reference_bookmaker_count"] == 2
    assert first_draftkings["confidence_label"] == "solid"
    assert isinstance(first_draftkings["confidence_score"], float)
    assert 0.0 <= first_draftkings["confidence_score"] <= 1.0
    assert first_draftkings["reference_odds"] == -104
    assert first_draftkings["sportsbook_deeplink_url"] == "https://example.test/jokic/over"
    assert first_draftkings["sportsbook_deeplink_level"] == "selection"


def test_build_pickem_cards_from_candidates_uses_looser_pickem_gate():
    candidates = [
        {
            "event_id": "evt-1",
            "market_key": "player_points",
            "selection_key": "evt-1|player_points|nikola jokic|over|24.5",
            "sportsbook": "DraftKings",
            "sport": "basketball_nba",
            "event": "Nuggets @ Suns",
            "commence_time": "2026-03-21T03:00:00Z",
            "market": "player_points",
            "player_name": "Nikola Jokic",
            "team": "Denver Nuggets",
            "opponent": "Phoenix Suns",
            "selection_side": "over",
            "line_value": 24.5,
            "book_odds": 105,
            "true_prob": 0.56,
            "ev_percentage": 6.2,
            "reference_bookmaker_count": 3,
        },
        {
            "event_id": "evt-1",
            "market_key": "player_points",
            "selection_key": "evt-1|player_points|nikola jokic|under|24.5",
            "sportsbook": "DraftKings",
            "sport": "basketball_nba",
            "event": "Nuggets @ Suns",
            "commence_time": "2026-03-21T03:00:00Z",
            "market": "player_points",
            "player_name": "Nikola Jokic",
            "team": "Denver Nuggets",
            "opponent": "Phoenix Suns",
            "selection_side": "under",
            "line_value": 24.5,
            "book_odds": -125,
            "true_prob": 0.44,
            "ev_percentage": 1.3,
            "reference_bookmaker_count": 2,
        },
        {
            "event_id": "evt-1",
            "market_key": "player_points",
            "selection_key": "evt-1|player_points|nikola jokic|over|24.5",
            "sportsbook": "FanDuel",
            "sport": "basketball_nba",
            "event": "Nuggets @ Suns",
            "commence_time": "2026-03-21T03:00:00Z",
            "market": "player_points",
            "player_name": "Nikola Jokic",
            "team": "Denver Nuggets",
            "opponent": "Phoenix Suns",
            "selection_side": "over",
            "line_value": 24.5,
            "book_odds": 110,
            "true_prob": 0.57,
            "ev_percentage": 7.1,
            "reference_bookmaker_count": 2,
        },
        {
            "event_id": "evt-1",
            "market_key": "player_points",
            "selection_key": "evt-1|player_points|nikola jokic|under|24.5",
            "sportsbook": "FanDuel",
            "sport": "basketball_nba",
            "event": "Nuggets @ Suns",
            "commence_time": "2026-03-21T03:00:00Z",
            "market": "player_points",
            "player_name": "Nikola Jokic",
            "team": "Denver Nuggets",
            "opponent": "Phoenix Suns",
            "selection_side": "under",
            "line_value": 24.5,
            "book_odds": -120,
            "true_prob": 0.43,
            "ev_percentage": 1.1,
            "reference_bookmaker_count": 2,
        },
    ]

    assert _build_pickem_cards_from_candidates(candidates, min_reference_bookmakers=3) == []

    pickem_cards = _build_pickem_cards_from_candidates(candidates, min_reference_bookmakers=2)

    assert len(pickem_cards) == 1
    assert pickem_cards[0]["comparison_key"] == "evt-1|player_points|nikolajokic|24.5"
    assert pickem_cards[0]["exact_line_bookmaker_count"] == 2
    assert pickem_cards[0]["consensus_side"] == "over"


def test_parse_prop_sides_canonicalizes_betmgm_state_template_links():
    event_payload = {
        "id": "evt-homepage",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "betonlineag",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -120},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": 100},
                        ],
                    }
                ],
            },
            {
                "key": "betmgm",
                "link": "https://sports.{state}.betmgm.com/en/sports/events/evt-homepage",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Nikola Jokic (Nuggets)",
                                "point": 24.5,
                                "price": 105,
                                "link": "https://sports.{state}.betmgm.com/en/sports?options=bad",
                            },
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -125},
                        ],
                    }
                ],
            },
        ],
    }

    sides = _parse_prop_sides(
        sport="basketball_nba",
        event_payload=event_payload,
        target_markets=["player_points"],
        min_reference_bookmakers=2,
    )

    betmgm_over = next(side for side in sides if side["sportsbook"] == "BetMGM" and side["selection_side"] == "over")
    assert betmgm_over["sportsbook_deeplink_url"] == "https://sports.betmgm.com/en/sports?options=bad"
    assert betmgm_over["sportsbook_deeplink_level"] == "selection"


def test_parse_prop_sides_uses_lookup_for_team_and_participant_context():
    event_payload = {
        "id": "evt-lookup",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Jamal Murray", "point": 23.5, "price": -110},
                            {"name": "Under", "description": "Jamal Murray", "point": 23.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "betonlineag",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Jamal Murray", "point": 23.5, "price": -108},
                            {"name": "Under", "description": "Jamal Murray", "point": 23.5, "price": -112},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Jamal Murray", "point": 23.5, "price": 105},
                            {"name": "Under", "description": "Jamal Murray", "point": 23.5, "price": -125},
                        ],
                    }
                ],
            },
        ],
    }

    sides = _parse_prop_sides(
        sport="basketball_nba",
        event_payload=event_payload,
        target_markets=["player_points"],
        player_context_lookup={
            "jamalmurray": {"team": "Nuggets", "participant_id": "player-27"},
        },
        min_reference_bookmakers=2,
    )

    draftkings_over = next(side for side in sides if side["sportsbook"] == "DraftKings" and side["selection_side"] == "over")
    assert draftkings_over["participant_id"] == "player-27"
    assert draftkings_over["team"] == "Nuggets"
    assert draftkings_over["opponent"] == "Suns"


def test_parse_prop_sides_filters_thin_consensus_candidates_by_default():
    event_payload = {
        "id": "evt-thin",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": 105},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -125},
                        ],
                    }
                ],
            },
        ],
    }

    candidates = _build_prop_side_candidates(
        sport="basketball_nba",
        event_payload=event_payload,
        target_markets=["player_points"],
    )
    surfaced = _parse_prop_sides(
        sport="basketball_nba",
        event_payload=event_payload,
        target_markets=["player_points"],
    )
    thin_ok = _parse_prop_sides(
        sport="basketball_nba",
        event_payload=event_payload,
        target_markets=["player_points"],
        min_reference_bookmakers=1,
    )

    assert len(candidates) == 4
    assert {side["reference_bookmaker_count"] for side in candidates} == {1}
    assert surfaced == []
    assert len(thin_ok) == 4


def test_build_prop_side_candidates_supports_one_sided_alt_total_bases_target_offer():
    event_payload = {
        "id": "evt-alt-tb",
        "home_team": "Dodgers",
        "away_team": "Padres",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "batter_total_bases_alternate",
                        "outcomes": [
                            {"name": "Over", "description": "Mookie Betts (Dodgers)", "point": 2, "price": 140},
                        ],
                    }
                ],
            },
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "batter_total_bases",
                        "outcomes": [
                            {"name": "Over", "description": "Mookie Betts (Dodgers)", "point": 1.5, "price": -115},
                            {"name": "Under", "description": "Mookie Betts (Dodgers)", "point": 1.5, "price": -105},
                        ],
                    }
                ],
            },
            {
                "key": "betonlineag",
                "markets": [
                    {
                        "key": "batter_total_bases",
                        "outcomes": [
                            {"name": "Over", "description": "Mookie Betts (Dodgers)", "point": 1.5, "price": -110},
                            {"name": "Under", "description": "Mookie Betts (Dodgers)", "point": 1.5, "price": -110},
                        ],
                    }
                ],
            },
        ],
    }

    candidates = _build_prop_side_candidates(
        sport="baseball_mlb",
        event_payload=event_payload,
        target_markets=["batter_total_bases", "batter_total_bases_alternate"],
    )

    alt_offer = next(
        side for side in candidates
        if side["sportsbook"] == "FanDuel"
        and side["market_key"] == "batter_total_bases_alternate"
        and side["selection_side"] == "over"
    )

    assert alt_offer["line_value"] == 1.5
    assert alt_offer["display_name"] == "Mookie Betts Over 2+ TB ALT"
    assert alt_offer["reference_bookmakers"] == ["bovada", "betonlineag"]
    assert alt_offer["reference_bookmaker_count"] == 2


def test_normalize_prizepicks_projection_maps_supported_nba_market():
    included_index = {
        "new_player:173819": {
            "type": "new_player",
            "id": "173819",
            "attributes": {
                "combo": False,
                "display_name": "Victor Wembanyama",
                "name": "Victor Wembanyama",
                "ppid": "pp-victor",
                "team": "SAS",
                "team_name": "Spurs",
            },
            "relationships": {
                "team_data": {"data": {"type": "team", "id": "870"}},
            },
        },
        "game:138259": {
            "type": "game",
            "id": "138259",
            "attributes": {
                "external_game_id": "NBA_game_123",
                "start_time": "2026-03-23T19:00:00.000-04:00",
                "status": "scheduled",
            },
            "relationships": {
                "away_team_data": {"data": {"type": "team", "id": "870"}},
                "home_team_data": {"data": {"type": "team", "id": "212"}},
            },
        },
        "team:870": {
            "type": "team",
            "id": "870",
            "attributes": {"abbreviation": "SAS", "market": "San Antonio", "name": "Spurs"},
        },
        "team:212": {
            "type": "team",
            "id": "212",
            "attributes": {"abbreviation": "MIA", "market": "Miami", "name": "Heat"},
        },
        "stat_type:11": {
            "type": "stat_type",
            "id": "11",
            "attributes": {"name": "Points"},
        },
    }
    projection = {
        "type": "projection",
        "id": "10806661",
        "attributes": {
            "odds_type": "standard",
            "projection_type": "Single Stat",
            "line_score": 24.5,
            "status": "pre_game",
            "start_time": "2026-03-23T19:10:00.000-04:00",
        },
        "relationships": {
            "new_player": {"data": {"type": "new_player", "id": "173819"}},
            "game": {"data": {"type": "game", "id": "138259"}},
            "stat_type": {"data": {"type": "stat_type", "id": "11"}},
        },
    }

    normalized = _normalize_prizepicks_projection(projection, included_index)

    assert normalized is not None
    assert normalized["market_key"] == "player_points"
    assert normalized["event"] == "San Antonio Spurs @ Miami Heat"
    assert normalized["team"] == "San Antonio Spurs"
    assert normalized["opponent"] == "Miami Heat"
    assert normalized["participant_id"] == "pp-victor"


@pytest.mark.asyncio
async def test_fetch_prizepicks_board_uses_recent_cache_when_retry_exhausts(monkeypatch):
    import services.http_client as http_client_module
    import services.prizepicks as prizepicks_module

    await http_client_module.close_async_client()

    prizepicks_module._prizepicks_board_cache["fetched_at"] = 0.0
    prizepicks_module._prizepicks_board_cache["board"] = []

    sample_payload = {
        "data": [
            {
                "type": "projection",
                "id": "10806661",
                "attributes": {
                    "odds_type": "standard",
                    "projection_type": "Single Stat",
                    "line_score": 24.5,
                    "status": "pre_game",
                    "start_time": "2026-03-23T19:10:00.000-04:00",
                },
                "relationships": {
                    "new_player": {"data": {"type": "new_player", "id": "173819"}},
                    "game": {"data": {"type": "game", "id": "138259"}},
                    "stat_type": {"data": {"type": "stat_type", "id": "11"}},
                },
            }
        ],
        "included": [
            {
                "type": "new_player",
                "id": "173819",
                "attributes": {
                    "combo": False,
                    "display_name": "Victor Wembanyama",
                    "name": "Victor Wembanyama",
                    "ppid": "pp-victor",
                    "team": "SAS",
                    "team_name": "Spurs",
                },
                "relationships": {
                    "team_data": {"data": {"type": "team", "id": "870"}},
                },
            },
            {
                "type": "game",
                "id": "138259",
                "attributes": {
                    "external_game_id": "NBA_game_123",
                    "start_time": "2026-03-23T19:00:00.000-04:00",
                    "status": "scheduled",
                },
                "relationships": {
                    "away_team_data": {"data": {"type": "team", "id": "870"}},
                    "home_team_data": {"data": {"type": "team", "id": "212"}},
                },
            },
            {
                "type": "team",
                "id": "870",
                "attributes": {"abbreviation": "SAS", "market": "San Antonio", "name": "Spurs"},
            },
            {
                "type": "team",
                "id": "212",
                "attributes": {"abbreviation": "MIA", "market": "Miami", "name": "Heat"},
            },
            {
                "type": "stat_type",
                "id": "11",
                "attributes": {"name": "Points"},
            },
        ],
    }

    class _SuccessClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            request = httpx.Request("GET", "https://api.prizepicks.com/projections")
            return httpx.Response(200, request=request, json=sample_payload)

    monkeypatch.setattr(prizepicks_module.httpx, "AsyncClient", _SuccessClient)
    first_board = await prizepicks_module.fetch_prizepicks_nba_board()

    assert len(first_board) == 1

    class _FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("temporary failure")

    monkeypatch.setattr(prizepicks_module.httpx, "AsyncClient", _FailingClient)
    await http_client_module.close_async_client()
    second_board = await prizepicks_module.fetch_prizepicks_nba_board()

    assert second_board == first_board
    await http_client_module.close_async_client()


def test_build_prizepicks_comparison_cards_requires_exact_line_match():
    event_payload = {
        "id": "evt-1",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 23.5, "price": -110},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 23.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "betmgm",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 23.5, "price": -115},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 23.5, "price": -105},
                        ],
                    }
                ],
            },
        ],
    }

    cards, counts = _build_prizepicks_comparison_cards(
        event_payload=event_payload,
        target_markets=["player_points"],
        prizepicks_projections=[
            {
                "event_id": "NBA_game_123",
                "event": "Nuggets @ Suns",
                "commence_time": "2026-03-21T03:00:00Z",
                "player_name": "Nikola Jokic",
                "participant_id": "pp-jokic",
                "team": "Nuggets",
                "opponent": "Suns",
                "market_key": "player_points",
                "line_value": 24.5,
            }
        ],
        min_reference_bookmakers=2,
    )

    assert cards == []
    assert counts == {"matched": 0, "unmatched": 1, "filtered": 0}


def test_build_prizepicks_comparison_cards_allows_thin_exact_line_support_for_prizepicks_view():
    event_payload = {
        "id": "evt-1",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": 105},
                            {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -125},
                        ],
                    }
                ],
            },
        ],
    }

    cards, counts = _build_prizepicks_comparison_cards(
        event_payload=event_payload,
        target_markets=["player_points"],
        prizepicks_projections=[
            {
                "event_id": "NBA_game_123",
                "event": "Nuggets @ Suns",
                "commence_time": "2026-03-21T03:00:00Z",
                "player_name": "Nikola Jokic",
                "participant_id": "pp-jokic",
                "team": "Nuggets",
                "opponent": "Suns",
                "market_key": "player_points",
                "line_value": 24.5,
            }
        ],
        min_reference_bookmakers=1,
    )

    assert len(cards) == 1
    assert cards[0]["exact_line_bookmaker_count"] == 1
    assert cards[0]["confidence_label"] == "thin"
    assert counts == {"matched": 1, "unmatched": 0, "filtered": 0}


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_returns_low_confidence_for_two_books(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -125},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr(
        "services.player_props.get_json",
        lambda _key: None,
        raising=False,
    )
    monkeypatch.setattr(
        "services.player_props.set_json",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        assert _sport == "baseball_mlb"
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "baseball_mlb"
        assert event_id == "evt-mlb-1"
        assert markets == [ALT_PITCHER_K_LOOKUP_MARKET_KEY, ALT_PITCHER_K_LOOKUP_NORMAL_MARKET_KEY]
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team=None,
        opponent=None,
        line_value=6.5,
        game_date=None,
    )

    assert result["status"] == "ok"
    assert result["resolution_mode"] == "exact_pair"
    assert result["confidence"]["bucket"] == "low"
    assert result["confidence"]["paired_books_count"] == 2
    assert result["consensus"]["paired_books_count"] == 2
    assert result["consensus"]["reference_books_count"] == 2
    assert result["cache"]["hit"] is False
    assert result["warning"] is None


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_returns_normal_confidence_for_three_books(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -125},
                        ],
                    }
                ],
            },
            {
                "key": "betmgm",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 100},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -120},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=6.5,
        game_date="2026-07-04",
    )

    assert result["status"] == "ok"
    assert result["resolution_mode"] == "exact_pair"
    assert result["confidence"]["bucket"] == "normal"
    assert result["confidence"]["paired_books_count"] == 3
    assert result["consensus"]["paired_books_count"] == 3


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_returns_ambiguous_event_for_doubleheader(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T17:05:00Z",
        },
        {
            "id": "evt-mlb-2",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        },
    ]
    alt_market_payloads = {
        "evt-mlb-1": {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T17:05:00Z",
            "sport_key": "baseball_mlb",
            "bookmakers": [
                {
                    "key": "bovada",
                    "markets": [
                        {
                            "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                            "outcomes": [
                                {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                                {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                            ],
                        }
                    ],
                }
            ],
        },
        "evt-mlb-2": {
            "id": "evt-mlb-2",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
            "sport_key": "baseball_mlb",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                            "outcomes": [
                                {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                                {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -125},
                            ],
                        }
                    ],
                }
            ],
        },
    }

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "baseball_mlb"
        assert markets == [ALT_PITCHER_K_LOOKUP_MARKET_KEY]
        return alt_market_payloads[event_id], httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team=None,
        opponent=None,
        line_value=6.5,
        game_date=None,
    )

    assert result["status"] == "ambiguous_event"
    assert len(result["candidate_events"]) == 2
    assert "Add pitcher team, opponent, or game date" in result["warning"]


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_does_not_fall_back_to_base_market_or_other_line(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    mixed_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                        ],
                    },
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": 120},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": -140},
                        ],
                    },
                ],
            }
        ],
    }

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert markets == [ALT_PITCHER_K_LOOKUP_MARKET_KEY, ALT_PITCHER_K_LOOKUP_NORMAL_MARKET_KEY]
        return mixed_market_payload, httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team=None,
        opponent=None,
        line_value=6.5,
        game_date=None,
    )

    assert result["status"] == "not_found"
    assert result["event"]["event_id"] == "evt-mlb-1"
    assert "Add pitcher team, opponent, or game date" in result["warning"]


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_returns_insufficient_depth_for_single_book(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -125},
                        ],
                    }
                ],
            }
        ],
    }

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=6.5,
        game_date="2026-07-04",
    )

    assert result["status"] == "insufficient_depth"
    assert result["resolution_mode"] == "exact_pair"
    assert result["confidence"]["bucket"] == "insufficient_depth"
    assert result["consensus"]["paired_books_count"] == 1


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_models_from_nearby_paired_lines(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": -150},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": 120},
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": 145},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": -175},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": -145},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": 118},
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": 150},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": -180},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "baseball_mlb"
        assert event_id == "evt-mlb-1"
        assert markets == [ALT_PITCHER_K_LOOKUP_MARKET_KEY, ALT_PITCHER_K_LOOKUP_NORMAL_MARKET_KEY]
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=6.5,
        game_date="2026-07-04",
    )

    assert result["status"] == "ok"
    assert result["resolution_mode"] == "modeled_nearby_pairs"
    assert result["warning"] == "Fair odds are modeled from nearby paired alt lines because no exact target over/under pair was available."
    assert result["consensus"]["paired_books_count"] == 0
    assert result["consensus"]["reference_books_count"] == 2
    assert result["consensus"]["reference_books"] == ["Bovada", "DraftKings"]
    assert result["consensus"]["offers"] == [
        {
            "sportsbook": "FanDuel",
            "over_odds": 105.0,
            "over_deeplink_url": "https://sportsbook.fanduel.com/",
            "under_odds": None,
            "under_deeplink_url": "https://sportsbook.fanduel.com/",
        }
    ]
    assert result["confidence"]["bucket"] == "low"
    assert result["confidence"]["reason"] == "modeled_from_nearby_paired_lines_two_reference_books"
    assert result["confidence"]["paired_books_count"] == 2
    assert result["observed_offers"][0]["line_value"] == 6.5


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_can_use_normal_market_as_secondary_anchor(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    mixed_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": -150},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": 120},
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": 145},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": -175},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "baseball_mlb"
        assert event_id == "evt-mlb-1"
        assert markets == [ALT_PITCHER_K_LOOKUP_MARKET_KEY, "pitcher_strikeouts"]
        return mixed_market_payload, httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=6.5,
        game_date="2026-07-04",
    )

    assert result["status"] == "ok"
    assert result["resolution_mode"] == "modeled_nearby_pairs"
    assert result["warning"] == "Fair odds are modeled from nearby paired alt lines, with the normal pitcher strikeouts market used as a secondary anchor."
    assert result["consensus"]["paired_books_count"] == 0
    assert result["consensus"]["reference_books_count"] == 2
    assert result["consensus"]["reference_books"] == ["Bovada", "DraftKings"]
    assert result["confidence"]["bucket"] == "low"
    assert result["confidence"]["reason"] == "modeled_from_nearby_paired_lines_two_reference_books_with_normal_line_anchor"


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_returns_observed_only_for_one_sided_ladder(monkeypatch):
    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": -140},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": -190},
                        ],
                    },
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -112},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -108},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "baseball_mlb"
        assert event_id == "evt-mlb-1"
        assert markets == [ALT_PITCHER_K_LOOKUP_MARKET_KEY, "pitcher_strikeouts"]
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=6.5,
        game_date="2026-07-04",
    )

    assert result["status"] == "insufficient_depth"
    assert result["resolution_mode"] == "observed_only_one_sided"
    assert result["consensus"] is None
    assert result["confidence"]["bucket"] == "insufficient_depth"
    assert result["confidence"]["reason"] == "one_sided_ladder_only_no_paired_nearby_anchors"
    assert "one-sided alt ladder evidence" in result["warning"]
    assert len(result["observed_offers"]) == 3


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_stops_broad_search_before_event_market_fetch(monkeypatch):
    events_payload = [
        {
            "id": f"evt-mlb-{index}",
            "home_team": f"Home Team {index}",
            "away_team": f"Away Team {index}",
            "commence_time": f"2026-07-{(index % 9) + 1:02d}T23:10:00Z",
        }
        for index in range(ALT_PITCHER_K_LOOKUP_MAX_CANDIDATE_EVENTS + 1)
    ]
    calls = {"fetch_prop_market_for_event": 0}

    monkeypatch.setattr("services.player_props.get_json", lambda _key: None, raising=False)
    monkeypatch.setattr("services.player_props.set_json", lambda *_args, **_kwargs: None, raising=False)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        assert _sport == "baseball_mlb"
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*_args, **_kwargs):
        calls["fetch_prop_market_for_event"] += 1
        raise AssertionError("event-market fetch should not run once the broad-search guardrail trips")

    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events, raising=False)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=False)

    result = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team=None,
        opponent=None,
        line_value=6.5,
        game_date=None,
    )

    assert result["status"] == "ambiguous_event"
    assert result["resolution_mode"] is None
    assert len(result["candidate_events"]) == ALT_PITCHER_K_LOOKUP_MAX_CANDIDATE_EVENTS + 1
    assert "too many live MLB events" in result["warning"]
    assert calls["fetch_prop_market_for_event"] == 0


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_uses_dedicated_cache(monkeypatch):
    import services.player_props as player_props

    store: dict[str, dict] = {}
    stored_ttls: list[int] = []
    calls = {"fetch_events": 0}
    player_props._alt_pitcher_k_lookup_locks.clear()

    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -125},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr(player_props, "get_json", lambda key: store.get(key), raising=True)
    monkeypatch.setattr(
        player_props,
        "set_json",
        lambda key, value, ttl_seconds: (store.__setitem__(key, dict(value)), stored_ttls.append(ttl_seconds)),
        raising=True,
    )

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        calls["fetch_events"] += 1
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr(player_props, "fetch_events", _fake_fetch_events, raising=True)
    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=True)

    first = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=6.5,
        game_date="2026-07-04",
    )
    second = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=6.5,
        game_date="2026-07-04",
    )

    expected_key = _alt_pitcher_k_lookup_cache_key(
        game_date="2026-07-04",
        team="New York Yankees",
        opponent="Boston Red Sox",
        player_name="Gerrit Cole",
        line_value=6.5,
    )
    assert calls["fetch_events"] == 1
    assert expected_key in store
    assert stored_ttls == [ALT_PITCHER_K_LOOKUP_TTL_SECONDS, ALT_PITCHER_K_LOOKUP_TTL_SECONDS]
    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_reuses_cached_event_market_payload_for_other_lines(monkeypatch):
    import services.player_props as player_props

    store: dict[str, dict] = {}
    calls = {"fetch_events": 0, "fetch_prop_market_for_event": 0}
    player_props._alt_pitcher_k_lookup_locks.clear()
    player_props._alt_pitcher_k_event_market_locks.clear()

    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": -150},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": 120},
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": 145},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": -175},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": -145},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 5.5, "price": 118},
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": 150},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 7.5, "price": -180},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr(player_props, "get_json", lambda key: store.get(key), raising=True)
    monkeypatch.setattr(player_props, "set_json", lambda key, value, _ttl: store.__setitem__(key, dict(value)), raising=True)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        calls["fetch_events"] += 1
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        calls["fetch_prop_market_for_event"] += 1
        assert sport == "baseball_mlb"
        assert event_id == "evt-mlb-1"
        assert markets == [ALT_PITCHER_K_LOOKUP_MARKET_KEY, ALT_PITCHER_K_LOOKUP_NORMAL_MARKET_KEY]
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr(player_props, "fetch_events", _fake_fetch_events, raising=True)
    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=True)

    first = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=5.5,
        game_date="2026-07-04",
    )
    second = await lookup_alt_pitcher_k_exact_line(
        player_name="Gerrit Cole",
        team="New York Yankees",
        opponent="Boston Red Sox",
        line_value=7.5,
        game_date="2026-07-04",
    )

    assert calls["fetch_events"] == 2
    assert calls["fetch_prop_market_for_event"] == 1
    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first["resolution_mode"] == "exact_pair"
    assert second["resolution_mode"] == "exact_pair"


@pytest.mark.asyncio
async def test_lookup_alt_pitcher_k_exact_line_dedupes_in_flight_requests(monkeypatch):
    import services.player_props as player_props

    store: dict[str, dict] = {}
    calls = {"fetch_events": 0}
    player_props._alt_pitcher_k_lookup_locks.clear()

    events_payload = [
        {
            "id": "evt-mlb-1",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "commence_time": "2026-07-04T23:10:00Z",
        }
    ]
    alt_market_payload = {
        "id": "evt-mlb-1",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "commence_time": "2026-07-04T23:10:00Z",
        "sport_key": "baseball_mlb",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": ALT_PITCHER_K_LOOKUP_MARKET_KEY,
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": 105},
                            {"name": "Under", "description": "Gerrit Cole (New York Yankees)", "point": 6.5, "price": -125},
                        ],
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr(player_props, "get_json", lambda key: store.get(key), raising=True)
    monkeypatch.setattr(player_props, "set_json", lambda key, value, _ttl: store.__setitem__(key, dict(value)), raising=True)

    async def _fake_fetch_events(_sport: str, *, source: str = "unknown"):
        calls["fetch_events"] += 1
        await asyncio.sleep(0.02)
        return events_payload, httpx.Response(200)

    async def _fake_fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str):
        return alt_market_payload, httpx.Response(200)

    monkeypatch.setattr(player_props, "fetch_events", _fake_fetch_events, raising=True)
    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=True)

    first, second = await asyncio.gather(
        lookup_alt_pitcher_k_exact_line(
            player_name="Gerrit Cole",
            team="New York Yankees",
            opponent="Boston Red Sox",
            line_value=6.5,
            game_date="2026-07-04",
        ),
        lookup_alt_pitcher_k_exact_line(
            player_name="Gerrit Cole",
            team="New York Yankees",
            opponent="Boston Red Sox",
            line_value=6.5,
            game_date="2026-07-04",
        ),
    )

    assert calls["fetch_events"] == 1
    assert {first["cache"]["hit"], second["cache"]["hit"]} == {False, True}


@pytest.mark.asyncio
async def test_scan_player_props_fetches_ranked_curated_matchups(monkeypatch):
    scoreboard_payload = {
        "events": [
            {
                "id": "espn-1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Los Angeles Lakers"}},
                            {"homeAway": "away", "team": {"displayName": "Boston Celtics"}},
                        ],
                    }
                ],
            },
            {
                "id": "espn-2",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["Regional Sports"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Denver Nuggets"}},
                            {"homeAway": "away", "team": {"displayName": "Phoenix Suns"}},
                        ],
                    }
                ],
            },
        ]
    }
    odds_events = [
        {
            "id": "odds-1",
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "commence_time": "2099-03-21T03:00:00Z",
        },
        {
            "id": "odds-2",
            "home_team": "Denver Nuggets",
            "away_team": "Phoenix Suns",
            "commence_time": "2099-03-21T04:00:00Z",
        },
    ]

    called_event_ids = []

    async def _fake_scoreboard():
        return scoreboard_payload

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        assert source == "manual_scan_props_events"
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return odds_events, response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "basketball_nba"
        assert markets == ["player_points"]
        assert source == "manual_scan"
        called_event_ids.append(event_id)
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "commence_time": "2099-03-21T03:00:00Z",
            "bookmakers": [],
        }, response

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)
    monkeypatch.setattr("services.player_props.get_player_prop_markets", lambda: ["player_points"])

    result = await scan_player_props("basketball_nba", source="manual_scan")

    assert called_event_ids == ["odds-1", "odds-2"]
    assert result["events_fetched"] == 2
    assert result["events_with_both_books"] == 0
    assert result["sides"] == []
    assert result["diagnostics"]["matched_event_count"] == 2
    assert result["diagnostics"]["unmatched_game_count"] == 0
    assert len(result["diagnostics"]["curated_games"]) == 2
    assert result["diagnostics"]["markets_requested"] == ["player_points"]


@pytest.mark.asyncio
async def test_scan_player_props_falls_back_to_scoreboard_games_when_no_national_tv_games(monkeypatch):
    scoreboard_payload = {
        "events": [
            {
                "id": "espn-1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["Regional Sports"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Los Angeles Lakers"}},
                            {"homeAway": "away", "team": {"displayName": "Boston Celtics"}},
                        ],
                    }
                ],
            }
        ]
    }
    odds_events = [
        {
            "id": "odds-1",
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "commence_time": "2099-03-21T03:00:00Z",
        }
    ]

    called_event_ids = []

    async def _fake_scoreboard():
        return scoreboard_payload

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return odds_events, response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        called_event_ids.append(event_id)
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "commence_time": "2099-03-21T03:00:00Z",
            "bookmakers": [],
        }, response

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)
    monkeypatch.setattr("services.player_props.get_player_prop_markets", lambda: ["player_points"])

    result = await scan_player_props("basketball_nba")

    assert called_event_ids == ["odds-1"]
    assert result["events_fetched"] == 1
    assert result["events_with_both_books"] == 0
    assert result["sides"] == []
    assert result["diagnostics"]["curated_games"][0]["selection_reason"] == "scoreboard_fallback"
    assert result["diagnostics"]["matched_event_count"] == 1


@pytest.mark.asyncio
async def test_scan_player_props_returns_empty_when_scoreboard_has_no_matchups(monkeypatch):
    async def _fake_scoreboard():
        return {"events": []}

    async def _boom_fetch_events(*_args, **_kwargs):
        raise AssertionError("Odds API events should not be fetched without scoreboard games")

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _boom_fetch_events)

    result = await scan_player_props("basketball_nba")

    assert result["events_fetched"] == 0
    assert result["events_with_both_books"] == 0
    assert result["sides"] == []
    assert result["diagnostics"]["scoreboard_event_count"] == 0
    assert result["diagnostics"]["matched_event_count"] == 0
    assert result["diagnostics"]["candidate_sides_count"] == 0
    assert result["diagnostics"]["quality_gate_filtered_count"] == 0


@pytest.mark.asyncio
async def test_scan_player_props_falls_back_to_odds_events_when_curated_games_do_not_match(monkeypatch):
    scoreboard_payload = {
        "events": [
            {
                "id": "espn-1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Los Angeles Lakers", "id": "13"}},
                            {"homeAway": "away", "team": {"displayName": "Boston Celtics", "id": "2"}},
                        ],
                    }
                ],
            }
        ]
    }
    odds_events = [
        {
            "id": "odds-1",
            "home_team": "Phoenix Suns",
            "away_team": "Denver Nuggets",
            "commence_time": "2099-03-21T03:00:00Z",
        }
    ]

    async def _fake_scoreboard():
        return scoreboard_payload

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return odds_events, response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Phoenix Suns",
            "away_team": "Denver Nuggets",
            "commence_time": "2099-03-21T03:00:00Z",
            "bookmakers": [
                {
                    "key": "bovada",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                                {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                            ],
                        }
                    ],
                },
                {
                    "key": "betonlineag",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -108},
                                {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -112},
                            ],
                        }
                    ],
                },
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": 105},
                                {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -125},
                            ],
                        }
                    ],
                },
            ],
        }, response

    async def _fake_lookup(**_kwargs):
        return {}

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)
    monkeypatch.setattr("services.player_props.build_matchup_player_lookup", _fake_lookup)
    monkeypatch.setattr("services.player_props.get_player_prop_markets", lambda: ["player_points"])
    monkeypatch.setattr("services.player_props.get_player_prop_min_reference_bookmakers", lambda: 2)

    result = await scan_player_props("basketball_nba")

    assert result["events_fetched"] == 1
    assert len(result["sides"]) == 6
    assert result["diagnostics"]["matched_event_count"] == 0
    assert result["diagnostics"]["scan_scope"] == "odds_fallback"
    assert result["diagnostics"]["fallback_event_count"] == 1
    assert "widened" in (result["diagnostics"]["fallback_reason"] or "").lower()


@pytest.mark.asyncio
async def test_scan_player_props_prioritizes_fetchable_curated_matches(monkeypatch):
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    later_one = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    later_two = (now + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    scoreboard_payload = {
        "events": [
            {
                "id": "espn-1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Detroit Pistons", "id": "8"}},
                            {"homeAway": "away", "team": {"displayName": "Atlanta Hawks", "id": "1"}},
                        ],
                    }
                ],
            },
            {
                "id": "espn-2",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Minnesota Timberwolves", "id": "16"}},
                            {"homeAway": "away", "team": {"displayName": "Houston Rockets", "id": "10"}},
                        ],
                    }
                ],
            },
            {
                "id": "espn-3",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["NBA League Pass"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Detroit Pistons", "id": "8"}},
                            {"homeAway": "away", "team": {"displayName": "Los Angeles Lakers", "id": "13"}},
                        ],
                    }
                ],
            },
            {
                "id": "espn-4",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["NBA League Pass"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Atlanta Hawks", "id": "1"}},
                            {"homeAway": "away", "team": {"displayName": "Memphis Grizzlies", "id": "29"}},
                        ],
                    }
                ],
            },
            {
                "id": "espn-5",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["NBA League Pass"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Chicago Bulls", "id": "4"}},
                            {"homeAway": "away", "team": {"displayName": "Houston Rockets", "id": "10"}},
                        ],
                    }
                ],
            },
        ]
    }
    odds_events = [
        {
            "id": "odds-soon",
            "home_team": "Detroit Pistons",
            "away_team": "Los Angeles Lakers",
            "commence_time": soon,
        },
        {
            "id": "odds-later-1",
            "home_team": "Atlanta Hawks",
            "away_team": "Memphis Grizzlies",
            "commence_time": later_one,
        },
        {
            "id": "odds-later-2",
            "home_team": "Chicago Bulls",
            "away_team": "Houston Rockets",
            "commence_time": later_two,
        },
    ]

    called_event_ids = []

    async def _fake_scoreboard():
        return scoreboard_payload

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return odds_events, response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        called_event_ids.append(event_id)
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Atlanta Hawks",
            "away_team": "Memphis Grizzlies",
            "commence_time": later_one,
            "bookmakers": [],
        }, response

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)
    monkeypatch.setattr("services.player_props.get_player_prop_markets", lambda: ["player_points"])

    result = await scan_player_props("basketball_nba")

    assert called_event_ids == ["odds-later-1", "odds-later-2"]
    assert result["events_fetched"] == 2
    assert result["diagnostics"]["events_skipped_pregame"] == 1
    assert [game["odds_event_id"] for game in result["diagnostics"]["curated_games"]] == [
        "odds-later-1",
        "odds-later-2",
        "odds-soon",
    ]


@pytest.mark.asyncio
async def test_scan_player_props_fallback_ignores_soon_events_before_truncating(monkeypatch):
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    later = (now + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    scoreboard_payload = {
        "events": [
            {
                "id": "espn-1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Los Angeles Lakers", "id": "13"}},
                            {"homeAway": "away", "team": {"displayName": "Boston Celtics", "id": "2"}},
                        ],
                    }
                ],
            }
        ]
    }
    odds_events = [
        {
            "id": "odds-1",
            "home_team": "Detroit Pistons",
            "away_team": "Los Angeles Lakers",
            "commence_time": soon,
        },
        {
            "id": "odds-2",
            "home_team": "Orlando Magic",
            "away_team": "Indiana Pacers",
            "commence_time": soon,
        },
        {
            "id": "odds-3",
            "home_team": "Philadelphia 76ers",
            "away_team": "Oklahoma City Thunder",
            "commence_time": soon,
        },
        {
            "id": "odds-4",
            "home_team": "Chicago Bulls",
            "away_team": "Houston Rockets",
            "commence_time": later,
        },
    ]

    called_event_ids = []

    async def _fake_scoreboard():
        return scoreboard_payload

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return odds_events, response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        called_event_ids.append(event_id)
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Chicago Bulls",
            "away_team": "Houston Rockets",
            "commence_time": later,
            "bookmakers": [],
        }, response

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)
    monkeypatch.setattr("services.player_props.get_player_prop_markets", lambda: ["player_points"])

    result = await scan_player_props("basketball_nba")

    assert called_event_ids == ["odds-4"]
    assert result["events_fetched"] == 1
    assert result["diagnostics"]["scan_scope"] == "odds_fallback"
    assert result["diagnostics"]["fallback_event_count"] == 1
    assert result["diagnostics"]["events_skipped_pregame"] == 0


@pytest.mark.asyncio
async def test_get_cached_or_scan_player_props_bypasses_cache_for_manual_scan(monkeypatch):
    import services.player_props as player_props

    slot = _prop_cache_slot("basketball_nba")
    now = datetime.now(timezone.utc).timestamp()
    cached_payload = {
        "surface": "player_props",
        "sides": [],
        "events_fetched": 0,
        "events_with_both_books": 0,
        "api_requests_remaining": "99",
        "fetched_at": now,
    }
    fresh_payload = {
        "surface": "player_props",
        "sides": [{"event_id": "fresh-evt"}],
        "events_fetched": 1,
        "events_with_both_books": 1,
        "api_requests_remaining": "98",
    }

    player_props._props_cache.clear()
    player_props._props_locks.clear()
    player_props._props_cache[slot] = dict(cached_payload)

    stored_payloads = []

    monkeypatch.setattr(player_props, "get_scan_cache", lambda _slot: dict(cached_payload), raising=True)
    monkeypatch.setattr(player_props, "set_scan_cache", lambda *_args: stored_payloads.append(_args), raising=True)

    async def _fake_scan(_sport: str, source: str = "unknown"):
        assert source == "manual_scan"
        return dict(fresh_payload)

    monkeypatch.setattr(player_props, "scan_player_props", _fake_scan, raising=True)

    result = await get_cached_or_scan_player_props("basketball_nba", source="manual_scan")

    assert result["cache_hit"] is False
    assert result["sides"] == [{"event_id": "fresh-evt"}]
    assert stored_payloads


@pytest.mark.asyncio
async def test_get_cached_or_scan_player_props_uses_cache_for_non_manual_sources(monkeypatch):
    import services.player_props as player_props

    slot = _prop_cache_slot("basketball_nba")
    now = datetime.now(timezone.utc).timestamp()
    cached_payload = {
        "surface": "player_props",
        "sides": [{"event_id": "cached-evt"}],
        "events_fetched": 1,
        "events_with_both_books": 1,
        "api_requests_remaining": "99",
        "fetched_at": now,
    }

    player_props._props_cache.clear()
    player_props._props_locks.clear()
    player_props._props_cache[slot] = dict(cached_payload)

    async def _boom_scan(*_args, **_kwargs):
        raise AssertionError("scan should not run when non-manual cache is warm")

    monkeypatch.setattr(player_props, "scan_player_props", _boom_scan, raising=True)

    result = await get_cached_or_scan_player_props("basketball_nba", source="ops_snapshot")

    assert result["cache_hit"] is True
    assert result["sides"] == [{"event_id": "cached-evt"}]


@pytest.mark.asyncio
async def test_scan_player_props_reports_quality_gate_filtering(monkeypatch):
    scoreboard_payload = {
        "events": [
            {
                "id": "espn-1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Los Angeles Lakers"}},
                            {"homeAway": "away", "team": {"displayName": "Boston Celtics"}},
                        ],
                    }
                ],
            }
        ]
    }
    odds_events = [
        {
            "id": "odds-1",
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "commence_time": "2099-03-21T03:00:00Z",
        }
    ]

    async def _fake_scoreboard():
        return scoreboard_payload

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return odds_events, response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "commence_time": "2099-03-21T03:00:00Z",
            "bookmakers": [
                {
                    "key": "bovada",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Jayson Tatum (Boston Celtics)", "point": 29.5, "price": -110},
                                {"name": "Under", "description": "Jayson Tatum (Boston Celtics)", "point": 29.5, "price": -110},
                            ],
                        }
                    ],
                },
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Jayson Tatum (Boston Celtics)", "point": 29.5, "price": 105},
                                {"name": "Under", "description": "Jayson Tatum (Boston Celtics)", "point": 29.5, "price": -125},
                            ],
                        }
                    ],
                },
            ],
        }, response

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)
    monkeypatch.setattr("services.player_props.get_player_prop_markets", lambda: ["player_points"])
    monkeypatch.setattr("services.player_props.get_player_prop_min_reference_bookmakers", lambda: 2)

    result = await scan_player_props("basketball_nba")

    assert result["events_fetched"] == 1
    assert result["sides"] == []
    assert result["diagnostics"]["candidate_sides_count"] == 4
    assert result["diagnostics"]["quality_gate_filtered_count"] == 4
    assert result["diagnostics"]["quality_gate_min_reference_bookmakers"] == 2


@pytest.mark.asyncio
async def test_scan_player_props_disables_external_prizepicks_provider(monkeypatch):
    scoreboard_payload = {
        "events": [
            {
                "id": "espn-1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["NBA TV"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Phoenix Suns", "id": "21"}},
                            {"homeAway": "away", "team": {"displayName": "Denver Nuggets", "id": "7"}},
                        ],
                    }
                ],
            }
        ]
    }
    odds_events = [
        {
            "id": "odds-1",
            "home_team": "Phoenix Suns",
            "away_team": "Denver Nuggets",
            "commence_time": "2099-03-21T03:00:00Z",
        }
    ]

    async def _fake_scoreboard():
        return scoreboard_payload

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return odds_events, response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Phoenix Suns",
            "away_team": "Denver Nuggets",
            "commence_time": "2099-03-21T03:00:00Z",
            "bookmakers": [
                {
                    "key": "bovada",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                                {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -110},
                            ],
                        }
                    ],
                },
                {
                    "key": "betonlineag",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -108},
                                {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -112},
                            ],
                        }
                    ],
                },
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": 105},
                                {"name": "Under", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": -125},
                            ],
                        }
                    ],
                },
            ],
        }, response

    async def _fake_lookup(**_kwargs):
        return {"nikolajokic": {"team": "Denver Nuggets", "participant_id": "203999"}}

    monkeypatch.setattr("services.player_props.fetch_nba_scoreboard_window", _fake_scoreboard)
    monkeypatch.setattr("services.player_props.fetch_events", _fake_fetch_events)
    monkeypatch.setattr("services.player_props._fetch_prop_market_for_event", _fake_fetch_prop_event)
    monkeypatch.setattr("services.player_props.build_matchup_player_lookup", _fake_lookup)
    monkeypatch.setattr("services.player_props.get_player_prop_markets", lambda: ["player_points"])
    monkeypatch.setattr("services.player_props.get_player_prop_min_reference_bookmakers", lambda: 2)

    result = await scan_player_props("basketball_nba")

    assert len(result["sides"]) == 6
    assert result["prizepicks_cards"] == []
    assert result["diagnostics"]["prizepicks_status"] == "disabled"
    assert result["diagnostics"]["prizepicks_message"] is None


# ── Weighted consensus probability tests ──────────────────────────────────────


def test_interpolate_logit_probability_is_monotonic_between_brackets():
    lower = _interpolate_logit_probability(
        lower_line=24.5,
        lower_prob=0.58,
        upper_line=25.5,
        upper_prob=0.42,
        target_line=24.75,
    )
    midpoint = _interpolate_logit_probability(
        lower_line=24.5,
        lower_prob=0.58,
        upper_line=25.5,
        upper_prob=0.42,
        target_line=25.0,
    )
    upper = _interpolate_logit_probability(
        lower_line=24.5,
        lower_prob=0.58,
        upper_line=25.5,
        upper_prob=0.42,
        target_line=25.25,
    )

    assert lower is not None and midpoint is not None and upper is not None
    assert 0.42 < upper < midpoint < lower < 0.58


def test_aggregate_reference_estimates_v2_filters_logit_outlier_and_marks_mixed_inputs():
    aggregation = _aggregate_reference_estimates(
        reference_estimates=[
            {"book_key": "betonlineag", "prob": 0.52, "input_mode": "exact"},
            {"book_key": "bovada", "prob": 0.53, "input_mode": "interpolated"},
            {"book_key": "betmgm", "prob": 0.51, "input_mode": "exact"},
            {"book_key": "draftkings", "prob": 0.82, "input_mode": "exact"},
        ],
        model_key="props_v2_shadow",
        market_key="player_points",
        weight_overrides=None,
    )

    assert aggregation is not None
    assert aggregation["filtered_reference_count"] == 3
    assert aggregation["interpolation_mode"] == "mixed"
    assert 0.51 <= aggregation["raw_true_prob"] <= 0.54


def test_shrink_probability_toward_even_is_smaller_for_higher_confidence():
    low_conf_prob, low_conf_shrink = _shrink_probability_toward_even(0.60, confidence_score=0.20)
    high_conf_prob, high_conf_shrink = _shrink_probability_toward_even(0.60, confidence_score=0.80)

    assert low_conf_shrink > high_conf_shrink
    assert abs(0.60 - low_conf_prob) > abs(0.60 - high_conf_prob)


def test_book_weight_for_model_falls_back_to_static_defaults_when_no_override_exists():
    assert _book_weight_for_model(
        book_key="betonlineag",
        market_key="player_points",
        model_key="props_v2_shadow",
        weight_overrides=None,
    ) == 3.0
    assert _book_weight_for_model(
        book_key="bovada",
        market_key="player_points",
        model_key="props_v2_shadow",
        weight_overrides={},
    ) == 1.5


def test_weighted_consensus_prob_single_book_returns_its_own_prob():
    assert _weighted_consensus_prob([0.55], ["draftkings"]) == 0.55


def test_weighted_consensus_prob_equal_weights_returns_mean():
    # Two follower books with equal weight → result is the plain mean
    result = _weighted_consensus_prob([0.50, 0.54], ["draftkings", "fanduel"])
    assert abs(result - 0.52) < 1e-9


def test_weighted_consensus_prob_betonline_pulls_result_toward_its_estimate():
    # betonlineag (weight=3) has prob 0.58; two followers at 0.50
    # weighted mean = (0.58*3 + 0.50 + 0.50) / (3+1+1) = (1.74+1.00)/5 = 0.548
    result = _weighted_consensus_prob(
        [0.50, 0.58, 0.50],
        ["draftkings", "betonlineag", "fanduel"],
    )
    expected = (0.50 * 1.0 + 0.58 * 3.0 + 0.50 * 1.0) / (1.0 + 3.0 + 1.0)
    assert abs(result - expected) < 1e-9
    # Result is clearly pulled above the plain mean (0.527)
    plain_mean = (0.50 + 0.58 + 0.50) / 3
    assert result > plain_mean


def test_weighted_consensus_prob_bovada_has_intermediate_weight():
    # bovada (weight=1.5) at 0.56; one follower at 0.50
    # weighted mean = (0.56*1.5 + 0.50*1.0) / (1.5+1.0) = (0.84+0.50)/2.5 = 0.536
    result = _weighted_consensus_prob([0.56, 0.50], ["bovada", "betmgm"])
    expected = (0.56 * 1.5 + 0.50 * 1.0) / (1.5 + 1.0)
    assert abs(result - expected) < 1e-9


def test_weighted_consensus_prob_excludes_outlier_beyond_threshold():
    # Three books: two agree around 0.50, one outlier at 0.80
    # anchor (median) = 0.50; outlier gap = 0.30 > threshold 0.12 → excluded
    result = _weighted_consensus_prob(
        [0.50, 0.51, 0.80],
        ["draftkings", "fanduel", "betonlineag"],
        outlier_threshold=0.12,
    )
    # betonlineag is excluded as outlier; result is mean of 0.50/0.51 at equal weight
    expected = (0.50 + 0.51) / 2
    assert abs(result - expected) < 1e-9


def test_weighted_consensus_prob_fallback_to_median_when_all_outliers():
    # Highly dispersed set with very tight threshold → all excluded
    result = _weighted_consensus_prob(
        [0.30, 0.70],
        ["draftkings", "fanduel"],
        outlier_threshold=0.01,
    )
    # Both are > 0.01 from median (0.50) → fallback to median = 0.50
    assert abs(result - 0.50) < 1e-9


# ── Confidence scoring tests ───────────────────────────────────────────────────


def test_compute_confidence_thin_for_single_book_no_anchor():
    label, score, std = _compute_confidence(
        reference_bookmakers=["draftkings"],
        reference_probs=[0.55],
    )
    # base=0.25, no anchor, no dispersion → score=0.25 → "thin" (< 0.30)
    assert label == "thin"
    assert abs(score - 0.25) < 1e-4
    assert std == 0.0


def test_compute_confidence_solid_for_two_follower_books_low_dispersion():
    # std is ~0.01, base=0.50, no anchor, small dispersion penalty
    label, score, std = _compute_confidence(
        reference_bookmakers=["draftkings", "fanduel"],
        reference_probs=[0.50, 0.52],
    )
    assert label == "solid"
    assert 0.30 <= score < 0.55


def test_compute_confidence_betonline_anchor_upgrades_two_book_consensus():
    # Same count as above but betonlineag is present → +0.20 bonus → "high"
    label, score, std = _compute_confidence(
        reference_bookmakers=["betonlineag", "draftkings"],
        reference_probs=[0.50, 0.52],
    )
    assert label == "high"
    assert score >= 0.55


def test_compute_confidence_penalises_high_dispersion():
    # 3 books but wildly spread → dispersion penalty should drop label below elite
    label_low_disp, score_low, _ = _compute_confidence(
        reference_bookmakers=["draftkings", "fanduel", "betmgm"],
        reference_probs=[0.50, 0.51, 0.52],
    )
    label_high_disp, score_high, _ = _compute_confidence(
        reference_bookmakers=["draftkings", "fanduel", "betmgm"],
        reference_probs=[0.40, 0.55, 0.65],
    )
    assert score_low > score_high
    assert label_low_disp in ("elite", "high")
    assert label_high_disp in ("solid", "thin")


def test_compute_confidence_four_tight_books_is_elite():
    label, score, std = _compute_confidence(
        reference_bookmakers=["draftkings", "fanduel", "betmgm", "caesars"],
        reference_probs=[0.525, 0.528, 0.522, 0.530],
    )
    assert label == "elite"
    assert score >= 0.75


def test_compute_confidence_betonline_with_high_dispersion_stays_reasonable():
    # betonlineag present but strong disagreement → bonus partially offset by penalty
    label, score, std = _compute_confidence(
        reference_bookmakers=["betonlineag", "draftkings"],
        reference_probs=[0.35, 0.65],
    )
    # std ≈ 0.15, penalty = min(0.15*4, 0.40) = 0.40; base=0.50, bonus=0.20
    # raw = 0.50+0.20-0.40 = 0.30 → "solid"
    assert label in ("solid", "thin")
    assert score <= 0.55


# ── End-to-end confidence field tests ────────────────────────────────────────


def test_parse_prop_sides_exposes_confidence_score_field():
    """All surfaced sides must carry the new confidence_score and prob_std fields."""
    event_payload = {
        "id": "evt-conf",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [{"key": "player_points", "outcomes": [
                    {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -110},
                    {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -110},
                ]}],
            },
            {
                "key": "betonlineag",
                "markets": [{"key": "player_points", "outcomes": [
                    {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -115},
                    {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -105},
                ]}],
            },
            {
                "key": "draftkings",
                "markets": [{"key": "player_points", "outcomes": [
                    {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": 110},
                    {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -130},
                ]}],
            },
        ],
    }
    sides = _parse_prop_sides(
        sport="basketball_nba",
        event_payload=event_payload,
        target_markets=["player_points"],
        min_reference_bookmakers=2,
    )
    assert len(sides) > 0
    for side in sides:
        assert "confidence_score" in side
        assert isinstance(side["confidence_score"], float)
        assert 0.0 <= side["confidence_score"] <= 1.0
        assert "prob_std" in side
        assert isinstance(side["prob_std"], float)


def test_parse_prop_sides_betonline_reference_boosts_confidence_vs_follower_only():
    """A consensus that includes betonlineag should yield higher confidence_score
    than one using the same number of pure follower books."""
    base_bookmaker_set = [
        {
            "key": "bovada",
            "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -110},
                {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -110},
            ]}],
        },
        {
            "key": "betmgm",
            "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -108},
                {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -112},
            ]}],
        },
        {
            "key": "draftkings",
            "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -112},
                {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -108},
            ]}],
        },
    ]

    # Variant with betonlineag instead of betmgm as reference
    betonline_bookmaker_set = [
        {
            "key": "bovada",
            "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -110},
                {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -110},
            ]}],
        },
        {
            "key": "betonlineag",
            "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -108},
                {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -112},
            ]}],
        },
        {
            "key": "draftkings",
            "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -112},
                {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -108},
            ]}],
        },
    ]

    base_payload = {"id": "evt-base", "home_team": "Suns", "away_team": "Nuggets",
                    "commence_time": "2026-03-21T03:00:00Z", "bookmakers": base_bookmaker_set}
    betonline_payload = {"id": "evt-bol", "home_team": "Suns", "away_team": "Nuggets",
                         "commence_time": "2026-03-21T03:00:00Z", "bookmakers": betonline_bookmaker_set}

    dk_side = lambda sides: next(
        s for s in sides if s["sportsbook"] == "DraftKings" and s["selection_side"] == "over"
    )

    base_sides = _parse_prop_sides(sport="basketball_nba", event_payload=base_payload,
                                   target_markets=["player_points"], min_reference_bookmakers=2)
    bol_sides = _parse_prop_sides(sport="basketball_nba", event_payload=betonline_payload,
                                  target_markets=["player_points"], min_reference_bookmakers=2)

    base_score = dk_side(base_sides)["confidence_score"]
    bol_score = dk_side(bol_sides)["confidence_score"]

    # Having betonlineag as a reference should yield a strictly higher confidence_score
    assert bol_score > base_score


def test_parse_prop_sides_high_dispersion_reduces_confidence_score():
    """A consensus where books disagree significantly should score lower than tight agreement."""
    def make_payload(over_tight, under_tight, over_wide, under_wide):
        return {
            "id": "evt-disp",
            "home_team": "Suns",
            "away_team": "Nuggets",
            "commence_time": "2026-03-21T03:00:00Z",
            "bookmakers": [
                {"key": "bovada", "markets": [{"key": "player_points", "outcomes": [
                    {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": over_tight},
                    {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": under_tight},
                ]}]},
                {"key": "betmgm", "markets": [{"key": "player_points", "outcomes": [
                    {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": over_wide},
                    {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": under_wide},
                ]}]},
                {"key": "draftkings", "markets": [{"key": "player_points", "outcomes": [
                    {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": 105},
                    {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -125},
                ]}]},
            ],
        }

    tight_payload = make_payload(-110, -110, -108, -112)  # refs tightly agree
    wide_payload  = make_payload(-130, 110,  -145, 125)   # refs strongly disagree

    dk = lambda sides: next(
        s for s in sides if s["sportsbook"] == "DraftKings" and s["selection_side"] == "over"
    )

    tight_sides = _parse_prop_sides(sport="basketball_nba", event_payload=tight_payload,
                                    target_markets=["player_points"], min_reference_bookmakers=2)
    wide_sides  = _parse_prop_sides(sport="basketball_nba", event_payload=wide_payload,
                                    target_markets=["player_points"], min_reference_bookmakers=2)

    tight_score = dk(tight_sides)["confidence_score"]
    wide_score  = dk(wide_sides)["confidence_score"]

    assert tight_score > wide_score
    # High dispersion should also push prob_std up
    assert dk(wide_sides)["prob_std"] > dk(tight_sides)["prob_std"]
