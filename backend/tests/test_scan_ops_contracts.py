import asyncio
import json
import os
import types
from pathlib import Path

import httpx
import pytest

from services import ops_runtime

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
    assert public_client.get(
        "/api/ops/alt-pitcher-k-lookup",
        params={
            "player_name": "Gerrit Cole",
            "team": "New York Yankees",
            "opponent": "Boston Red Sox",
            "line_value": 6.5,
            "game_date": "2026-07-04",
        },
    ).status_code == 401
    assert public_client.post("/api/ops/trigger/board-refresh").status_code == 401
    assert public_client.post("/api/ops/trigger/board-refresh/async").status_code == 401
    removed_scan_path = "/api/ops/trigger/" + "scan"
    assert public_client.post(removed_scan_path).status_code == 404
    assert public_client.post(f"{removed_scan_path}/async").status_code == 404
    assert public_client.post("/api/ops/trigger/auto-settle").status_code == 401
    assert public_client.post("/api/ops/trigger/test-discord").status_code == 401


@pytest.mark.integration
def test_ready_api_role_ignores_scheduler_freshness(monkeypatch, public_client):
    import routes.health_routes as health_routes

    monkeypatch.setenv("APP_ROLE", "api")
    monkeypatch.setattr(health_routes, "runtime_state", lambda: {
        "environment": "production",
        "scheduler_expected": True,
        "scheduler_running": False,
        "redis_configured": True,
        "cron_token_configured": True,
        "odds_api_key_configured": True,
        "supabase_url_configured": True,
        "supabase_service_role_configured": True,
        "discord": {
            "heartbeat_enabled": False,
            "scan_alert_mode": "off",
            "alert_delivery": {},
            "test_delivery": {},
            "last_schedule_stats": {},
        },
    }, raising=True)
    monkeypatch.setattr(health_routes, "check_db_ready", lambda: (True, None), raising=True)
    monkeypatch.setattr(health_routes, "check_scheduler_freshness", lambda _expected: (False, {
        "enabled": True,
        "fresh": False,
        "reason": "stale",
        "jobs": {},
    }), raising=True)

    resp = public_client.get("/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["scheduler_state"] is True
    assert body["checks"]["scheduler_freshness"] is True
    assert body["scheduler_freshness"]["fresh"] is False


@pytest.mark.integration
def test_ready_scheduler_role_requires_scheduler_freshness(monkeypatch, public_client):
    import routes.health_routes as health_routes

    monkeypatch.setenv("APP_ROLE", "scheduler")
    monkeypatch.setattr(health_routes, "runtime_state", lambda: {
        "environment": "production",
        "scheduler_expected": True,
        "scheduler_running": True,
        "redis_configured": True,
        "cron_token_configured": True,
        "odds_api_key_configured": True,
        "supabase_url_configured": True,
        "supabase_service_role_configured": True,
        "discord": {
            "heartbeat_enabled": False,
            "scan_alert_mode": "off",
            "alert_delivery": {},
            "test_delivery": {},
            "last_schedule_stats": {},
        },
    }, raising=True)
    monkeypatch.setattr(health_routes, "check_db_ready", lambda: (True, None), raising=True)
    monkeypatch.setattr(health_routes, "check_scheduler_freshness", lambda _expected: (False, {
        "enabled": True,
        "fresh": False,
        "reason": "stale",
        "jobs": {},
    }), raising=True)

    resp = public_client.get("/ready")

    assert resp.status_code == 503
    body = resp.json()["detail"]
    assert body["status"] == "not_ready"
    assert body["checks"]["scheduler_freshness"] is False
    assert body["scheduler_freshness"]["fresh"] is False


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
    import routes.scan_routes as scan_routes
    import services.odds_api as odds_api

    async def _fake_get_cached_or_scan(_sport: str, source: str = "manual_scan"):
        assert source == "manual_scan"
        return {
            "sides": [
                {
                    "event_id": "evt-123",
                    "market_key": "spreads",
                    "selection_key": "evt-123|spreads|lakers|-1.5",
                    "sportsbook": "DraftKings",
                    "sportsbook_deeplink_url": "https://sportsbook.example/dk/event/evt-123",
                    "sportsbook_deeplink_level": "event",
                    "sport": "basketball_nba",
                    "event": "Lakers @ Warriors",
                    "commence_time": "2026-03-20T18:00:00Z",
                    "team": "Lakers",
                    "selection_side": "home",
                    "line_value": -1.5,
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
    monkeypatch.setattr(scan_routes, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(scan_routes, "retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(scan_routes, "annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

    async def _fake_piggyback_clv(_sides):
        return None

    monkeypatch.setattr(scan_routes, "piggyback_clv", _fake_piggyback_clv, raising=True)
    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ["basketball_nba"], raising=True)
    monkeypatch.setattr(odds_api, "get_cached_or_scan", _fake_get_cached_or_scan, raising=True)

    resp = auth_client.get("/api/scan-markets", params={"sport": "basketball_nba"}, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, _load_fixture("scan_markets_normal.json"))


@pytest.mark.integration
def test_scan_latest_empty_contract_shape(auth_client, auth_headers, monkeypatch):
    import routes.scan_routes as scan_routes

    fake_db_state = {"select_data": []}
    monkeypatch.setattr(scan_routes, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(scan_routes, "retry_supabase", lambda f: f(), raising=True)

    resp = auth_client.get("/api/scan-latest", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, _load_fixture("scan_markets_empty.json"))


@pytest.mark.integration
def test_scan_latest_duplicate_state_contract_shape(auth_client, auth_headers, monkeypatch):
    import routes.scan_routes as scan_routes

    payload = _load_fixture("scan_markets_duplicate_state.json")
    fake_db_state = {"select_data": [{"payload": payload}]}
    monkeypatch.setattr(scan_routes, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(scan_routes, "retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(scan_routes, "annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

    resp = auth_client.get("/api/scan-latest", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    _assert_shape_like(body, payload)


@pytest.mark.integration
def test_scan_markets_accepts_player_props_surface(auth_client, auth_headers, monkeypatch):
    import routes.scan_routes as scan_routes
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
    monkeypatch.setattr(scan_routes, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(scan_routes, "retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(scan_routes, "annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)
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
    import routes.scan_routes as scan_routes

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
    monkeypatch.setattr(scan_routes, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(scan_routes, "retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(scan_routes, "annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

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
    import routes.scan_routes as scan_routes
    import services.player_props as player_props

    fake_db_state = {}
    monkeypatch.setattr(scan_routes, "get_db", lambda: _FakeDB(fake_db_state), raising=True)
    monkeypatch.setattr(scan_routes, "retry_supabase", lambda f: f(), raising=True)
    monkeypatch.setattr(scan_routes, "annotate_sides_with_duplicate_state", lambda _db, _uid, sides: sides, raising=True)

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

    assert "_model_candidate_sets" not in scan_body
    upsert = fake_db_state["last_upsert"]
    latest_payload = upsert["payload"]["payload"]
    assert latest_payload["surface"] == "player_props"
    assert "_model_candidate_sets" not in latest_payload
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
    assert "_model_candidate_sets" not in latest_body
    assert latest_body["events_fetched"] == 1
    assert latest_body["diagnostics"]["candidate_sides_count"] == 6
    assert latest_body["sides"][0]["reference_bookmaker_count"] == 2
    assert latest_body["prizepicks_cards"] == []


@pytest.mark.integration
def test_ops_status_contract_shape_normal(auth_client, monkeypatch):
    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")

    resp = auth_client.get("/api/ops/status", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200
    body = resp.json()
    _assert_shape_like(body, _load_fixture("ops_status_normal.json"))


@pytest.mark.integration
def test_ops_alt_pitcher_k_lookup_contract_shape(public_client, monkeypatch):
    import services.player_props as player_props

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_lookup(*, player_name: str, team: str | None, opponent: str | None, line_value: float, game_date: str | None, source: str = "ops_alt_pitcher_k_lookup"):
        assert player_name == "Gerrit Cole"
        assert team == "New York Yankees"
        assert opponent == "Boston Red Sox"
        assert line_value == 6.5
        assert game_date == "2026-07-04"
        return {
            "status": "ok",
            "sport": "baseball_mlb",
            "market_key": "pitcher_strikeouts_alternate",
            "resolution_mode": "exact_pair",
            "lookup": {
                "player_name": player_name,
                "team": team,
                "opponent": opponent,
                "line_value": line_value,
                "game_date": game_date,
            },
            "event": {
                "event_id": "evt-mlb-1",
                "event": "New York Yankees @ Boston Red Sox",
                "commence_time": "2026-07-04T23:10:00Z",
            },
            "consensus": {
                "over_prob": 0.5238,
                "under_prob": 0.4762,
                "fair_over_odds": -110,
                "fair_under_odds": 110,
                "paired_books": ["Bovada", "DraftKings"],
                "paired_books_count": 2,
                "reference_books": ["Bovada", "DraftKings"],
                "reference_books_count": 2,
                "best_over_sportsbook": "DraftKings",
                "best_over_odds": 105,
                "best_over_deeplink_url": None,
                "best_under_sportsbook": "Bovada",
                "best_under_odds": -110,
                "best_under_deeplink_url": None,
                "offers": [
                    {
                        "sportsbook": "Bovada",
                        "over_odds": -110,
                        "over_deeplink_url": None,
                        "under_odds": -110,
                        "under_deeplink_url": None,
                    }
                ],
            },
            "confidence": {
                "bucket": "low",
                "paired_books_count": 2,
                "repo_label": "solid",
                "repo_score": 0.5,
                "prob_std": 0.01,
                "reason": "two_paired_books_exact_line",
            },
            "warning": None,
            "cache": {
                "hit": False,
                "ttl_seconds": 60,
            },
            "observed_offers": [
                {
                    "sportsbook": "Bovada",
                    "line_value": 6.5,
                    "over_odds": -110,
                    "over_deeplink_url": None,
                    "under_odds": -110,
                    "under_deeplink_url": None,
                }
            ],
            "candidate_events": [],
        }

    monkeypatch.setattr(player_props, "lookup_alt_pitcher_k_exact_line", _fake_lookup, raising=True)

    resp = public_client.get(
        "/api/ops/alt-pitcher-k-lookup",
        params={
            "player_name": "Gerrit Cole",
            "team": "New York Yankees",
            "opponent": "Boston Red Sox",
            "line_value": 6.5,
            "game_date": "2026-07-04",
        },
        headers={"X-Ops-Token": "ops-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    _assert_shape_like(
        body,
        {
            "status": "ok",
            "sport": "baseball_mlb",
            "market_key": "pitcher_strikeouts_alternate",
            "resolution_mode": "exact_pair",
            "lookup": {
                "player_name": "Gerrit Cole",
                "team": "New York Yankees",
                "opponent": "Boston Red Sox",
                "line_value": 6.5,
                "game_date": "2026-07-04",
            },
            "event": {
                "event_id": "evt-mlb-1",
                "event": "New York Yankees @ Boston Red Sox",
                "commence_time": "2026-07-04T23:10:00Z",
            },
            "consensus": {
                "over_prob": 0.5238,
                "under_prob": 0.4762,
                "fair_over_odds": -110,
                "fair_under_odds": 110,
                "paired_books": ["Bovada"],
                "paired_books_count": 2,
                "reference_books": ["Bovada", "DraftKings"],
                "reference_books_count": 2,
                "best_over_sportsbook": "DraftKings",
                "best_over_odds": 105,
                "best_over_deeplink_url": None,
                "best_under_sportsbook": "Bovada",
                "best_under_odds": -110,
                "best_under_deeplink_url": None,
                "offers": [
                    {
                        "sportsbook": "Bovada",
                        "over_odds": -110,
                        "over_deeplink_url": None,
                        "under_odds": -110,
                        "under_deeplink_url": None,
                    }
                ],
            },
            "confidence": {
                "bucket": "low",
                "paired_books_count": 2,
                "repo_label": "solid",
                "repo_score": 0.5,
                "prob_std": 0.01,
                "reason": "two_paired_books_exact_line",
            },
            "warning": None,
            "cache": {
                "hit": False,
                "ttl_seconds": 60,
            },
            "observed_offers": [
                {
                    "sportsbook": "Bovada",
                    "line_value": 6.5,
                    "over_odds": -110,
                    "over_deeplink_url": None,
                    "under_odds": -110,
                    "under_deeplink_url": None,
                }
            ],
            "candidate_events": [],
        },
    )


@pytest.mark.integration
def test_ops_alt_pitcher_k_lookup_allows_optional_context(public_client, monkeypatch):
    import services.player_props as player_props

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_lookup(*, player_name: str, team: str | None, opponent: str | None, line_value: float, game_date: str | None, source: str = "ops_alt_pitcher_k_lookup"):
        assert player_name == "Gerrit Cole"
        assert team is None
        assert opponent is None
        assert line_value == 6.5
        assert game_date is None
        return {
            "status": "not_found",
            "sport": "baseball_mlb",
            "market_key": "pitcher_strikeouts_alternate",
            "resolution_mode": None,
            "lookup": {
                "player_name": player_name,
                "team": team,
                "opponent": opponent,
                "line_value": line_value,
                "game_date": game_date,
            },
            "warning": "Player name + exact line alone did not find a unique live alt K line. Add pitcher team, opponent, or game date if you have it.",
            "cache": {
                "hit": False,
                "ttl_seconds": 60,
            },
            "observed_offers": [],
            "candidate_events": [],
        }

    monkeypatch.setattr(player_props, "lookup_alt_pitcher_k_exact_line", _fake_lookup, raising=True)

    resp = public_client.get(
        "/api/ops/alt-pitcher-k-lookup",
        params={
            "player_name": "Gerrit Cole",
            "line_value": 6.5,
        },
        headers={"X-Ops-Token": "ops-secret"},
    )

    assert resp.status_code == 200
    _assert_shape_like(
        resp.json(),
        {
            "status": "not_found",
            "sport": "baseball_mlb",
            "market_key": "pitcher_strikeouts_alternate",
            "resolution_mode": None,
            "lookup": {
                "player_name": "Gerrit Cole",
                "team": None,
                "opponent": None,
                "line_value": 6.5,
                "game_date": None,
            },
            "warning": "Player name + exact line alone did not find a unique live alt K line. Add pitcher team, opponent, or game date if you have it.",
            "cache": {
                "hit": False,
                "ttl_seconds": 60,
            },
            "observed_offers": [],
            "candidate_events": [],
        },
    )


@pytest.mark.integration
def test_ops_alt_pitcher_k_lookup_rate_limit_returns_429(public_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.player_props as player_props

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(ops_cron, "allow_fixed_window_rate_limit", lambda **_kwargs: False, raising=True)

    async def _boom_lookup(**_kwargs):
        raise AssertionError("lookup should not run when rate limit is exceeded")

    monkeypatch.setattr(player_props, "lookup_alt_pitcher_k_exact_line", _boom_lookup, raising=True)

    resp = public_client.get(
        "/api/ops/alt-pitcher-k-lookup",
        params={
            "player_name": "Gerrit Cole",
            "team": "New York Yankees",
            "opponent": "Boston Red Sox",
            "line_value": 6.5,
            "game_date": "2026-07-04",
        },
        headers={"X-Ops-Token": "ops-secret"},
    )

    assert resp.status_code == 429
    assert "Too many Alt Pitcher K lookup requests" in resp.json()["detail"]


@pytest.mark.integration
def test_ops_status_contract_shape_degraded(monkeypatch, auth_client):
    import routes.ops_cron as ops_cron

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    monkeypatch.setattr(ops_cron, "runtime_state", lambda: {
        "environment": "production",
        "scheduler_expected": True,
        "scheduler_running": True,
        "redis_configured": True,
        "cron_token_configured": True,
        "odds_api_key_configured": True,
        "supabase_url_configured": True,
        "supabase_service_role_configured": True,
    }, raising=True)
    monkeypatch.setattr(ops_cron, "check_db_ready", lambda: (False, "database timeout"), raising=True)
    monkeypatch.setattr(ops_cron, "check_scheduler_freshness", lambda _expected: (False, {
        "enabled": True,
        "fresh": False,
        "reason": "stale",
    }), raising=True)

    fallback_ops_status = {
        "last_readiness_failure": {
            "captured_at": "2026-03-20T17:58:00Z",
            "checks": {"db_connectivity": False, "scheduler_freshness": False},
            "db_error": "database timeout",
        }
    }
    monkeypatch.setattr(ops_cron, "get_ops_status", lambda: fallback_ops_status, raising=True)

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
def test_ops_trigger_board_refresh_runs_manual_board_refresh_contract(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

    async def _fake_board_drop_impl(**_kwargs):
        return {
            "ok": True,
            "run_id": "board-refresh-1",
            "started_at": "2026-03-20T18:00:00Z",
            "finished_at": "2026-03-20T18:01:00Z",
            "duration_ms": 60000,
            "board_drop": True,
            "errors": [],
            "total_sides": 12,
            "alerts_scheduled": 2,
            "result": {"scan_label": "Ops Manual Board Refresh"},
        }

    monkeypatch.setattr("routes.ops_cron.cron_run_board_drop_impl", _fake_board_drop_impl, raising=True)

    resp = auth_client.post("/api/ops/trigger/board-refresh", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["board_drop"] is True
    assert body["run_id"] == "board-refresh-1"


@pytest.mark.integration
def test_ops_trigger_board_refresh_contract_shape(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.daily_board as daily_board
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("DISCORD_SCAN_ALERT_MODE", "edge_live")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)
    seen_message_types: list[str] = []
    seen_delivery_contexts: list[str | None] = []

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        assert source == "ops_trigger_board_drop"
        assert scan_label == "Ops Manual Board Refresh"
        assert mst_anchor_time is None
        return {
            "straight_sides": 6,
            "props_sides": 4,
            "featured_games_count": 3,
            "game_line_sports_scanned": ["basketball_nba", "baseball_mlb"],
            "props_events_scanned": 7,
            "selected_event_ids": ["evt-1", "evt-2"],
            "selected_games": [{"event_id": "evt-1"}],
            "game_lines_events_fetched": 2,
            "game_lines_events_with_both_books": 2,
            "game_lines_api_requests_remaining": "91",
            "props_events_fetched": 7,
            "props_events_with_both_books": 6,
            "props_api_requests_remaining": "90",
            "fresh_straight_sides": [{"surface": "straight_bets"}],
            "fresh_prop_sides": [{"surface": "player_props"}],
        }

    def _fake_schedule_alerts(sides, message_type="heartbeat", *, delivery_context=None):
        seen_message_types.append(message_type)
        seen_delivery_contexts.append(delivery_context)
        return len(sides)

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)
    monkeypatch.setattr(discord_alerts, "schedule_alerts", _fake_schedule_alerts, raising=True)

    resp = auth_client.post("/api/ops/trigger/board-refresh", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body.get("ok"), bool)
    assert isinstance(body.get("run_id"), str)
    assert body.get("board_drop") is True
    assert isinstance(body.get("errors"), list)
    assert isinstance(body.get("total_sides"), int)
    assert isinstance(body.get("alerts_scheduled"), int)
    assert body["total_sides"] == 10
    assert body["result"]["props_sides"] == 4
    assert seen_message_types == ["heartbeat"]
    assert seen_delivery_contexts == [None]


@pytest.mark.integration
def test_ops_trigger_board_refresh_timed_ping_routes_manual_board_refresh_to_heartbeat(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.daily_board as daily_board
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("DISCORD_SCAN_ALERT_MODE", "timed_ping")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        assert source == "ops_trigger_board_drop"
        return {
            "straight_sides": 4,
            "props_sides": 2,
            "featured_games_count": 3,
            "fresh_straight_sides": [],
            "fresh_prop_sides": [],
        }

    def _fail_if_edge_alerts_called(_sides, message_type="heartbeat", *, delivery_context=None):
        raise AssertionError("schedule_alerts should not run in timed_ping mode")

    sent: list[str] = []

    async def _fake_send_discord_webhook(payload, message_type="heartbeat", *, delivery_context=None):
        sent.append(message_type)
        assert delivery_context is None
        return {
            "delivery_status": "delivered",
            "status_code": 204,
            "route_kind": "heartbeat_dedicated",
            "webhook_source": "DISCORD_DEBUG_WEBHOOK_URL",
        }

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)
    monkeypatch.setattr(discord_alerts, "schedule_alerts", _fail_if_edge_alerts_called, raising=True)
    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    resp = auth_client.post("/api/ops/trigger/board-refresh", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200
    assert resp.json()["board_drop"] is True
    assert sent == ["heartbeat"]


@pytest.mark.integration
def test_ops_trigger_board_refresh_piggybacks_clv_with_fresh_sides(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.daily_board as daily_board
    import services.discord_alerts as discord_alerts

    captured_sides: list[list[dict]] = []
    fresh_straight = [{"surface": "straight_bets", "selection_key": "straight-1"}]
    fresh_props = [{"surface": "player_props", "selection_key": "prop-1"}]

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("DISCORD_SCAN_ALERT_MODE", "edge_live")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        assert source == "ops_trigger_board_drop"
        assert scan_label == "Ops Manual Board Refresh"
        assert mst_anchor_time is None
        return {
            "straight_sides": 3,
            "props_sides": 2,
            "fresh_straight_sides": fresh_straight,
            "fresh_prop_sides": fresh_props,
        }

    def _fake_piggyback_clv(sides):
        captured_sides.append(sides)

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)
    monkeypatch.setattr(
        discord_alerts,
        "schedule_alerts",
        lambda sides, message_type="heartbeat", *, delivery_context=None: len(sides),
        raising=True,
    )
    monkeypatch.setattr(ops_cron, "piggyback_clv", _fake_piggyback_clv, raising=True)

    resp = auth_client.post("/api/ops/trigger/board-refresh", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200
    assert captured_sides == [[*fresh_straight, *fresh_props]]


@pytest.mark.integration
def test_ops_trigger_board_refresh_skips_clv_piggyback_with_no_fresh_sides(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.daily_board as daily_board
    import services.discord_alerts as discord_alerts

    piggyback_calls = 0

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("DISCORD_SCAN_ALERT_MODE", "edge_live")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        return {
            "straight_sides": 0,
            "props_sides": 0,
            "fresh_straight_sides": [],
            "fresh_prop_sides": [],
        }

    def _fake_piggyback_clv(_sides):
        nonlocal piggyback_calls
        piggyback_calls += 1

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)
    monkeypatch.setattr(
        discord_alerts,
        "schedule_alerts",
        lambda sides, message_type="heartbeat", *, delivery_context=None: len(sides),
        raising=True,
    )
    monkeypatch.setattr(ops_cron, "piggyback_clv", _fake_piggyback_clv, raising=True)

    resp = auth_client.post("/api/ops/trigger/board-refresh", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200
    assert piggyback_calls == 0


@pytest.mark.integration
def test_ops_trigger_board_refresh_clv_piggyback_failure_does_not_fail_route(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.daily_board as daily_board
    import services.discord_alerts as discord_alerts

    created_tasks = 0
    real_create_task = asyncio.create_task

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("DISCORD_SCAN_ALERT_MODE", "edge_live")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        return {
            "straight_sides": 1,
            "props_sides": 0,
            "fresh_straight_sides": [{"surface": "straight_bets", "selection_key": "straight-1"}],
            "fresh_prop_sides": [],
        }

    async def _fake_piggyback_clv(_sides):
        raise RuntimeError("clv piggyback exploded")

    def _tracking_create_task(coro):
        nonlocal created_tasks
        created_tasks += 1
        return real_create_task(coro)

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)
    monkeypatch.setattr(
        discord_alerts,
        "schedule_alerts",
        lambda sides, message_type="heartbeat", *, delivery_context=None: len(sides),
        raising=True,
    )
    monkeypatch.setattr(ops_cron, "piggyback_clv", _fake_piggyback_clv, raising=True)
    monkeypatch.setattr("routes.ops_cron.asyncio.create_task", _tracking_create_task, raising=True)

    resp = auth_client.post("/api/ops/trigger/board-refresh", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200
    assert resp.json()["board_drop"] is True
    assert created_tasks >= 1


@pytest.mark.integration
def test_ops_trigger_board_refresh_async_background_runner_wires_clv_piggyback(monkeypatch):
    import routes.ops_cron as ops_cron

    captured: dict[str, object] = {}

    async def _fake_cron_run_board_drop_impl(*_args, **kwargs):
        captured["piggyback_clv"] = kwargs.get("piggyback_clv")

    monkeypatch.setattr(ops_cron, "cron_run_board_drop_impl", _fake_cron_run_board_drop_impl, raising=True)

    asyncio.run(ops_cron._run_ops_board_drop_background(run_id="ops-board-drop-test"))

    assert captured["piggyback_clv"] is ops_cron.piggyback_clv


@pytest.mark.integration
def test_ops_trigger_board_refresh_async_contract_shape(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

    async def _fake_background_runner(*, run_id: str):
        ops_runtime.set_ops_status(
            "last_ops_trigger_scan",
            {
                "run_id": run_id,
                "captured_at": "2026-03-20T18:00:00Z",
                "board_drop": True,
                "pending": False,
            },
        )

    monkeypatch.setattr("routes.ops_cron._run_ops_board_drop_background", _fake_background_runner, raising=True)

    resp = auth_client.post("/api/ops/trigger/board-refresh/async", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 202

    body = resp.json()
    assert body.get("ok") is True
    assert body.get("accepted") is True
    assert body.get("pending") is True
    assert body.get("board_drop") is True
    assert isinstance(body.get("run_id"), str)
    assert ops_runtime.get_ops_status()["last_board_refresh"]["status"] == "queued"
    assert ops_runtime.get_ops_status()["last_board_refresh"]["kind"] == "board_drop"


@pytest.mark.integration
def test_scoped_board_refresh_updates_latest_board_refresh(auth_client, monkeypatch):
    import routes.board_routes as board_routes
    import services.odds_api as odds_api
    import services.shared_state as shared_state

    ops_runtime.init_ops_status()
    persisted_runs: list[dict] = []

    monkeypatch.setattr(shared_state, "allow_fixed_window_rate_limit", lambda **_kwargs: True, raising=True)
    monkeypatch.setattr(board_routes, "get_db", lambda: _FakeDB({}), raising=True)
    monkeypatch.setattr(board_routes, "_retry_supabase", lambda func, retries=2: func(), raising=True)
    monkeypatch.setattr(
        board_routes,
        "persist_scoped_refresh",
        lambda **_kwargs: "2026-03-20T18:00:00Z",
        raising=True,
    )
    monkeypatch.setattr(board_routes, "_persist_ops_job_run", lambda **kwargs: persisted_runs.append(kwargs), raising=True)

    async def _fake_get_cached_or_scan(_sport: str, source: str = "manual_refresh"):
        assert source == "manual_refresh"
        return {
            "sides": [
                {
                    "surface": "straight_bets",
                    "sportsbook": "DraftKings",
                    "sport": "basketball_nba",
                    "event": "Lakers @ Warriors",
                    "commence_time": "2026-03-20T18:00:00Z",
                    "team": "Lakers",
                    "pinnacle_odds": 105,
                    "book_odds": 118,
                    "true_prob": 0.51,
                    "base_kelly_fraction": 0.02,
                    "book_decimal": 2.18,
                    "ev_percentage": 2.1,
                }
            ],
            "events_fetched": 3,
            "events_with_both_books": 2,
            "api_requests_remaining": "490",
            "scanned_at": "2026-03-20T17:58:00Z",
        }

    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ["basketball_nba"], raising=True)
    monkeypatch.setattr(odds_api, "get_cached_or_scan", _fake_get_cached_or_scan, raising=True)

    resp = auth_client.post("/api/board/refresh?scope=straight_bets")
    assert resp.status_code == 200

    body = resp.json()
    assert body["surface"] == "straight_bets"
    assert body["refreshed_at"] == "2026-03-20T18:00:00Z"
    assert body["data"]["events_fetched"] == 3

    latest_refresh = ops_runtime.get_ops_status()["last_board_refresh"]
    assert latest_refresh["kind"] == "scoped_refresh"
    assert latest_refresh["surface"] == "straight_bets"
    assert latest_refresh["status"] == "completed"
    assert latest_refresh["canonical_board_updated"] is False
    assert latest_refresh["result"]["scan_label"] == "Manual Game Lines Refresh"
    assert latest_refresh["result"]["straight_sides"] == 1

    assert persisted_runs[0]["job_kind"] == "board_scoped_refresh"
    assert persisted_runs[0]["status"] == "completed"
    assert persisted_runs[0]["surface"] == "straight_bets"
    assert persisted_runs[0]["meta"]["canonical_board_updated"] is False


@pytest.mark.integration
def test_scoped_board_refresh_failure_updates_latest_board_refresh(auth_client, monkeypatch):
    import routes.board_routes as board_routes
    import services.shared_state as shared_state

    ops_runtime.init_ops_status()
    persisted_runs: list[dict] = []

    monkeypatch.setattr(shared_state, "allow_fixed_window_rate_limit", lambda **_kwargs: True, raising=True)
    monkeypatch.setattr(board_routes, "get_db", lambda: _FakeDB({}), raising=True)
    monkeypatch.setattr(board_routes, "_persist_ops_job_run", lambda **kwargs: persisted_runs.append(kwargs), raising=True)

    async def _raise_refresh(*, source: str):
        raise RuntimeError(f"{source} exploded")

    monkeypatch.setattr(board_routes, "_refresh_player_props_result", _raise_refresh, raising=True)

    resp = auth_client.post("/api/board/refresh?scope=player_props")
    assert resp.status_code == 502

    latest_refresh = ops_runtime.get_ops_status()["last_board_refresh"]
    assert latest_refresh["kind"] == "scoped_refresh"
    assert latest_refresh["surface"] == "player_props"
    assert latest_refresh["status"] == "failed"
    assert latest_refresh["canonical_board_updated"] is False
    assert latest_refresh["error_count"] == 1
    assert latest_refresh["result"]["scan_label"] == "Manual Player Props Refresh"

    assert persisted_runs[0]["job_kind"] == "board_scoped_refresh"
    assert persisted_runs[0]["status"] == "failed"
    assert persisted_runs[0]["surface"] == "player_props"
    assert persisted_runs[0]["meta"]["canonical_board_updated"] is False


@pytest.mark.integration
def test_ops_research_opportunities_summary_contract_shape(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.research_opportunities as research

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

    monkeypatch.setattr(research, "get_research_opportunities_summary", lambda _db: {
        "captured_count": 4,
        "open_count": 2,
        "close_captured_count": 2,
        "clv_ready_count": 2,
        "beat_close_pct": 50.0,
        "avg_clv_percent": 0.8,
        "by_surface": [],
        "by_market": [],
        "by_source": [],
        "by_sportsbook": [],
        "by_edge_bucket": [],
        "by_drop_time": [],
        "by_event_day": [],
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
    assert isinstance(body.get("by_market"), list)
    assert isinstance(body.get("by_source"), list)
    assert isinstance(body.get("by_drop_time"), list)
    assert isinstance(body.get("by_event_day"), list)
    assert isinstance(body.get("recent_opportunities"), list)
    assert body["recent_opportunities"][0]["surface"] == "player_props"


@pytest.mark.integration
def test_ops_model_calibration_summary_contract_shape(auth_client, monkeypatch):
    import routes.ops_cron as ops_cron
    import services.model_calibration as calibration

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)
    monkeypatch.setattr(
        calibration,
        "get_model_calibration_summary",
        lambda _db: calibration.empty_model_calibration_summary(),
        raising=True,
    )

    resp = auth_client.get("/api/ops/model-calibration/summary", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body.get("captured_count"), int)
    assert isinstance(body.get("by_model"), list)
    assert "shadow_candidate_set" in body
    assert "release_gate" in body
    assert body["release_gate"]["verdict"] == "not_enough_sample"
    assert isinstance(body["release_gate"]["passes"], bool)
    assert "deadband_brier" in body["release_gate"]
    assert "overlap_pct" in body["shadow_candidate_set"]
    assert "weight_status" in body["shadow_candidate_set"]


@pytest.mark.integration
def test_ops_trigger_auto_settle_contract_shape(auth_client, monkeypatch):
    import services.odds_api as odds_api
    import routes.ops_cron as ops_cron

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setattr(ops_cron, "get_db", lambda: _FakeDB({}), raising=True)

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
    seen_message_types: list[str] = []

    async def _fake_send_discord_webhook(_payload, message_type="heartbeat", *, delivery_context=None):
        seen_message_types.append(message_type)
        assert delivery_context is None
        return None

    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    resp = auth_client.post("/api/ops/trigger/test-discord", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert body.get("ok") is True
    assert body.get("scheduled") is True
    assert isinstance(body.get("run_id"), str)
    assert seen_message_types == ["test"]


@pytest.mark.integration
def test_ops_trigger_test_discord_returns_diagnostics_on_failure(auth_client, monkeypatch):
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_send_discord_webhook(_payload, message_type="heartbeat", *, delivery_context=None):
        assert delivery_context is None
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
    seen_message_types: list[str] = []

    async def _fake_send_discord_webhook(_payload, message_type="heartbeat", *, delivery_context=None):
        seen_message_types.append(message_type)
        assert delivery_context is None
        return None

    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    resp = auth_client.post("/api/ops/trigger/test-discord-alert", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert body.get("ok") is True
    assert body.get("scheduled") is True
    assert isinstance(body.get("run_id"), str)
    assert body.get("message_type") == "test"
    assert seen_message_types == ["test"]


@pytest.mark.integration
def test_ops_trigger_test_discord_alert_returns_config_diagnostics_when_unconfigured(auth_client, monkeypatch):
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_send_discord_webhook(_payload, message_type="heartbeat", *, delivery_context=None):
        assert delivery_context is None
        return {
            "ok": False,
            "message_type": message_type,
            "route_kind": "test_unconfigured",
            "webhook_source": None,
            "delivery_status": "disabled_no_webhook",
            "status_code": None,
            "response_text": None,
        }

    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    resp = auth_client.post("/api/ops/trigger/test-discord-alert", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 503

    body = resp.json()
    assert body["detail"]["error"] == "discord_webhook_not_configured"
    assert body["detail"]["message_type"] == "test"
    assert body["detail"]["route_kind"] == "test_unconfigured"
    assert body["detail"]["webhook_source"] is None


@pytest.mark.integration
def test_ops_trigger_test_discord_alert_does_not_fallback_to_primary_when_debug_missing(auth_client, monkeypatch):
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY", "1")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)

    monkeypatch.setattr(
        discord_alerts.httpx,
        "AsyncClient",
        lambda timeout: pytest.fail("test Discord alert route should not post to the primary webhook"),
        raising=True,
    )

    resp = auth_client.post("/api/ops/trigger/test-discord-alert", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 503

    body = resp.json()
    assert body["detail"]["error"] == "discord_webhook_not_configured"
    assert body["detail"]["message_type"] == "test"
    assert body["detail"]["route_kind"] == "test_unconfigured"
    assert body["detail"]["webhook_source"] is None
