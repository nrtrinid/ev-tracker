import pytest
from fastapi import HTTPException

from .test_utils import ensure_supabase_stub

ensure_supabase_stub()

from routes.board_routes import (
    get_board_latest_player_prop_detail,
    get_board_latest_player_props_opportunities,
)


def test_get_board_latest_player_props_opportunities_filters_pages_and_annotates(monkeypatch):
    def _fake_load_filtered_page(*, db, retry_supabase, view, page, page_size, filter_item):
        assert view == "opportunities"
        assert page == 1
        assert page_size == 1
        sample = {
            "surface": "player_props",
            "event_id": "evt-1",
            "market_key": "player_points",
            "selection_key": "sel-1",
            "sportsbook": "DraftKings",
            "sport": "basketball_nba",
            "event": "Lakers @ Suns",
            "event_short": "LAL @ PHX",
            "commence_time": "2099-04-02T02:00:00Z",
            "market": "player_points",
            "player_name": "Devin Booker",
            "selection_side": "over",
            "display_name": "Devin Booker Over 24.5",
            "reference_odds": -105,
            "reference_source": "consensus",
            "reference_bookmaker_count": 3,
            "confidence_label": "high",
            "book_odds": 110,
            "true_prob": 0.55,
            "base_kelly_fraction": 0.03,
            "book_decimal": 2.1,
            "ev_percentage": 7.5,
        }
        assert filter_item(sample) is True
        return (
            {
                "scanned_at": "2026-04-02T00:00:00Z",
                "available_books": ["DraftKings", "FanDuel"],
                "available_markets": ["player_points"],
            },
            [sample],
            1,
            2,
            False,
        )

    monkeypatch.setattr("routes.board_routes.get_db", lambda: object())
    monkeypatch.setattr("routes.board_routes.load_player_prop_board_filtered_page", _fake_load_filtered_page)
    monkeypatch.setattr(
        "routes.board_routes.annotate_sides_with_duplicate_state",
        lambda _db, _user_id, sides: [{**side, "scanner_duplicate_state": "better_now"} for side in sides],
    )

    out = get_board_latest_player_props_opportunities(
        page=1,
        page_size=1,
        books="DraftKings",
        time_filter="all_games",
        market="player_points",
        search="Booker",
        tz_offset_minutes=420,
        user={"id": "user-1"},
    )

    assert out is not None
    assert out["source_total"] == 2
    assert out["total"] == 1
    assert out["has_more"] is False
    assert out["items"][0]["sportsbook"] == "DraftKings"
    assert out["items"][0]["scanner_duplicate_state"] == "better_now"


def test_get_board_latest_player_prop_detail_raises_404_when_missing(monkeypatch):
    monkeypatch.setattr("routes.board_routes.get_db", lambda: object())
    monkeypatch.setattr("routes.board_routes.load_player_prop_board_detail", lambda **_kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        get_board_latest_player_prop_detail(
            selection_key="missing",
            sportsbook="DraftKings",
            user={"id": "user-1"},
        )

    assert exc_info.value.status_code == 404
