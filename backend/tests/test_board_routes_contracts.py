import pytest

from .test_utils import ensure_supabase_stub

ensure_supabase_stub()

import routes.board_routes as board_routes


def _runtime_hooks(*, sync_calls=None, status_updates=None, persisted_runs=None):
    sync_calls = sync_calls if sync_calls is not None else []
    status_updates = status_updates if status_updates is not None else []
    persisted_runs = persisted_runs if persisted_runs is not None else []

    def _log_event(*_args, **_kwargs):
        return None

    def _sync_pickem(payload, source):
        sync_calls.append({"payload": payload, "source": source})

    def _set_ops_status(key, payload):
        status_updates.append({"key": key, "payload": payload})

    def _persist_ops_job_run(**kwargs):
        persisted_runs.append(kwargs)

    return _log_event, "boot-test", _sync_pickem, _set_ops_status, _persist_ops_job_run


def _board_snapshot(*, game_context=None, meta=None):
    return {
        "meta": meta
        or {
            "snapshot_id": "snap-1",
            "snapshot_type": "scheduled",
            "scanned_at": "2026-04-22T09:30:00Z",
            "surfaces_included": ["straight_bets", "player_props"],
            "sports_included": ["basketball_nba", "baseball_mlb"],
            "next_scheduled_drop": "2026-04-22T15:00:00Z",
            "events_scanned": 8,
            "total_sides": 42,
        },
        "game_context": game_context,
        "straight_bets": None,
        "player_props": None,
    }


def _straight_side(**overrides):
    side = {
        "surface": "straight_bets",
        "event_id": "evt-1",
        "market_key": "h2h",
        "selection_key": "evt-1|h2h|lakers",
        "sportsbook": "DraftKings",
        "sport": "basketball_nba",
        "event": "Lakers @ Warriors",
        "commence_time": "2026-04-22T19:00:00Z",
        "team": "Lakers",
        "selection_side": "home",
        "pinnacle_odds": 105,
        "book_odds": 118,
        "true_prob": 0.51,
        "base_kelly_fraction": 0.02,
        "book_decimal": 2.18,
        "ev_percentage": 2.1,
    }
    side.update(overrides)
    return side


def _player_prop_side(**overrides):
    side = {
        "surface": "player_props",
        "event_id": "evt-pp-1",
        "market_key": "player_points",
        "selection_key": "evt-pp-1|player_points|booker|over|24.5",
        "sportsbook": "DraftKings",
        "sport": "basketball_nba",
        "event": "Lakers @ Suns",
        "commence_time": "2026-04-22T19:00:00Z",
        "market": "player_points",
        "player_name": "Devin Booker",
        "team": "Phoenix Suns",
        "opponent": "Los Angeles Lakers",
        "selection_side": "over",
        "line_value": 24.5,
        "display_name": "Devin Booker Over 24.5",
        "reference_odds": -105,
        "reference_source": "consensus",
        "reference_bookmakers": ["DraftKings", "FanDuel"],
        "reference_bookmaker_count": 2,
        "confidence_label": "high",
        "book_odds": 110,
        "true_prob": 0.55,
        "base_kelly_fraction": 0.03,
        "book_decimal": 2.1,
        "ev_percentage": 7.5,
    }
    side.update(overrides)
    return side


def _player_prop_diagnostics():
    return {
        "scan_mode": "manual_refresh",
        "scan_scope": "all_supported_sports",
        "scoreboard_event_count": 3,
        "odds_event_count": 4,
        "curated_games": [
            {
                "event_id": "evt-pp-1",
                "away_team": "Los Angeles Lakers",
                "home_team": "Phoenix Suns",
                "selection_reason": "nba_tv",
                "broadcasts": ["ESPN"],
                "odds_event_id": "odds-1",
                "commence_time": "2026-04-22T19:00:00Z",
                "matched": True,
            }
        ],
        "matched_event_count": 1,
        "unmatched_game_count": 0,
        "fallback_reason": None,
        "fallback_event_count": 0,
        "events_fetched": 4,
        "events_skipped_pregame": 0,
        "events_with_provider_markets": 2,
        "events_with_supported_book_markets": 2,
        "events_provider_only": 0,
        "events_with_results": 2,
        "candidate_sides_count": 2,
        "quality_gate_filtered_count": 0,
        "quality_gate_min_reference_bookmakers": 2,
        "pickem_quality_gate_min_reference_bookmakers": 2,
        "sides_count": 1,
        "markets_requested": ["player_points"],
        "provider_market_event_counts": {"player_points": 2},
        "supported_book_market_event_counts": {"player_points": 2},
        "sports_scanned": ["basketball_nba"],
        "by_sport": {"basketball_nba": {"events_fetched": 4}},
        "prizepicks_status": "ok",
        "prizepicks_message": None,
        "prizepicks_board_items_count": 1,
        "prizepicks_exact_line_matches_count": 1,
        "prizepicks_unmatched_count": 0,
        "prizepicks_filtered_count": 0,
    }


def _prizepicks_card():
    return {
        "comparison_key": "evt-pp-1|player_points|booker|24.5",
        "event_id": "evt-pp-1",
        "sport": "basketball_nba",
        "event": "Lakers @ Suns",
        "commence_time": "2026-04-22T19:00:00Z",
        "player_name": "Devin Booker",
        "participant_id": "p-1",
        "team": "Phoenix Suns",
        "opponent": "Los Angeles Lakers",
        "market_key": "player_points",
        "market": "player_points",
        "prizepicks_line": 24.5,
        "exact_line_bookmakers": ["DraftKings", "FanDuel"],
        "exact_line_bookmaker_count": 2,
        "consensus_over_prob": 0.56,
        "consensus_under_prob": 0.44,
        "consensus_side": "over",
        "confidence_label": "high",
        "best_over_sportsbook": "DraftKings",
        "best_over_odds": 110,
        "best_under_sportsbook": "FanDuel",
        "best_under_odds": -118,
    }


def test_board_latest_hardcoded_minimal_contract(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "hardcoded_minimal")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["snapshot_id"] == "hardcoded_minimal"
    assert body["meta"]["snapshot_type"] == "manual"
    assert body["meta"]["degraded"] is True
    assert body["game_context"] is None
    assert body["straight_bets"] is None
    assert body["player_props"] is None


def test_board_latest_meta_only_contract(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "meta_only")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "load_board_snapshot",
        lambda **_kwargs: _board_snapshot(game_context={"scan_label": "Morning", "unexpected": "kept_in_cache"}),
    )

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["snapshot_id"] == "snap-1"
    assert body["game_context"] is None
    assert body["straight_bets"] is None
    assert body["player_props"] is None


def test_board_latest_minimal_game_context_marks_degraded_when_keys_trimmed(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "minimal_game_context")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "load_board_snapshot",
        lambda **_kwargs: _board_snapshot(
            game_context={
                "scan_label": "Morning Drop",
                "scan_anchor_time_mst": "09:30",
                "featured_lines_meta": {"games": 3},
                "captured_at": "2026-04-22T09:31:00Z",
                "unexpected_branch": {"drop_me": True},
            }
        ),
    )

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["degraded"] is True
    assert body["game_context"] == {
        "scan_label": "Morning Drop",
        "scan_anchor_time_mst": "09:30",
        "featured_lines_meta": {"games": 3},
        "captured_at": "2026-04-22T09:31:00Z",
    }
    assert body["straight_bets"] is None
    assert body["player_props"] is None


def test_board_latest_invalid_mode_falls_back_to_full_contract(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "not-a-real-mode")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "load_board_snapshot",
        lambda **_kwargs: _board_snapshot(game_context={"scan_label": "Morning", "unexpected": "preserved"}),
    )

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["game_context"] == {"scan_label": "Morning", "unexpected": "preserved"}
    assert body["straight_bets"] is None
    assert body["player_props"] is None


@pytest.mark.parametrize("raw_snapshot", [None, "not-a-dict"])
def test_board_latest_missing_or_malformed_snapshot_returns_empty_sentinel(auth_client, monkeypatch, raw_snapshot):
    monkeypatch.setenv("BOARD_LATEST_MODE", "full")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(board_routes, "load_board_snapshot", lambda **_kwargs: raw_snapshot)

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["snapshot_id"] == "none"
    assert body["meta"]["snapshot_type"] == "scheduled"
    assert body["game_context"] is None
    assert body["straight_bets"] is None
    assert body["player_props"] is None


def test_board_latest_db_init_failure_returns_controlled_502(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "full")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 502
    assert resp.json()["error"] == "board_db_init_failed"


def test_board_latest_load_failure_returns_controlled_502(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "full")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "load_board_snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("load failed")),
    )

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 502
    assert resp.json()["error"] == "board_load_failed"


def test_board_latest_memory_error_returns_controlled_503(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "full")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(board_routes, "load_board_snapshot", lambda **_kwargs: _board_snapshot(game_context={"scan_label": "Drop"}))
    monkeypatch.setattr(
        board_routes,
        "jsonable_encoder",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("too large")),
    )

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 503
    assert resp.json()["error"] == "board_too_large"


def test_board_latest_unexpected_runtime_error_degrades_to_empty_200(auth_client, monkeypatch):
    monkeypatch.setenv("BOARD_LATEST_MODE", "full")
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(board_routes, "load_board_snapshot", lambda **_kwargs: _board_snapshot(game_context={"scan_label": "Drop"}))

    original_encoder = board_routes.jsonable_encoder
    calls = {"count": 0}

    def _flaky_encoder(value):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("bad payload")
        return original_encoder(value)

    monkeypatch.setattr(board_routes, "jsonable_encoder", _flaky_encoder)

    resp = auth_client.get("/api/board/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["snapshot_id"] == "none"
    assert body["meta"]["degraded"] is True
    assert body["game_context"] is None
    assert body["straight_bets"] is None
    assert body["player_props"] is None


def test_board_latest_surface_straight_bets_success_contract(auth_client, monkeypatch):
    payload = {
        "surface": "straight_bets",
        "sport": "basketball_nba",
        "sides": [_straight_side()],
        "events_fetched": 3,
        "events_with_both_books": 2,
        "api_requests_remaining": "490",
        "scanned_at": "2026-04-22T09:30:00Z",
    }

    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr("services.scan_cache.load_latest_scan_payload", lambda **_kwargs: payload)

    resp = auth_client.get("/api/board/latest/surface?surface=straight_bets")

    assert resp.status_code == 200
    body = resp.json()
    assert body["surface"] == "straight_bets"
    assert body["events_fetched"] == 3
    assert body["events_with_both_books"] == 2
    assert body["api_requests_remaining"] == "490"
    assert body["sides"][0]["team"] == "Lakers"
    assert body["sides"][0].get("scanner_duplicate_state") is None


def test_board_latest_surface_player_props_success_reannotates_duplicates(auth_client, monkeypatch):
    payload = {
        "surface": "player_props",
        "sport": "basketball_nba",
        "sides": [_player_prop_side()],
        "events_fetched": 2,
        "events_with_both_books": 1,
        "api_requests_remaining": "88",
        "scanned_at": "2026-04-22T09:30:00Z",
    }
    captured = {}

    def _annotate(db, user_id, sides):
        captured["user_id"] = user_id
        captured["sides"] = sides
        return [{**side, "scanner_duplicate_state": "already_logged"} for side in sides]

    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(board_routes, "load_player_prop_board_legacy_surface", lambda **_kwargs: payload)
    monkeypatch.setattr(board_routes, "annotate_sides_with_duplicate_state", _annotate)

    resp = auth_client.get("/api/board/latest/surface?surface=player_props")

    assert resp.status_code == 200
    body = resp.json()
    assert captured["user_id"]
    assert captured["sides"][0]["selection_key"] == payload["sides"][0]["selection_key"]
    assert body["surface"] == "player_props"
    assert body["sides"][0]["scanner_duplicate_state"] == "already_logged"


def test_board_latest_surface_missing_payload_returns_null(auth_client, monkeypatch):
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr("services.scan_cache.load_latest_scan_payload", lambda **_kwargs: None)

    resp = auth_client.get("/api/board/latest/surface?surface=straight_bets")

    assert resp.status_code == 200
    assert resp.json() is None


def test_board_latest_surface_invalid_surface_returns_400(auth_client, monkeypatch):
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())

    resp = auth_client.get("/api/board/latest/surface?surface=not_real")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "surface must be straight_bets or player_props"


def test_board_latest_surface_load_failure_returns_502(auth_client, monkeypatch):
    monkeypatch.setattr(board_routes, "_resolve_main_runtime_hooks", lambda: _runtime_hooks())
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        "services.scan_cache.load_latest_scan_payload",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resp = auth_client.get("/api/board/latest/surface?surface=straight_bets")

    assert resp.status_code == 502
    assert resp.json()["detail"] == "Failed to load board surface payload"


def test_board_refresh_rate_limit_returns_429(auth_client, monkeypatch):
    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: False)

    resp = auth_client.post("/api/board/refresh?scope=player_props")

    assert resp.status_code == 429
    assert "Too many refresh requests" in resp.json()["detail"]


def test_board_refresh_invalid_scope_returns_400(auth_client, monkeypatch):
    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: True)

    resp = auth_client.post("/api/board/refresh?scope=not_real")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "scope must be straight_bets or player_props"


def test_board_refresh_db_init_failure_returns_502(auth_client, monkeypatch):
    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: True)
    monkeypatch.setattr(board_routes, "get_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))

    resp = auth_client.post("/api/board/refresh?scope=player_props")

    assert resp.status_code == 502
    assert "Failed to initialize database client" in resp.json()["detail"]


def test_board_refresh_execution_failure_records_failed_ops_status(auth_client, monkeypatch):
    status_updates = []
    persisted_runs = []

    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: True)
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "_resolve_main_runtime_hooks",
        lambda: _runtime_hooks(status_updates=status_updates, persisted_runs=persisted_runs),
    )
    async def _raise_refresh(**_kwargs):
        raise RuntimeError("manual_refresh exploded")

    monkeypatch.setattr(board_routes, "_refresh_player_props_result", _raise_refresh)

    resp = auth_client.post("/api/board/refresh?scope=player_props")

    assert resp.status_code == 502
    assert "Refresh failed" in resp.json()["detail"]
    assert status_updates[0]["key"] == "last_board_refresh"
    assert status_updates[0]["payload"]["kind"] == "scoped_refresh"
    assert status_updates[0]["payload"]["status"] == "failed"
    assert persisted_runs[0]["job_kind"] == "board_scoped_refresh"
    assert persisted_runs[0]["meta"]["response_status_code"] == 502


def test_board_refresh_invalid_refresh_payload_returns_500(auth_client, monkeypatch):
    status_updates = []
    persisted_runs = []

    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: True)
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "_resolve_main_runtime_hooks",
        lambda: _runtime_hooks(status_updates=status_updates, persisted_runs=persisted_runs),
    )
    async def _invalid_refresh(**_kwargs):
        return {
            "surface": "player_props",
            "sport": "basketball_nba",
            "sides": [_player_prop_side()],
            "events_fetched": 2,
            "events_with_both_books": 1,
            "api_requests_remaining": "88",
            "scanned_at": "2026-04-22T09:30:00Z",
            "diagnostics": {"scan_mode": "manual_refresh"},
        }

    monkeypatch.setattr(board_routes, "_refresh_player_props_result", _invalid_refresh)

    resp = auth_client.post("/api/board/refresh?scope=player_props")

    assert resp.status_code == 500
    assert "Failed to build response" in resp.json()["detail"]
    assert status_updates[0]["payload"]["status"] == "failed"
    assert persisted_runs[0]["meta"]["response_status_code"] == 500


def test_board_refresh_straight_bets_success_merges_supported_sports(auth_client, monkeypatch):
    sync_calls = []
    status_updates = []
    persisted_runs = []
    persist_calls = []
    scan_calls = []

    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: True)
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "_resolve_main_runtime_hooks",
        lambda: _runtime_hooks(
            sync_calls=sync_calls,
            status_updates=status_updates,
            persisted_runs=persisted_runs,
        ),
    )

    import services.odds_api as odds_api

    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ("basketball_nba", "baseball_mlb"), raising=True)

    async def _cached_or_scan(sport_key, source="manual_refresh"):
        scan_calls.append({"sport_key": sport_key, "source": source})
        if sport_key == "basketball_nba":
            return {
                "sides": [_straight_side(sport="basketball_nba", selection_key="evt-1|h2h|lakers")],
                "events_fetched": 2,
                "events_with_both_books": 1,
                "api_requests_remaining": "88",
                "scanned_at": "2026-04-22T09:30:00Z",
            }
        return {
            "sides": [_straight_side(sport="baseball_mlb", selection_key="evt-2|h2h|dbacks", team="D-backs")],
            "events_fetched": 3,
            "events_with_both_books": 2,
            "api_requests_remaining": "77",
            "scanned_at": "2026-04-22T09:31:00Z",
        }

    monkeypatch.setattr(odds_api, "get_cached_or_scan", _cached_or_scan, raising=True)

    def _persist_scoped_refresh(**kwargs):
        persist_calls.append(kwargs)
        return "2026-04-22T09:32:00Z"

    monkeypatch.setattr(board_routes, "persist_scoped_refresh", _persist_scoped_refresh)

    resp = auth_client.post("/api/board/refresh?scope=straight_bets")

    assert resp.status_code == 200
    body = resp.json()
    assert body["surface"] == "straight_bets"
    assert body["refreshed_at"] == "2026-04-22T09:32:00Z"
    assert body["data"]["surface"] == "straight_bets"
    assert body["data"]["sport"] == "all"
    assert body["data"]["events_fetched"] == 5
    assert body["data"]["events_with_both_books"] == 3
    assert body["data"]["api_requests_remaining"] == "77"
    assert [call["sport_key"] for call in scan_calls] == ["basketball_nba", "baseball_mlb"]
    assert all(call["source"] == "manual_refresh" for call in scan_calls)
    assert sync_calls == []
    assert status_updates[0]["payload"]["kind"] == "scoped_refresh"
    assert status_updates[0]["payload"]["surface"] == "straight_bets"
    assert status_updates[0]["payload"]["canonical_board_updated"] is False
    assert status_updates[0]["payload"]["result"]["scan_label"] == "Manual Game Lines Refresh"
    assert status_updates[0]["payload"]["result"]["straight_sides"] == 2
    assert status_updates[0]["payload"]["result"]["game_line_sports_scanned"] == [
        "baseball_mlb",
        "basketball_nba",
    ]
    assert persisted_runs[0]["job_kind"] == "board_scoped_refresh"
    assert persisted_runs[0]["surface"] == "straight_bets"
    assert persisted_runs[0]["total_sides"] == 2
    assert persisted_runs[0]["meta"]["canonical_board_updated"] is False
    assert persist_calls[0]["surface"] == "straight_bets"
    assert persist_calls[0]["scan_payload"]["surface"] == "straight_bets"


def test_board_refresh_player_props_success_returns_optional_fields_and_syncs_when_fresh(auth_client, monkeypatch):
    sync_calls = []
    status_updates = []
    persisted_runs = []
    persist_calls = []

    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: True)
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "_resolve_main_runtime_hooks",
        lambda: _runtime_hooks(
            sync_calls=sync_calls,
            status_updates=status_updates,
            persisted_runs=persisted_runs,
        ),
    )
    async def _successful_refresh(**_kwargs):
        return {
            "surface": "player_props",
            "sport": "basketball_nba",
            "sides": [_player_prop_side()],
            "events_fetched": 2,
            "events_with_both_books": 1,
            "api_requests_remaining": "88",
            "scanned_at": "2026-04-22T09:30:00Z",
            "diagnostics": _player_prop_diagnostics(),
            "prizepicks_cards": [_prizepicks_card()],
            "cache_hit": False,
        }

    monkeypatch.setattr(board_routes, "_refresh_player_props_result", _successful_refresh)

    def _persist_scoped_refresh(**kwargs):
        persist_calls.append(kwargs)
        return "2026-04-22T09:31:00Z"

    monkeypatch.setattr(board_routes, "persist_scoped_refresh", _persist_scoped_refresh)

    resp = auth_client.post("/api/board/refresh?scope=player_props")

    assert resp.status_code == 200
    body = resp.json()
    assert body["surface"] == "player_props"
    assert body["refreshed_at"] == "2026-04-22T09:31:00Z"
    assert body["data"]["diagnostics"]["scan_mode"] == "manual_refresh"
    assert body["data"]["prizepicks_cards"][0]["comparison_key"] == "evt-pp-1|player_points|booker|24.5"
    assert len(sync_calls) == 1
    assert sync_calls[0]["source"] == "manual_refresh"
    assert status_updates[0]["payload"]["kind"] == "scoped_refresh"
    assert status_updates[0]["payload"]["status"] == "completed"
    assert status_updates[0]["payload"]["canonical_board_updated"] is False
    assert persisted_runs[0]["job_kind"] == "board_scoped_refresh"
    assert persisted_runs[0]["meta"]["canonical_board_updated"] is False
    assert persist_calls[0]["surface"] == "player_props"
    assert persist_calls[0]["scan_payload"]["surface"] == "player_props"


def test_board_refresh_player_props_cache_hit_skips_pickem_sync(auth_client, monkeypatch):
    sync_calls = []
    status_updates = []
    persisted_runs = []

    monkeypatch.setattr("services.shared_state.allow_fixed_window_rate_limit", lambda **_kwargs: True)
    monkeypatch.setattr(board_routes, "get_db", lambda: object())
    monkeypatch.setattr(
        board_routes,
        "_resolve_main_runtime_hooks",
        lambda: _runtime_hooks(
            sync_calls=sync_calls,
            status_updates=status_updates,
            persisted_runs=persisted_runs,
        ),
    )
    async def _cached_refresh(**_kwargs):
        return {
            "surface": "player_props",
            "sport": "basketball_nba",
            "sides": [_player_prop_side()],
            "events_fetched": 2,
            "events_with_both_books": 1,
            "api_requests_remaining": "88",
            "scanned_at": "2026-04-22T09:30:00Z",
            "diagnostics": _player_prop_diagnostics(),
            "prizepicks_cards": [_prizepicks_card()],
            "cache_hit": True,
        }

    monkeypatch.setattr(board_routes, "_refresh_player_props_result", _cached_refresh)
    monkeypatch.setattr(board_routes, "persist_scoped_refresh", lambda **_kwargs: "2026-04-22T09:31:00Z")

    resp = auth_client.post("/api/board/refresh?scope=player_props")

    assert resp.status_code == 200
    assert sync_calls == []
    assert status_updates[0]["payload"]["status"] == "completed"
    assert persisted_runs[0]["status"] == "completed"
