from services.player_prop_board import (
    BOARD_VIEW_OPPORTUNITIES,
    build_player_prop_board_detail_key,
    build_player_prop_board_item,
    build_player_prop_board_pickem_cards,
    filter_player_prop_board_items,
    filter_player_prop_board_pickem_items,
    load_player_prop_board_filtered_page,
    load_player_prop_board_artifact,
    load_player_prop_board_detail,
    matches_board_time_filter,
    paginate_board_items,
    persist_player_prop_board_artifacts,
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store):
        self._store = store
        self._selected_key = None

    def upsert(self, payload, on_conflict=None):
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            self._store[row["key"]] = row
        return self

    def select(self, _fields):
        return self

    def eq(self, field, value):
        if field == "key":
            self._selected_key = value
        return self

    def limit(self, _value):
        return self

    def execute(self):
        if self._selected_key is None:
            return {"ok": True}
        row = self._store.get(self._selected_key)
        return _Result([row] if row is not None else [])


class _DB:
    def __init__(self):
        self.store = {}
        self.query = _Query(self.store)

    def table(self, name):
        assert name == "global_scan_cache"
        return self.query


def _prop_side(
    *,
    sportsbook: str = "DraftKings",
    side: str = "over",
    line_value: float = 24.5,
    event_id: str = "evt-1",
    event: str = "Lakers @ Suns",
    event_short: str = "LAL @ PHX",
    book_odds: float = 110,
    true_prob: float = 0.55,
    ev_percentage: float = 6.5,
    sport: str = "basketball_nba",
    market_key: str = "player_points",
) -> dict:
    return {
        "surface": "player_props",
        "event_id": event_id,
        "market_key": market_key,
        "selection_key": f"{event_id}|{market_key}|devinbooker|{side}|{line_value}",
        "sportsbook": sportsbook,
        "sportsbook_deeplink_url": f"https://example.com/{sportsbook.lower()}",
        "sportsbook_deeplink_level": "selection",
        "sport": sport,
        "event": event,
        "event_short": event_short,
        "commence_time": "2026-04-02T02:00:00Z",
        "market": market_key,
        "player_name": "Devin Booker",
        "participant_id": "p-1",
        "team": "Phoenix Suns",
        "team_short": "PHX",
        "opponent": "Los Angeles Lakers",
        "opponent_short": "LAL",
        "selection_side": side,
        "line_value": line_value,
        "display_name": f"Devin Booker {side.title()} {line_value}",
        "reference_odds": -105,
        "reference_source": "consensus",
        "reference_bookmakers": ["DraftKings", "FanDuel", "BetMGM"],
        "reference_bookmaker_count": 3,
        "confidence_label": "high",
        "confidence_score": 0.84,
        "prob_std": 0.02,
        "book_odds": book_odds,
        "true_prob": true_prob,
        "base_kelly_fraction": 0.03,
        "book_decimal": 2.1,
        "ev_percentage": ev_percentage,
        "active_model_key": "props_v2",
        "shadow_model_key": "props_v1",
        "interpolation_mode": "exact",
        "reference_inputs_json": {"books": 3},
        "model_evaluations": [{"model_key": "props_v2"}],
    }


def test_build_player_prop_board_item_strips_heavy_fields():
    item = build_player_prop_board_item(_prop_side())

    assert item["selection_key"]
    assert item["reference_bookmaker_count"] == 3
    assert "reference_bookmakers" not in item
    assert "reference_inputs_json" not in item
    assert "model_evaluations" not in item
    assert "active_model_key" not in item
    assert "confidence_score" not in item
    assert "prob_std" not in item


def test_build_player_prop_board_pickem_cards_groups_exact_line_pairs():
    items = [
        build_player_prop_board_item(_prop_side(sportsbook="DraftKings", side="over", book_odds=105, true_prob=0.56)),
        build_player_prop_board_item(_prop_side(sportsbook="DraftKings", side="under", book_odds=-115, true_prob=0.44)),
        build_player_prop_board_item(_prop_side(sportsbook="FanDuel", side="over", book_odds=110, true_prob=0.58)),
        build_player_prop_board_item(_prop_side(sportsbook="FanDuel", side="under", book_odds=-120, true_prob=0.42)),
    ]

    cards = build_player_prop_board_pickem_cards(items)

    assert len(cards) == 1
    card = cards[0]
    assert card["comparison_key"] == "evt-1|player_points|devinbooker|24.5"
    assert card["exact_line_bookmaker_count"] == 2
    assert card["consensus_side"] == "over"
    assert card["best_over_sportsbook"] == "FanDuel"


def test_persist_and_load_player_prop_board_artifacts():
    db = _DB()
    payload = {
        "surface": "player_props",
        "sport": "basketball_nba",
        "sides": [
            _prop_side(sportsbook="DraftKings", side="over", ev_percentage=7.0),
            _prop_side(sportsbook="DraftKings", side="under", ev_percentage=1.5),
            _prop_side(sportsbook="FanDuel", side="over", ev_percentage=5.0),
            _prop_side(sportsbook="FanDuel", side="under", ev_percentage=0.8),
        ],
        "events_fetched": 4,
        "events_with_both_books": 4,
        "api_requests_remaining": "88",
        "scanned_at": "2026-04-02T00:00:00Z",
    }

    summary = persist_player_prop_board_artifacts(
        db=db,
        payload=payload,
        retry_supabase=lambda fn: fn(),
        log_event=lambda *_args, **_kwargs: None,
        chunk_size=2,
        legacy_max_items=1,
    )

    assert summary["opportunities_total"] == 3
    assert summary["pickem_total"] == 1
    assert f"player_props:board_opportunities_meta" in db.store
    assert f"player_props:board_opportunities_chunk_1" in db.store
    assert f"player_props:board_detail_lookup" not in db.store
    assert any(key.startswith("player_props:board_detail_") for key in db.store)
    assert f"player_props:board_legacy_surface" in db.store

    meta, items = load_player_prop_board_artifact(
        db=db,
        retry_supabase=lambda fn: fn(),
        view=BOARD_VIEW_OPPORTUNITIES,
    )
    assert meta is not None
    assert meta["chunk_count"] == 2
    assert meta["available_sports"] == ["basketball_nba"]
    assert len(items) == 3
    assert items[0]["ev_percentage"] >= items[-1]["ev_percentage"]
    assert all(float(item["ev_percentage"]) > 1 for item in items)

    detail = load_player_prop_board_detail(
        db=db,
        retry_supabase=lambda fn: fn(),
        selection_key=payload["sides"][0]["selection_key"],
        sportsbook=payload["sides"][0]["sportsbook"],
    )
    assert detail is not None
    assert detail["reference_bookmakers"] == ["DraftKings", "FanDuel", "BetMGM"]


def test_persist_player_prop_board_artifacts_prefers_prebuilt_pickem_cards():
    db = _DB()
    prebuilt_pickem = [
        {
            "comparison_key": "evt-1|player_points|devinbooker|24.5",
            "event_id": "evt-1",
            "sport": "basketball_nba",
            "event": "Lakers @ Suns",
            "event_short": "LAL @ PHX",
            "commence_time": "2026-04-02T02:00:00Z",
            "player_name": "Devin Booker",
            "participant_id": "p-1",
            "team": "Phoenix Suns",
            "team_short": "PHX",
            "opponent": "Los Angeles Lakers",
            "opponent_short": "LAL",
            "market_key": "player_points",
            "market": "player_points",
            "line_value": 24.5,
            "exact_line_bookmakers": ["DraftKings", "FanDuel"],
            "exact_line_bookmaker_count": 2,
            "consensus_over_prob": 0.58,
            "consensus_under_prob": 0.42,
            "consensus_side": "over",
            "confidence_label": "solid",
            "best_over_sportsbook": "FanDuel",
            "best_over_odds": 110,
            "best_under_sportsbook": "DraftKings",
            "best_under_odds": -120,
        }
    ]
    payload = {
        "surface": "player_props",
        "sport": "basketball_nba",
        "sides": [
            _prop_side(sportsbook="DraftKings", side="over", ev_percentage=7.0),
        ],
        "pickem_cards": prebuilt_pickem,
        "events_fetched": 1,
        "events_with_both_books": 1,
        "api_requests_remaining": "88",
        "scanned_at": "2026-04-02T00:00:00Z",
    }

    summary = persist_player_prop_board_artifacts(
        db=db,
        payload=payload,
        retry_supabase=lambda fn: fn(),
        log_event=lambda *_args, **_kwargs: None,
        chunk_size=2,
        legacy_max_items=1,
    )

    assert summary["pickem_total"] == 1

    meta, items = load_player_prop_board_artifact(
        db=db,
        retry_supabase=lambda fn: fn(),
        view="pickem",
    )
    assert meta is not None
    assert len(items) == 1
    assert items[0]["comparison_key"] == prebuilt_pickem[0]["comparison_key"]


def test_filter_and_paginate_player_prop_board_items():
    items = [
        build_player_prop_board_item(_prop_side(sportsbook="DraftKings", event="Lakers @ Suns", event_short="LAL @ PHX")),
        build_player_prop_board_item(
            _prop_side(
                sportsbook="FanDuel",
                event="Warriors @ Kings",
                event_short="GSW @ SAC",
                event_id="evt-2",
                sport="baseball_mlb",
                market_key="batter_hits",
            )
        ),
    ]

    filtered = filter_player_prop_board_items(
        items,
        books=["FanDuel"],
        time_filter="all_games",
        sport="baseball_mlb",
        market="batter_hits",
        search="Kings",
    )
    assert len(filtered) == 1
    assert filtered[0]["sportsbook"] == "FanDuel"
    assert filtered[0]["sport"] == "baseball_mlb"

    market_search = filter_player_prop_board_items(
        items,
        books=["DraftKings"],
        time_filter="all_games",
        sport="basketball_nba",
        market="all",
        search="points",
    )
    assert len(market_search) == 1
    assert market_search[0]["market_key"] == "player_points"

    page, has_more = paginate_board_items(items, page=1, page_size=1)
    assert len(page) == 1
    assert has_more is True


def test_load_player_prop_board_filtered_page_reads_only_requested_slice():
    db = _DB()
    payload = {
        "surface": "player_props",
        "sport": "basketball_nba",
        "sides": [
            _prop_side(event_id=f"evt-{idx}", sportsbook="DraftKings", ev_percentage=5.0 + idx)
            for idx in range(5)
        ],
        "events_fetched": 5,
        "events_with_both_books": 5,
        "api_requests_remaining": "88",
        "scanned_at": "2026-04-02T00:00:00Z",
    }

    persist_player_prop_board_artifacts(
        db=db,
        payload=payload,
        retry_supabase=lambda fn: fn(),
        log_event=lambda *_args, **_kwargs: None,
        chunk_size=2,
        legacy_max_items=2,
    )

    meta, items, filtered_total, source_total, has_more = load_player_prop_board_filtered_page(
        db=db,
        retry_supabase=lambda fn: fn(),
        view=BOARD_VIEW_OPPORTUNITIES,
        page=2,
        page_size=2,
        filter_item=lambda item: True,
    )

    assert meta is not None
    assert source_total == 5
    assert filtered_total == 5
    assert len(items) == 2
    assert has_more is True


def test_filter_player_prop_board_pickem_items_by_books_and_search():
    cards = [
        {
            "comparison_key": "evt-1|player_points|devinbooker|24.5",
            "sport": "basketball_nba",
            "event": "Lakers @ Suns",
            "commence_time": "2026-04-02T02:00:00Z",
            "player_name": "Devin Booker",
            "market_key": "player_points",
            "market": "player_points",
            "team": "Phoenix Suns",
            "opponent": "Los Angeles Lakers",
            "best_over_sportsbook": "DraftKings",
            "best_under_sportsbook": "FanDuel",
            "exact_line_bookmakers": ["DraftKings", "FanDuel"],
        }
    ]

    filtered = filter_player_prop_board_pickem_items(
        cards,
        books=["DraftKings"],
        time_filter="all_games",
        sport="basketball_nba",
        market="player_points",
        search="Booker",
    )
    assert len(filtered) == 1


def test_persist_player_prop_board_artifacts_tracks_multiple_available_sports():
    db = _DB()
    payload = {
        "surface": "player_props",
        "sport": "all",
        "sides": [
            _prop_side(sport="basketball_nba", market_key="player_points"),
            _prop_side(
                event_id="evt-mlb-1",
                event="Dodgers @ Padres",
                event_short="LAD @ SDP",
                sport="baseball_mlb",
                market_key="batter_hits",
            ),
        ],
        "events_fetched": 2,
        "events_with_both_books": 2,
        "api_requests_remaining": "88",
        "scanned_at": "2026-04-02T00:00:00Z",
    }

    persist_player_prop_board_artifacts(
        db=db,
        payload=payload,
        retry_supabase=lambda fn: fn(),
        log_event=lambda *_args, **_kwargs: None,
        chunk_size=10,
        legacy_max_items=2,
    )

    meta, _items = load_player_prop_board_artifact(
        db=db,
        retry_supabase=lambda fn: fn(),
        view="browse",
    )

    assert meta is not None
    assert meta["available_sports"] == ["baseball_mlb", "basketball_nba"]


def test_matches_board_time_filter_supports_closed_today_with_offset():
    assert matches_board_time_filter(
        "2099-04-02T02:00:00Z",
        "all_games",
        tz_offset_minutes=420,
    ) is True
    assert build_player_prop_board_detail_key("sel-1", "DraftKings") == "sel-1::draftkings"
