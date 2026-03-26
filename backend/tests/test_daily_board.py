from datetime import datetime, timezone
import importlib
import sys

from services.daily_board import _select_daily_games


def _game(event_id: str, commence_time: str, offers: int = 2) -> dict:
    return {
        "event_id": event_id,
        "event": "Away @ Home",
        "commence_time": commence_time,
        "totals_offers": [{"sportsbook": "Pinnacle", "total": 220.5, "over_odds": -110, "under_odds": -110}] * offers,
    }


def test_select_daily_games_prefers_after_drop_when_before_drop():
    # Before 3:30 PM Phoenix on 2026-03-26.
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
    # After 3:30 PM Phoenix on 2026-03-26.
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

