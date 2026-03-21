import json
import os
import types
from pathlib import Path

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
        "recent_calls": [
            {
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
    import services.odds_api as odds_api
    import services.discord_alerts as discord_alerts

    monkeypatch.setenv("CRON_TOKEN", "ops-secret")

    async def _fake_get_cached_or_scan(_sport: str, source: str = "ops_trigger_scan"):
        assert source == "ops_trigger_scan"
        return {
            "sides": [{"team": "Lakers"}, {"team": "Warriors"}],
            "events_fetched": 1,
            "events_with_both_books": 1,
            "api_requests_remaining": "496",
        }

    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ["basketball_nba"], raising=True)
    monkeypatch.setattr(odds_api, "get_cached_or_scan", _fake_get_cached_or_scan, raising=True)
    monkeypatch.setattr(discord_alerts, "schedule_alerts", lambda _sides: 0, raising=True)

    resp = auth_client.post("/api/ops/trigger/scan", headers={"X-Ops-Token": "ops-secret"})
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body.get("ok"), bool)
    assert isinstance(body.get("run_id"), str)
    assert isinstance(body.get("sports_scanned"), list)
    assert isinstance(body.get("errors"), list)
    assert isinstance(body.get("total_sides"), int)
    assert isinstance(body.get("alerts_scheduled"), int)


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
