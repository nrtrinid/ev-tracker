import pytest
from datetime import datetime, timezone

from services.espn_scoreboard import (
    build_matchup_player_lookup,
    build_scoreboard_date_window,
    extract_national_tv_matchups,
)


def test_extract_national_tv_matchups_prioritizes_broadcast_tiers_and_caps_in_order():
    payload = {
        "events": [
            {
                "id": "1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Lakers"}},
                            {"homeAway": "away", "team": {"displayName": "Celtics"}},
                        ],
                    }
                ],
            },
            {
                "id": "2",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["TNT"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Knicks"}},
                            {"homeAway": "away", "team": {"displayName": "Bulls"}},
                        ],
                    }
                ],
            },
            {
                "id": "3",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["NBA TV"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Heat"}},
                            {"homeAway": "away", "team": {"displayName": "Magic"}},
                        ],
                    }
                ],
            },
            {
                "id": "4",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ABC"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Suns"}},
                            {"homeAway": "away", "team": {"displayName": "Nuggets"}},
                        ],
                    }
                ],
            },
            {
                "id": "5",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["ESPN2"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Clippers"}},
                            {"homeAway": "away", "team": {"displayName": "Warriors"}},
                        ],
                    }
                ],
            },
            {
                "id": "6",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["Regional"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Pelicans"}},
                            {"homeAway": "away", "team": {"displayName": "Kings"}},
                        ],
                    }
                ],
            },
        ]
    }

    out = extract_national_tv_matchups(payload, max_games=3)

    assert [game["event_id"] for game in out] == ["1", "2", "4"]
    assert [game["selection_reason"] for game in out] == ["national_tv", "national_tv", "national_tv"]


def test_extract_national_tv_matchups_falls_back_to_nba_tv_then_scoreboard_games():
    payload = {
        "events": [
            {
                "id": "1",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["NBA TV"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Lakers"}},
                            {"homeAway": "away", "team": {"displayName": "Celtics"}},
                        ],
                    }
                ],
            },
            {
                "id": "2",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["Regional"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Knicks"}},
                            {"homeAway": "away", "team": {"displayName": "Bulls"}},
                        ],
                    }
                ],
            },
            {
                "id": "3",
                "competitions": [
                    {
                        "broadcasts": [{"names": ["League Pass"]}],
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Heat"}},
                            {"homeAway": "away", "team": {"displayName": "Magic"}},
                        ],
                    }
                ],
            }
        ]
    }

    out = extract_national_tv_matchups(payload)

    assert [game["event_id"] for game in out] == ["1", "2", "3"]
    assert [game["selection_reason"] for game in out] == ["nba_tv", "scoreboard_fallback", "scoreboard_fallback"]


def test_build_scoreboard_date_window_includes_adjacent_days():
    out = build_scoreboard_date_window(datetime(2026, 3, 22, 5, 0, tzinfo=timezone.utc))

    assert out == ["20260321", "20260322", "20260323"]


@pytest.mark.asyncio
async def test_build_matchup_player_lookup_merges_home_and_away_rosters(monkeypatch):
    async def _fake_fetch_team_roster(team_id: str):
        if team_id == "home-1":
            return {
                "athletes": [
                    {"id": "p1", "fullName": "Nikola Jokic", "displayName": "Nikola Jokic"},
                ]
            }
        return {
            "athletes": [
                {"id": "p2", "fullName": "Kevin Durant", "displayName": "Kevin Durant"},
            ]
        }

    monkeypatch.setattr("services.espn_scoreboard.fetch_team_roster", _fake_fetch_team_roster)

    out = await build_matchup_player_lookup(
        home_team_id="home-1",
        home_team_name="Denver Nuggets",
        away_team_id="away-1",
        away_team_name="Phoenix Suns",
    )

    assert out["nikolajokic"] == {"team": "Denver Nuggets", "participant_id": "p1"}
    assert out["kevindurant"] == {"team": "Phoenix Suns", "participant_id": "p2"}
