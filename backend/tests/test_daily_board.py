from datetime import datetime, timezone
import importlib
import sys
import types

import pytest
from services.daily_board import _select_daily_games


def _game(event_id: str, commence_time: str, offers: int = 2) -> dict:
    return {
        "event_id": event_id,
        "event": "Away @ Home",
        "commence_time": commence_time,
        "totals_offers": [{"sportsbook": "Pinnacle", "total": 220.5, "over_odds": -110, "under_odds": -110}] * offers,
    }


def test_select_daily_games_prefers_after_drop_when_before_drop():
    # Before 3:00 PM Phoenix on 2026-03-26.
    now = datetime(2026, 3, 26, 21, 0, 0, tzinfo=timezone.utc)  # 14:00 Phoenix
    games = [
        _game("early", "2026-03-26T22:00:00Z"),  # 15:00 Phoenix (before drop) -> fallback bucket
        _game("post", "2026-03-26T23:00:00Z"),   # 16:00 Phoenix (after drop) -> preferred
        _game("later", "2026-03-27T02:00:00Z"),  # 19:00 Phoenix (after drop) -> preferred
    ]
    selected = _select_daily_games(games, max_games=3, now=now)
    assert selected[0]["event_id"] == "post"
    assert selected[0]["selection_reason"] == "post_drop_preferred"
    assert selected[1]["event_id"] == "later"
    assert selected[1]["selection_reason"] == "post_drop_preferred"
    assert selected[2]["event_id"] == "early"
    assert selected[2]["selection_reason"] == "fallback_pool"


def test_select_daily_games_prefers_after_now_when_after_drop():
    # After 3:00 PM Phoenix on 2026-03-26.
    now = datetime(2026, 3, 27, 0, 0, 0, tzinfo=timezone.utc)  # 17:00 Phoenix
    games = [
        _game("before_now", "2026-03-26T23:30:00Z"),  # 16:30 Phoenix, still future relative to cutoff? (but before now)
        _game("after_now", "2026-03-27T01:00:00Z"),   # 18:00 Phoenix
    ]
    selected = _select_daily_games(games, max_games=2, now=now)
    assert selected[0]["event_id"] == "after_now"
    assert selected[0]["selection_reason"] == "post_now_preferred"


def test_select_daily_games_ranks_by_coverage_then_pinnacle_then_total_then_time():
    now = datetime(2026, 3, 26, 21, 0, 0, tzinfo=timezone.utc)  # before drop
    g_low_coverage = _game("g1", "2026-03-27T02:00:00Z", offers=2)
    g_high_coverage_low_total = _game("g2", "2026-03-27T02:00:00Z", offers=5)
    g_high_coverage_high_total = _game("g3", "2026-03-27T02:00:00Z", offers=5)
    # bump total value for g3
    for offer in g_high_coverage_high_total["totals_offers"]:
        offer["total"] = 244.5
    selected = _select_daily_games([g_low_coverage, g_high_coverage_low_total, g_high_coverage_high_total], max_games=3, now=now)
    assert [g["event_id"] for g in selected[:2]] == ["g3", "g2"]


def test_daily_board_selection_does_not_import_espn_modules():
    # Guard: daily_board should not depend on ESPN scoreboard/TV curation.
    sys.modules.pop("services.daily_board", None)
    mod = importlib.import_module("services.daily_board")
    src = getattr(mod, "__file__", "") or ""
    assert "daily_board.py" in src
    with open(src, "r", encoding="utf-8") as f:
        contents = f.read()
    assert "espn_scoreboard" not in contents


@pytest.mark.asyncio
async def test_run_daily_board_drop_limits_game_lines_to_nba_and_mlb(monkeypatch):
    import services.daily_board as daily_board
    import services.odds_api as odds_api
    import services.player_props as player_props
    import services.scan_markets as scan_markets

    featured_calls: list[str] = []
    game_line_scan_calls: list[tuple[str, str]] = []
    manual_scan_supported_sports: list[list[str]] = []

    async def _fake_fetch_featured_lines_slate(*, sport: str, source: str):
        featured_calls.append(sport)
        if sport == "basketball_nba":
            games = [_game("nba-1", "2026-05-27T02:00:00Z", offers=3)]
        else:
            games = [_game("mlb-1", "2026-05-27T19:00:00Z", offers=2)]
        return {
            "sport": sport,
            "games": games,
            "events_fetched": len(games),
            "api_requests_remaining": "95",
        }

    prop_event_sources: list[tuple[str, str]] = []
    prop_scan_calls: list[tuple[str, list[str], list[str], str]] = []

    async def _fake_fetch_events(sport: str, source: str):
        prop_event_sources.append((sport, source))
        assert source == f"scheduled_board_drop_{sport}_props_events"
        event_id = "evt-nba-1" if sport == "basketball_nba" else "evt-mlb-1"
        return ([{"id": event_id}], types.SimpleNamespace(headers={"x-requests-remaining": "94"}))

    async def _fake_get_cached_or_scan(sport: str, source: str = "unknown"):
        game_line_scan_calls.append((sport, source))
        return {
            "sides": [{"sport": sport, "event": f"{sport} matchup"}],
            "events_fetched": 1,
            "events_with_both_books": 1,
            "api_requests_remaining": "93",
            "fetched_at": 1_700_000_000.0,
        }

    async def _fake_scan_player_props_for_event_ids(*, sport: str, event_ids: list[str], markets: list[str], source: str):
        prop_scan_calls.append((sport, list(event_ids), list(markets), source))
        expected_event_ids = ["evt-nba-1"] if sport == "basketball_nba" else ["evt-mlb-1"]
        assert event_ids == expected_event_ids
        assert source == "scheduled_board_drop"
        return {
            "sides": [{"sport": sport, "player_name": "Example Player", "market": markets[0]}],
            "events_fetched": 1,
            "events_with_both_books": 1,
            "api_requests_remaining": "92",
            "scanned_at": "2026-03-27T00:00:00Z",
        }

    def _fake_manual_scan_sports_for_env(*, environment: str, supported_sports: list[str]) -> list[str]:
        manual_scan_supported_sports.append(list(supported_sports))
        return list(supported_sports)

    monkeypatch.setattr(odds_api, "fetch_featured_lines_slate", _fake_fetch_featured_lines_slate, raising=True)
    monkeypatch.setattr(odds_api, "fetch_events", _fake_fetch_events, raising=True)
    monkeypatch.setattr(odds_api, "get_cached_or_scan", _fake_get_cached_or_scan, raising=True)
    monkeypatch.setattr(player_props, "scan_player_props_for_event_ids", _fake_scan_player_props_for_event_ids, raising=True)
    monkeypatch.setattr(
        scan_markets,
        "manual_scan_sports_for_env",
        _fake_manual_scan_sports_for_env,
        raising=True,
    )

    result = await daily_board.run_daily_board_drop(
        db=None,
        source="scheduled_board_drop",
        scan_label="Final Board / Bet Placement Scan",
        mst_anchor_time="15:00",
        retry_supabase=lambda fn: fn(),
        log_event=lambda *_args, **_kwargs: None,
    )

    assert featured_calls == ["basketball_nba", "baseball_mlb"]
    assert manual_scan_supported_sports == [["basketball_nba", "baseball_mlb"]]
    assert prop_event_sources == [
        ("basketball_nba", "scheduled_board_drop_basketball_nba_props_events"),
        ("baseball_mlb", "scheduled_board_drop_baseball_mlb_props_events"),
    ]
    assert game_line_scan_calls == [
        ("basketball_nba", "scheduled_board_drop"),
        ("baseball_mlb", "scheduled_board_drop"),
    ]
    assert [call[0] for call in prop_scan_calls] == ["basketball_nba", "baseball_mlb"]
    assert result["game_line_sports_scanned"] == ["basketball_nba", "baseball_mlb"]
    assert result["featured_games_count"] == 2
    assert result["summary"]["game_lines"]["sports_scanned"] == ["basketball_nba", "baseball_mlb"]
    assert result["summary"]["player_props"]["events_scanned"] == 2
    assert result["summary"]["player_props"]["board_items"]["browse_total"] == 2

