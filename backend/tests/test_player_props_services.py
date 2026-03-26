from datetime import datetime, timedelta, timezone

import pytest
import httpx

from services.player_props import (
    PLAYER_PROP_REFERENCE_SOURCE,
    _build_prizepicks_comparison_cards,
    _build_prop_side_candidates,
    _compute_confidence,
    _prop_cache_slot,
    _match_curated_events,
    _normalize_prop_outcomes,
    _parse_prop_sides,
    _weighted_consensus_prob,
    get_cached_or_scan_player_props,
    get_player_prop_markets,
    scan_player_props,
)
from services.prizepicks import _normalize_prizepicks_projection


def test_get_player_prop_markets_defaults_to_all_when_env_missing(monkeypatch):
    monkeypatch.delenv("PLAYER_PROP_MARKETS", raising=False)
    assert get_player_prop_markets() == [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
    ]


def test_get_player_prop_markets_filters_to_supported_env_values(monkeypatch):
    monkeypatch.setenv("PLAYER_PROP_MARKETS", "player_points,player_assists,unknown_market")
    assert get_player_prop_markets() == ["player_points", "player_assists"]


def test_normalize_prop_outcomes_keeps_complete_over_under_pairs():
    outcomes = [
        {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -110},
        {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -110},
        {"name": "Over", "description": "Jamal Murray", "point": 19.5, "price": -105},
    ]

    normalized = _normalize_prop_outcomes(outcomes)

    assert len(normalized) == 2
    assert {entry["name"] for entry in normalized} == {"Over", "Under"}


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
    )

    assert len(sides) == 6
    first_draftkings = next(side for side in sides if side["sportsbook"] == "DraftKings" and side["selection_side"] == "over")
    assert first_draftkings["surface"] == "player_props"
    assert first_draftkings["market_key"] == "player_points"
    assert first_draftkings["selection_key"].startswith("evt-1|player_points|nikola jokic")
    assert first_draftkings["display_name"].startswith("Nikola Jokic")
    assert first_draftkings["reference_source"] == PLAYER_PROP_REFERENCE_SOURCE
    assert first_draftkings["reference_bookmakers"] == ["bovada", "betmgm"]
    assert first_draftkings["reference_bookmaker_count"] == 2
    assert first_draftkings["confidence_label"] == "solid"
    assert isinstance(first_draftkings["confidence_score"], float)
    assert 0.0 <= first_draftkings["confidence_score"] <= 1.0
    assert first_draftkings["reference_odds"] == -104
    assert first_draftkings["sportsbook_deeplink_url"] == "https://example.test/jokic/over"
    assert first_draftkings["sportsbook_deeplink_level"] == "selection"


def test_parse_prop_sides_falls_back_to_homepage_when_provider_links_are_unusable():
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
    )

    betmgm_over = next(side for side in sides if side["sportsbook"] == "BetMGM" and side["selection_side"] == "over")
    assert betmgm_over["sportsbook_deeplink_url"] == "https://sports.betmgm.com/"
    assert betmgm_over["sportsbook_deeplink_level"] == "homepage"


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
    import services.prizepicks as prizepicks_module

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
    second_board = await prizepicks_module.fetch_prizepicks_nba_board()

    assert second_board == first_board


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
                                   target_markets=["player_points"])
    bol_sides = _parse_prop_sides(sport="basketball_nba", event_payload=betonline_payload,
                                  target_markets=["player_points"])

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
                                    target_markets=["player_points"])
    wide_sides  = _parse_prop_sides(sport="basketball_nba", event_payload=wide_payload,
                                    target_markets=["player_points"])

    tight_score = dk(tight_sides)["confidence_score"]
    wide_score  = dk(wide_sides)["confidence_score"]

    assert tight_score > wide_score
    # High dispersion should also push prob_std up
    assert dk(wide_sides)["prob_std"] > dk(tight_sides)["prob_std"]
