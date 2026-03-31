import json
import os
import types
from pathlib import Path

import httpx
import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scan_ops_payloads"


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer dummy"}


def _load_fixture(name: str) -> dict:
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def _assert_shape_like(actual, expected, path: str = "$"):
    """Shape/type parity check; intentionally does not enforce exact value equality."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual).__name__}"
        for key, expected_value in expected.items():
            assert key in actual, f"{path}: missing key '{key}'"
            _assert_shape_like(actual[key], expected_value, f"{path}.{key}")
        return

    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual).__name__}"
        if not expected:
            return
        assert len(actual) > 0, f"{path}: expected non-empty list to validate element shape"
        _assert_shape_like(actual[0], expected[0], f"{path}[0]")
        return

    # `null` in fixture means "key must exist", not strict type/value.
    if expected is None:
        return

    # Numeric shape parity treats int/float as compatible scalar number types.
    if isinstance(expected, (int, float)):
        assert isinstance(actual, (int, float)), (
            f"{path}: expected numeric type, got {type(actual).__name__}"
        )
        return

    assert isinstance(actual, type(expected)), (
        f"{path}: expected type {type(expected).__name__}, got {type(actual).__name__}"
    )


class _FakeTable:
    def __init__(self, name: str, state: dict):
        self.name = name
        self.state = state
        self._is_select = False

    def select(self, *_args, **_kwargs):
        self._is_select = True
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def upsert(self, payload, on_conflict=None):
        self.state["last_upsert"] = {
            "table": self.name,
            "payload": payload,
            "on_conflict": on_conflict,
        }
        return self

    def execute(self):
        if self.name == "global_scan_cache" and self._is_select:
            return types.SimpleNamespace(data=self.state.get("select_data", []))
        return types.SimpleNamespace(data=[])


class _FakeDB:
    def __init__(self, state: dict):
        self.state = state

    def table(self, name: str):
        return _FakeTable(name, self.state)


@pytest.mark.integration
def test_scan_endpoints_require_auth(public_client):
    assert public_client.get("/api/scan-bets").status_code == 401
    assert public_client.get("/api/scan-markets").status_code == 401
    assert public_client.get("/api/scan-latest").status_code == 401


@pytest.mark.integration
def test_ops_endpoints_require_ops_token(public_client):
    assert public_client.get("/api/ops/status").status_code == 401
    assert public_client.get("/api/ops/research-opportunities/summary").status_code == 401
    assert public_client.get("/api/ops/model-calibration/summary").status_code == 401
    assert public_client.post("/api/ops/trigger/scan").status_code == 401
    assert public_client.post("/api/ops/trigger/auto-settle").status_code == 401
    assert public_client.post("/api/ops/trigger/test-discord").status_code == 401


@pytest.mark.integration
def test_scan_bets_contract_shape(auth_client, auth_headers, monkeypatch):
    import services.odds_api as odds_api

    async def _fake_scan_for_ev(_sport: str):
        return {
            "opportunities": [
                {
                    "sportsbook": "DraftKings",
                    "sport": "basketball_nba",
                    "event": "Lakers @ Warriors",
                    "commence_time": "2026-03-20T18:00:00Z",
                    "team": "Lakers",
                    "pinnacle_odds": 105,
                    "book_odds": 115,
                    "true_prob": 0.51,
                    "ev_percentage": 2.7,
                    "base_kelly_fraction": 0.02,
                    "book_decimal": 2.15,
                }
            ],
            "events_fetched": 4,
            "events_with_both_books": 3,
            "api_requests_remaining": "498",
        }

    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ["basketball_nba"], raising=True)
    monkeypatch.setattr(odds_api, "scan_for_ev", _fake_scan_for_ev, raising=True)

    resp = auth_client.get("/api/scan-bets", params={"sport": "basketball_nba"}, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["sport"] == "basketball_nba"
    assert isinstance(body["opportunities"], list)
    assert "events_fetched" in body
    assert "events_with_both_books" in body
    assert "api_requests_remaining" in body


@pytest.mark.integration
def test_scan_markets_contract_shape_with_duplicate_fields(auth_client, auth_headers, monkeypatch):
    import main
    import services.odds_api as odds_api

    async def _fake_get_cached_or_scan(_sport: str, source: str = "manual_scan"):
        assert source == "manual_scan"
        return {
            "sides": [
                {
                    "event_id": "evt-123",
                    "sportsbook": "DraftKings",
                    "sportsbook_deeplink_url": "https://sportsbook.example/dk/event/evt-123",
                    "sportsbook_deeplink_level": "event",
                    "sport": "basketball_nba",
                    "event": "Lakers @ Warriors",
                    "commence_time": "2026-03-20T18:00:00Z",
                    "team": "Lakers",
                    "pinnacle_odds": 110,
                    "book_odds": 120,
                    "true_prob": 0.51,
                    "base_kelly_fraction": 0.03,
                    "book_decimal": 2.2,
                    "ev_percentage": 3.2,
                    "scanner_duplicate_state": "new",
                    "best_logged_odds_american": None,
                    "current_odds_american": 120,
                    "matched_pending_bet_id": None,
                }
            ],
            "events_fetched": 12,
            "events_with_both_books": 10,
            "api_requests_remaining": "498",
            "fetched_at": 1770000000,
        }

    fake_db_state = {}
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(main, "_annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

    async def _fake_piggyback_clv(_sides):
        return None

    monkeypatch.setattr(main, "_piggyback_clv", _fake_piggyback_clv, raising=True)
    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ["basketball_nba"], raising=True)
    monkeypatch.setattr(odds_api, "get_cached_or_scan", _fake_get_cached_or_scan, raising=True)

    resp = auth_client.get("/api/scan-markets", params={"sport": "basketball_nba"}, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, _load_fixture("scan_markets_normal.json"))


@pytest.mark.integration
def test_scan_latest_empty_contract_shape(auth_client, auth_headers, monkeypatch):
    import main

    fake_db_state = {"select_data": []}
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f: f(), raising=True)

    resp = auth_client.get("/api/scan-latest", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, _load_fixture("scan_markets_empty.json"))


@pytest.mark.integration
def test_scan_latest_duplicate_state_contract_shape(auth_client, auth_headers, monkeypatch):
    import main

    payload = _load_fixture("scan_markets_duplicate_state.json")
    fake_db_state = {"select_data": [{"payload": payload}]}
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(main, "_annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

    resp = auth_client.get("/api/scan-latest", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, payload)


@pytest.mark.integration
def test_scan_markets_accepts_player_props_surface(auth_client, auth_headers, monkeypatch):
    import main
    import services.player_props as player_props

    async def _fake_get_cached_or_scan_player_props(_sport: str, source: str = "manual_scan"):
        assert source == "manual_scan"
        return {
            "surface": "player_props",
            "sides": [
                {
                    "surface": "player_props",
                    "event_id": "evt-123",
                    "market_key": "player_points",
                    "selection_key": "evt-123|player_points|nikola jokic|over:24.5",
                    "sportsbook": "FanDuel",
                    "sportsbook_deeplink_url": "https://sportsbook.example/fd/event/evt-123",
                    "sportsbook_deeplink_level": "event",
                    "sport": "basketball_nba",
                    "event": "Nuggets @ Suns",
                    "commence_time": "2026-03-20T18:00:00Z",
                    "market": "player_points",
                    "player_name": "Nikola Jokic",
                    "participant_id": None,
                    "team": "Nuggets",
                    "opponent": "Suns",
                    "selection_side": "over",
                    "line_value": 24.5,
                    "display_name": "Nikola Jokic Over 24.5",
                    "reference_odds": -108,
                    "reference_source": "market_median",
                    "reference_bookmakers": ["bovada", "betmgm"],
                    "book_odds": 105,
                    "true_prob": 0.52,
                    "base_kelly_fraction": 0.03,
                    "book_decimal": 2.05,
                    "ev_percentage": 6.6,
                    "scanner_duplicate_state": "new",
                    "best_logged_odds_american": None,
                    "current_odds_american": 105,
                    "matched_pending_bet_id": None,
                }
            ],
            "prizepicks_cards": [],
            "events_fetched": 1,
            "events_with_both_books": 1,
            "api_requests_remaining": "498",
            "fetched_at": 1770000000,
        }

    fake_db_state = {}
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(main, "_annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)
    monkeypatch.setattr(player_props, "get_cached_or_scan_player_props", _fake_get_cached_or_scan_player_props, raising=True)

    resp = auth_client.get(
        "/api/scan-markets",
        params={"surface": "player_props", "sport": "basketball_nba"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["surface"] == "player_props"
    assert body["sides"][0]["reference_odds"] == -108
    assert body["sides"][0]["reference_source"] == "market_median"
    assert body["prizepicks_cards"] == []


@pytest.mark.integration
def test_scan_latest_accepts_player_props_surface(auth_client, auth_headers, monkeypatch):
    import main

    payload = {
        "surface": "player_props",
        "sport": "basketball_nba",
        "sides": [
            {
                "surface": "player_props",
                "event_id": "evt-123",
                "market_key": "player_points",
                "selection_key": "evt-123|player_points|nikola jokic|over:24.5",
                "sportsbook": "FanDuel",
                "sportsbook_deeplink_url": "https://sportsbook.example/fd/event/evt-123",
                "sportsbook_deeplink_level": "event",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "commence_time": "2026-03-20T18:00:00Z",
                "market": "player_points",
                "player_name": "Nikola Jokic",
                "participant_id": None,
                "team": "Nuggets",
                "opponent": "Suns",
                "selection_side": "over",
                "line_value": 24.5,
                "display_name": "Nikola Jokic Over 24.5",
                "reference_odds": -108,
                "reference_source": "market_median",
                "reference_bookmakers": ["bovada", "betmgm"],
                "book_odds": 105,
                "true_prob": 0.52,
                "base_kelly_fraction": 0.03,
                "book_decimal": 2.05,
                "ev_percentage": 6.6,
                "scanner_duplicate_state": "new",
                "best_logged_odds_american": None,
                "current_odds_american": 105,
                "matched_pending_bet_id": None,
            }
        ],
        "prizepicks_cards": [],
        "events_fetched": 1,
        "events_with_both_books": 1,
        "api_requests_remaining": "498",
        "scanned_at": "2026-03-20T17:55:00Z",
    }
    fake_db_state = {"select_data": [{"payload": payload}]}
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(main, "_annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

    resp = auth_client.get(
        "/api/scan-latest",
        params={"surface": "player_props"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["surface"] == "player_props"
    assert body["sides"][0]["reference_odds"] == -108
    assert body["prizepicks_cards"] == []


@pytest.mark.integration
def test_player_props_manual_scan_end_to_end_contract(auth_client, auth_headers, monkeypatch):
    import main
    import services.player_props as player_props

    fake_db_state = {}
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(main, "_annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

    async def _fake_scoreboard():
        return {
            "events": [
                {
                    "id": "401810887",
                    "competitions": [
                        {
                            "broadcasts": [{"names": ["NBA TV"]}],
                            "competitors": [
                                {
                                    "homeAway": "home",
                                    "team": {"displayName": "Denver Nuggets", "id": "7"},
                                },
                                {
                                    "homeAway": "away",
                                    "team": {"displayName": "Portland Trail Blazers", "id": "22"},
                                },
                            ],
                        }
                    ],
                }
            ]
        }

    async def _fake_fetch_events(_sport: str, source: str = "unknown"):
        assert source == "manual_scan_props_events"
        request = httpx.Request("GET", "https://example.test/events")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "99"})
        return [
            {
                "id": "odds-evt-1",
                "home_team": "Denver Nuggets",
                "away_team": "Portland Trail Blazers",
                "commence_time": "2099-03-21T03:00:00Z",
            }
        ], response

    async def _fake_fetch_prop_event(*, sport: str, event_id: str, markets: list[str], source: str):
        assert sport == "basketball_nba"
        assert event_id == "odds-evt-1"
        assert markets == ["player_points"]
        assert source == "manual_scan"
        request = httpx.Request("GET", f"https://example.test/{event_id}")
        response = httpx.Response(200, request=request, headers={"x-requests-remaining": "98"})
        return {
            "id": event_id,
            "home_team": "Denver Nuggets",
            "away_team": "Portland Trail Blazers",
            "commence_time": "2099-03-21T03:00:00Z",
            "bookmakers": [
                {
                    "key": "bovada",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Christian Braun (Denver Nuggets)", "point": 17.5, "price": -110},
                                {"name": "Under", "description": "Christian Braun (Denver Nuggets)", "point": 17.5, "price": -110},
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
                                {"name": "Over", "description": "Christian Braun (Denver Nuggets)", "point": 17.5, "price": -108},
                                {"name": "Under", "description": "Christian Braun (Denver Nuggets)", "point": 17.5, "price": -112},
                            ],
                        }
                    ],
                },
                {
                    "key": "fanduel",
                    "link": "https://sportsbook.example/fd/christian-braun",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {"name": "Over", "description": "Christian Braun (Denver Nuggets)", "point": 17.5, "price": 105},
                                {"name": "Under", "description": "Christian Braun (Denver Nuggets)", "point": 17.5, "price": -125},
                            ],
                        }
                    ],
                },
            ],
        }, response

    async def _fake_build_matchup_player_lookup(**_kwargs):
        return {
            "christianbraun": {"team": "Denver Nuggets", "participant_id": "4431767"},
        }

    player_props._props_cache.clear()
    player_props._props_locks.clear()
    monkeypatch.setattr(player_props, "get_scan_cache", lambda _slot: None, raising=True)
    monkeypatch.setattr(player_props, "set_scan_cache", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(player_props, "fetch_nba_scoreboard_window", _fake_scoreboard, raising=True)
    monkeypatch.setattr(player_props, "fetch_events", _fake_fetch_events, raising=True)
    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_event, raising=True)
    monkeypatch.setattr(player_props, "build_matchup_player_lookup", _fake_build_matchup_player_lookup, raising=True)
    monkeypatch.setattr(player_props, "get_player_prop_markets", lambda: ["player_points"], raising=True)
    monkeypatch.setattr(player_props, "get_player_prop_min_reference_bookmakers", lambda: 2, raising=True)

    scan_resp = auth_client.get(
        "/api/scan-markets",
        params={"surface": "player_props", "sport": "basketball_nba"},
        headers=auth_headers,
    )

    assert scan_resp.status_code == 200, scan_resp.text
    scan_body = scan_resp.json()
    _assert_shape_like(
        scan_body,
        {
            "surface": "player_props",
            "sport": "basketball_nba",
            "sides": [
                {
                    "surface": "player_props",
                    "event_id": "odds-evt-1",
                    "market_key": "player_points",
                    "selection_key": "odds-evt-1|player_points|christian braun|over:17.5",
                    "sportsbook": "FanDuel",
                    "sportsbook_deeplink_url": "https://sportsbook.example/fd/christian-braun",
                    "sportsbook_deeplink_level": "event",
                    "sport": "basketball_nba",
                    "event": "Portland Trail Blazers @ Denver Nuggets",
                    "commence_time": "2099-03-21T03:00:00Z",
                    "market": "player_points",
                    "player_name": "Christian Braun",
                    "participant_id": "4431767",
                    "team": "Denver Nuggets",
                    "opponent": "Portland Trail Blazers",
                    "selection_side": "over",
                    "line_value": 17.5,
                    "display_name": "Christian Braun Over 17.5",
                    "reference_odds": -108,
                    "reference_source": "market_median",
                    "reference_bookmakers": ["bovada", "betonlineag"],
                    "reference_bookmaker_count": 2,
                    "confidence_label": "solid",
                    "book_odds": 105,
                    "true_prob": 0.518,
                    "base_kelly_fraction": 0.047,
                    "book_decimal": 2.05,
                    "ev_percentage": 6.19,
                }
            ],
            "events_fetched": 1,
            "events_with_both_books": 1,
            "api_requests_remaining": "98",
            "scanned_at": "2026-03-20T17:55:00Z",
            "prizepicks_cards": [],
            "diagnostics": {
                "scan_mode": "curated_sniper",
                "scoreboard_event_count": 1,
                "odds_event_count": 1,
                "curated_games": [
                    {
                        "event_id": "401810887",
                        "away_team": "Portland Trail Blazers",
                        "home_team": "Denver Nuggets",
                        "selection_reason": "nba_tv",
                        "broadcasts": ["NBA TV"],
                        "odds_event_id": "odds-evt-1",
                        "commence_time": "2099-03-21T03:00:00Z",
                        "matched": True,
                    }
                ],
                "matched_event_count": 1,
                "unmatched_game_count": 0,
                "events_fetched": 1,
                "events_skipped_pregame": 0,
                "events_with_results": 1,
                "candidate_sides_count": 6,
                "quality_gate_filtered_count": 0,
                "quality_gate_min_reference_bookmakers": 2,
                "sides_count": 6,
                "markets_requested": ["player_points"],
                "prizepicks_status": "disabled",
                "prizepicks_message": None,
                "prizepicks_board_items_count": 0,
                "prizepicks_exact_line_matches_count": 0,
                "prizepicks_unmatched_count": 0,
                "prizepicks_filtered_count": 0,
            },
        },
    )

    upsert = fake_db_state["last_upsert"]
    latest_payload = upsert["payload"]["payload"]
    assert latest_payload["surface"] == "player_props"
    assert latest_payload["diagnostics"]["quality_gate_min_reference_bookmakers"] == 2
    assert latest_payload["sides"][0]["participant_id"] == "4431767"
    assert latest_payload["prizepicks_cards"] == []

    fake_db_state["select_data"] = [{"payload": latest_payload}]
    latest_resp = auth_client.get(
        "/api/scan-latest",
        params={"surface": "player_props"},
        headers=auth_headers,
    )

    assert latest_resp.status_code == 200
    latest_body = latest_resp.json()
    assert latest_body["surface"] == "player_props"
    assert latest_body["events_fetched"] == 1
    assert latest_body["diagnostics"]["candidate_sides_count"] == 6
    assert latest_body["sides"][0]["reference_bookmaker_count"] == 2
    assert latest_body["prizepicks_cards"] == []


@pytest.mark.integration
def test_ops_status_contract_shape_normal(auth_client, monkeypatch):
    import main

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")

    resp = auth_client.get("/api/ops/status", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, _load_fixture("ops_status_normal.json"))


@pytest.mark.integration
def test_ops_status_contract_shape_degraded(monkeypatch, auth_client):
    import main

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    monkeypatch.setattr(main, "_runtime_state", lambda: {
        "environment": "production",
        "scheduler_expected": True,
        "scheduler_running": True,
        "redis_configured": True,
        "cron_token_configured": True,
        "odds_api_key_configured": True,
        "supabase_url_configured": True,
        "supabase_service_role_configured": True,
    }, raising=True)
    monkeypatch.setattr(main, "_check_db_ready", lambda: (False, "database timeout"), raising=True)
    monkeypatch.setattr(main, "_check_scheduler_freshness", lambda _expected: (False, {
        "enabled": True,
        "fresh": False,
        "reason": "stale",
    }), raising=True)

    main.app.state.ops_status = {
        "last_readiness_failure": {
            "captured_at": "2026-03-20T17:58:00Z",
            "checks": {"db_connectivity": False, "scheduler_freshness": False},
            "db_error": "database timeout",
        }
    }

    import services.odds_api as odds_api
    monkeypatch.setattr(odds_api, "get_odds_api_activity_snapshot", lambda: {
        "summary": {
            "calls_last_hour": 7,
            "errors_last_hour": 2,
            "last_success_at": "2026-03-20T17:54:00Z",
            "last_error_at": "2026-03-20T17:56:00Z",
        },
        "recent_scans": [
            {
                "activity_kind": "scan_session",
                "scan_session_id": "manual-1",
                "timestamp": "2026-03-20T17:55:00Z",
                "source": "manual_scan",
                "surface": "straight_bets",
                "scan_scope": "single_sport",
                "requested_sport": "basketball_ncaab",
                "actor_label": "ops@example.com",
                "run_id": None,
                "detail_count": 1,
                "live_call_count": 1,
                "cache_hit_count": 0,
                "other_count": 0,
                "total_events_fetched": 3,
                "total_events_with_both_books": 2,
                "total_sides": 6,
                "min_api_requests_remaining": "490",
                "error_count": 1,
                "has_errors": True,
                "details": [
                    {
                        "activity_kind": "scan_detail",
                        "timestamp": "2026-03-20T17:55:00Z",
                        "source": "manual_scan",
                        "surface": "straight_bets",
                        "scan_scope": "single_sport",
                        "requested_sport": "basketball_ncaab",
                        "sport": "basketball_ncaab",
                        "actor_label": "ops@example.com",
                        "run_id": None,
                        "cache_hit": False,
                        "outbound_call_made": True,
                        "duration_ms": 384,
                        "events_fetched": 3,
                        "events_with_both_books": 2,
                        "sides_count": 6,
                        "api_requests_remaining": "490",
                        "status_code": 502,
                        "error_type": "HTTPStatusError",
                        "error_message": "bad gateway",
                    }
                ],
            }
        ],
        "recent_calls": [
            {
                "activity_kind": "raw_call",
                "timestamp": "2026-03-20T17:56:00Z",
                "source": "manual_scan",
                "endpoint": "odds",
                "sport": "basketball_ncaab",
                "cache_hit": False,
                "outbound_call_made": True,
                "status_code": 502,
                "duration_ms": 384,
                "api_requests_remaining": "490",
                "error_type": "HTTPStatusError",
                "error_message": "bad gateway",
            }
        ],
    }, raising=True)

    resp = auth_client.get("/api/ops/status", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, _load_fixture("ops_status_degraded.json"))


@pytest.mark.integration
def test_ops_trigger_scan_contract_shape(auth_client, monkeypatch):
    import services.daily_board as daily_board

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_daily_board_drop(*, db, source: str, retry_supabase, log_event):
        assert source == "ops_trigger_board_drop"
        return {
            "ok": True,
            "snapshot_id": "snap_test",
            "scanned_at": "2026-03-26T20:00:00Z",
            "selected_event_ids": ["evt-1"],
            "selected_games": [],
            "props_sides": 2,
            "duration_ms": 12.0,
        }

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_daily_board_drop, raising=True)

    resp = auth_client.post("/api/ops/trigger/scan", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body.get("ok"), bool)
    assert isinstance(body.get("run_id"), str)
    assert body.get("board_drop") is True
    assert isinstance(body.get("result"), dict) or body.get("result") is None
    assert isinstance(body.get("errors"), list)
    assert (isinstance(body.get("total_sides"), int) or body.get("total_sides") is None)
    assert isinstance(body.get("alerts_scheduled"), int)


@pytest.mark.integration
def test_ops_research_opportunities_summary_contract_shape(auth_client, monkeypatch):
    import main
    import services.research_opportunities as research

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB({}), raising=True)

    monkeypatch.setattr(research, "get_research_opportunities_summary", lambda _db, **_kwargs: {
        "captured_count": 4,
        "open_count": 2,
        "close_captured_count": 2,
        "pending_close_count": 2,
        "valid_close_count": 2,
        "invalid_close_count": 0,
        "valid_close_coverage_pct": None,
        "invalid_close_rate_pct": None,
        "clv_ready_count": 2,
        "beat_close_pct": 50.0,
        "avg_clv_percent": 0.8,
        "by_surface": [],
        "by_source": [],
        "by_sportsbook": [],
        "by_edge_bucket": [],
        "by_odds_bucket": [],
        "recent_opportunities": [
            {
                "opportunity_key": "prop-1",
                "surface": "player_props",
                "first_seen_at": "2026-03-24T15:00:00Z",
                "last_seen_at": "2026-03-24T15:00:00Z",
                "commence_time": "2026-03-24T19:00:00Z",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "team": "Denver Nuggets",
                "sportsbook": "FanDuel",
                "market": "player_points",
                "event_id": "evt-prop-1",
                "player_name": "Nikola Jokic",
                "source_market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "first_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 6.6,
                "first_book_odds": 105,
                "best_book_odds": 105,
                "latest_reference_odds": -108,
                "reference_odds_at_close": None,
                "clv_ev_percent": None,
                "beat_close": None,
            }
        ],
    }, raising=True)

    resp = auth_client.get("/api/ops/research-opportunities/summary", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body.get("captured_count"), int)
    assert isinstance(body.get("open_count"), int)
    assert isinstance(body.get("close_captured_count"), int)
    assert isinstance(body.get("clv_ready_count"), int)
    assert isinstance(body.get("by_surface"), list)
    assert isinstance(body.get("by_source"), list)
    assert isinstance(body.get("recent_opportunities"), list)
    assert body["recent_opportunities"][0]["surface"] == "player_props"


@pytest.mark.integration
def test_ops_model_calibration_summary_contract_shape(auth_client, monkeypatch):
    import main
    import services.model_calibration as calibration

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB({}), raising=True)

    monkeypatch.setattr(calibration, "get_model_calibration_summary", lambda _db: {
        "captured_count": 8,
        "valid_close_count": 4,
        "paired_close_count": 3,
        "fallback_close_count": 1,
        "paired_close_pct": 75.0,
        "by_model": [
            {
                "key": "props_v1_live",
                "captured_count": 4,
                "valid_close_count": 2,
                "paired_close_count": 2,
                "avg_brier_score": 0.024,
                "avg_log_loss": 0.137,
                "avg_clv_percent": 0.8,
                "beat_close_pct": 50.0,
            }
        ],
        "by_market": [],
        "by_sportsbook": [],
        "by_interpolation_mode": [],
        "cohort_trend": [
            {
                "cohort_key": "2026-03-30",
                "captured_count": 8,
                "valid_close_count": 4,
                "avg_brier_score": 0.022,
                "avg_log_loss": 0.131,
                "avg_clv_percent": 0.7,
                "beat_close_pct": 50.0,
            }
        ],
        "recent_comparisons": [
            {
                "opportunity_key": "prop-compare-1",
                "surface": "player_props",
                "first_seen_at": "2026-03-30T12:00:00Z",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "sportsbook": "FanDuel",
                "market": "player_points",
                "player_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "close_quality": "paired",
                "close_true_prob": 0.534,
                "baseline_model_key": "props_v1_live",
                "baseline_true_prob": 0.522,
                "baseline_ev_percentage": 6.1,
                "baseline_clv_ev_percent": 0.5,
                "candidate_model_key": "props_v2_shadow",
                "candidate_true_prob": 0.531,
                "candidate_ev_percentage": 7.0,
                "candidate_clv_ev_percent": 0.8,
            }
        ],
        "release_gate": {
            "candidate_model_key": "props_v2_shadow",
            "baseline_model_key": "props_v1_live",
            "candidate_valid_close_count": 120,
            "baseline_valid_close_count": 120,
            "candidate_avg_brier_score": 0.021,
            "baseline_avg_brier_score": 0.024,
            "candidate_avg_log_loss": 0.129,
            "baseline_avg_log_loss": 0.137,
            "candidate_avg_clv_percent": 0.82,
            "baseline_avg_clv_percent": 0.8,
            "candidate_beat_close_pct": 51.0,
            "baseline_beat_close_pct": 50.0,
            "eligible": False,
            "passes": False,
            "reasons": ["Need at least 200 valid closes for both baseline and shadow models."],
        },
    }, raising=True)

    resp = auth_client.get("/api/ops/model-calibration/summary", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body.get("captured_count"), int)
    assert isinstance(body.get("valid_close_count"), int)
    assert isinstance(body.get("paired_close_count"), int)
    assert isinstance(body.get("fallback_close_count"), int)
    assert isinstance(body.get("by_model"), list)
    assert isinstance(body.get("cohort_trend"), list)
    assert isinstance(body.get("recent_comparisons"), list)
    assert isinstance(body.get("release_gate"), dict)
    assert body["recent_comparisons"][0]["candidate_model_key"] == "props_v2_shadow"


@pytest.mark.integration
def test_ops_trigger_auto_settle_contract_shape(auth_client, monkeypatch):
    import services.odds_api as odds_api
    import main

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(main, "get_db", lambda: _FakeDB({}), raising=True)

    async def _fake_run_auto_settler(_db, source: str = "auto_settle_ops_trigger"):
        assert source == "auto_settle_ops_trigger"
        return 3

    monkeypatch.setattr(odds_api, "run_auto_settler", _fake_run_auto_settler, raising=True)
    monkeypatch.setattr(odds_api, "get_last_auto_settler_summary", lambda: {"total_settled": 3}, raising=True)

    resp = auth_client.post("/api/ops/trigger/auto-settle", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert body.get("ok") is True
    assert isinstance(body.get("run_id"), str)
    assert isinstance(body.get("duration_ms"), (int, float))
    assert isinstance(body.get("settled"), int)


@pytest.mark.integration
def test_ops_trigger_test_discord_contract_shape(auth_client, monkeypatch):
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_send_discord_webhook(_payload):
        return None

    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    resp = auth_client.post("/api/ops/trigger/test-discord", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert body.get("ok") is True
    assert body.get("scheduled") is True
    assert isinstance(body.get("run_id"), str)


@pytest.mark.integration
def test_ops_trigger_test_discord_returns_diagnostics_on_failure(auth_client, monkeypatch):
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_send_discord_webhook(_payload, message_type="alert"):
        raise discord_alerts.DiscordDeliveryError(
            message="Discord webhook rejected test message with status 429: rate limited",
            message_type=message_type,
            status_code=429,
            response_text="rate limited",
        )

    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    resp = auth_client.post("/api/ops/trigger/test-discord", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 502

    body = resp.json()
    assert body["detail"]["error"] == "discord_delivery_failed"
    assert body["detail"]["message_type"] == "test"
    assert body["detail"]["status_code"] == 429
    assert body["detail"]["response_text"] == "rate limited"


@pytest.mark.integration
def test_ops_trigger_test_discord_alert_contract_shape(auth_client, monkeypatch):
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_send_discord_webhook(_payload, message_type="alert"):
        return None

    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    resp = auth_client.post("/api/ops/trigger/test-discord-alert", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert body.get("ok") is True
    assert body.get("scheduled") is True
    assert isinstance(body.get("run_id"), str)
