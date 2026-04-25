import importlib
import types

import pytest
from fastapi import HTTPException

from .test_utils import ensure_supabase_stub

ensure_supabase_stub()


def test_check_db_ready_uses_bounded_rest_probe(monkeypatch):
    import services.ops_runtime as ops_runtime

    captured = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            return b"[]"

    def _fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers.get("Authorization")
        return _Response()

    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("READINESS_DB_TIMEOUT_SECONDS", "0.75")
    monkeypatch.setattr(ops_runtime.urllib.request, "urlopen", _fake_urlopen)

    ok, error = ops_runtime.check_db_ready()

    assert ok is True
    assert error is None
    assert captured["url"] == "https://test-project.supabase.co/rest/v1/settings?select=user_id&limit=1"
    assert captured["timeout"] == 0.75
    assert captured["authorization"] == "Bearer service-key"


def test_check_db_ready_reports_timeout_without_supabase_client(monkeypatch):
    import services.ops_runtime as ops_runtime

    def _fake_urlopen(_request, timeout):
        raise TimeoutError("slow db")

    def _fail_get_db():
        raise AssertionError("readiness must not initialize the Supabase SDK client")

    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("READINESS_DB_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(ops_runtime.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(ops_runtime, "get_db", _fail_get_db)

    ok, error = ops_runtime.check_db_ready()

    assert ok is False
    assert error == "TimeoutError: readiness DB probe exceeded 1s"


def test_readiness_failure_does_not_write_failure_history(monkeypatch):
    import routes.health_routes as health_routes

    status_updates = []
    log_events = []

    monkeypatch.setattr(health_routes, "runtime_state", lambda: {
        "environment": "production",
        "scheduler_expected": False,
        "scheduler_running": False,
        "redis_configured": True,
        "cron_token_configured": True,
        "odds_api_key_configured": True,
        "supabase_url_configured": True,
        "supabase_service_role_configured": True,
        "discord": {},
    })
    monkeypatch.setattr(health_routes, "check_db_ready", lambda: (False, "database timeout"))
    monkeypatch.setattr(health_routes, "check_scheduler_freshness", lambda _expected: (True, {
        "enabled": False,
        "fresh": True,
        "jobs": {},
    }))
    monkeypatch.setattr(health_routes, "set_ops_status", lambda key, payload: status_updates.append((key, payload)))
    monkeypatch.setattr(health_routes, "log_event", lambda event, **kwargs: log_events.append((event, kwargs)))

    with pytest.raises(HTTPException) as exc_info:
        health_routes.readiness_check()

    assert exc_info.value.status_code == 503
    assert status_updates[0][0] == "last_readiness_failure"
    assert log_events[0][0] == "readiness.failed"
    assert not hasattr(health_routes, "persist_ops_job_run")


def test_ops_status_uses_memory_fallback_when_db_not_ready():
    import routes.ops_cron as ops_cron

    calls = {"get_db": 0, "load_snapshot": 0}

    def _get_db():
        calls["get_db"] += 1
        raise AssertionError("ops status should not hit Supabase snapshot when db check failed")

    result = ops_cron.ops_status_impl(
        x_cron_token="ops-secret",
        require_valid_cron_token=lambda token: None,
        runtime_state=lambda: {"scheduler_expected": False},
        check_db_ready=lambda: (False, "database timeout"),
        check_scheduler_freshness=lambda _expected: (True, {"enabled": False, "fresh": True, "jobs": {}}),
        utc_now_iso=lambda: "2026-04-25T00:00:00Z",
        get_db=_get_db,
        retry_supabase=lambda fn: fn(),
        log_event=lambda *_args, **_kwargs: None,
        get_ops_status=lambda: {"last_readiness_failure": {"db_error": "database timeout"}},
    )

    assert calls["get_db"] == 0
    assert result["checks"]["db_connectivity"] is False
    assert result["ops"]["last_readiness_failure"]["db_error"] == "database timeout"


def test_get_db_refuses_production_supabase_while_testing(monkeypatch):
    import database

    monkeypatch.setenv("TESTING", "1")
    monkeypatch.delenv("ALLOW_PROD_TESTS", raising=False)
    monkeypatch.delenv("TEST_SUPABASE_URL", raising=False)
    monkeypatch.delenv("TEST_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://xzeakifampttrqqhhibu.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")

    database = importlib.reload(database)
    database._supabase = None

    with pytest.raises(RuntimeError, match="Refusing to initialize production Supabase"):
        database.get_db()


def test_get_db_allows_dedicated_test_supabase(monkeypatch):
    import database

    created = {}

    def _fake_create_client(url, key):
        created["url"] = url
        created["key"] = key
        return types.SimpleNamespace(url=url, key=key)

    monkeypatch.setenv("TESTING", "1")
    monkeypatch.delenv("ALLOW_PROD_TESTS", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://xzeakifampttrqqhhibu.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "prod-key")
    monkeypatch.setenv("TEST_SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("TEST_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    database = importlib.reload(database)
    monkeypatch.setattr(database, "create_client", _fake_create_client)
    database._supabase = None

    db = database.get_db()

    assert db.url == "https://test-project.supabase.co"
    assert created == {"url": "https://test-project.supabase.co", "key": "test-key"}
