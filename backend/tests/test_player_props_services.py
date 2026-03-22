from services.player_props import _normalize_prop_outcomes, _parse_prop_sides, get_player_prop_markets


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


def test_parse_prop_sides_builds_surface_aware_payload():
    event_payload = {
        "id": "evt-1",
        "home_team": "Suns",
        "away_team": "Nuggets",
        "commence_time": "2026-03-21T03:00:00Z",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": -110},
                            {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -110},
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
                            {"name": "Over", "description": "Nikola Jokic", "point": 24.5, "price": 105},
                            {"name": "Under", "description": "Nikola Jokic", "point": 24.5, "price": -125},
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

    assert len(sides) == 2
    first = sides[0]
    assert first["surface"] == "player_props"
    assert first["market_key"] == "player_points"
    assert first["selection_key"].startswith("evt-1|player_points|nikola jokic")
    assert first["display_name"].startswith("Nikola Jokic")
