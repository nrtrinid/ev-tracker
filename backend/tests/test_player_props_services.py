import pytest
import httpx

from services.player_props import (
    PLAYER_PROP_REFERENCE_SOURCE,
    _build_prop_side_candidates,
    _match_curated_events,
    _normalize_prop_outcomes,
    _parse_prop_sides,
    get_player_prop_markets,
    scan_player_props,
)


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
                            {"name": "Over", "description": "Nikola Jokic (Nuggets)", "point": 24.5, "price": 105},
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
    assert first_draftkings["reference_odds"] == -104


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
