import importlib
import os
import sys
import types
from datetime import datetime, UTC, timedelta

import pytest
from fastapi import HTTPException


def _reload_main(monkeypatch, *, zoneinfo_zoneinfo_override=None):
    """
    Reload backend main module with optional ZoneInfo override.

    main.py does `from zoneinfo import ZoneInfo` at import time, so to simulate
    missing tzdata we patch `zoneinfo.ZoneInfo` before reload.
    """
    if zoneinfo_zoneinfo_override is not None:
        import zoneinfo as _zoneinfo_mod
        monkeypatch.setattr(_zoneinfo_mod, "ZoneInfo", zoneinfo_zoneinfo_override, raising=True)

    # Unit tests should not require real backend secrets just to import main.
    monkeypatch.setenv("SUPABASE_URL", os.getenv("SUPABASE_URL") or "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "unit-test-key")

    # Allow importing main.py even when backend deps aren't installed in the current interpreter.
    # (These are unit tests; we stub the client to avoid touching the network/DB.)
    if "supabase" not in sys.modules:
        sys.modules["supabase"] = types.SimpleNamespace(
            create_client=lambda *args, **kwargs: None,
            Client=object,
        )

    if "main" in sys.modules:
        return importlib.reload(sys.modules["main"])
    return importlib.import_module("main")


class DummyScheduler:
    def __init__(self):
        self.jobs = []
        self.started = False
        self.shutdown_called = False
        self.shutdown_wait = None

    def add_job(self, func, trigger):
        self.jobs.append({"func": func, "trigger": trigger})

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        self.shutdown_called = True
        self.shutdown_wait = wait


def _install_apscheduler_stubs(*, scheduler_cls=DummyScheduler):
    """
    Provide minimal apscheduler module stubs so `main.start_scheduler()` can import them
    even when apscheduler isn't installed in the current interpreter.
    """
    apscheduler_mod = types.ModuleType("apscheduler")
    schedulers_mod = types.ModuleType("apscheduler.schedulers")
    sched_asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    triggers_mod = types.ModuleType("apscheduler.triggers")
    triggers_cron_mod = types.ModuleType("apscheduler.triggers.cron")
    triggers_interval_mod = types.ModuleType("apscheduler.triggers.interval")

    class CronTrigger:
        def __init__(self, *, hour, minute, timezone=None):
            self.hour = hour
            self.minute = minute
            self.timezone = timezone

    class IntervalTrigger:
        def __init__(self, *, minutes):
            self.minutes = minutes

    sched_asyncio_mod.AsyncIOScheduler = scheduler_cls
    triggers_cron_mod.CronTrigger = CronTrigger
    triggers_interval_mod.IntervalTrigger = IntervalTrigger

    sys.modules.setdefault("apscheduler", apscheduler_mod)
    sys.modules.setdefault("apscheduler.schedulers", schedulers_mod)
    sys.modules.setdefault("apscheduler.schedulers.asyncio", sched_asyncio_mod)
    sys.modules.setdefault("apscheduler.triggers", triggers_mod)
    sys.modules.setdefault("apscheduler.triggers.cron", triggers_cron_mod)
    sys.modules.setdefault("apscheduler.triggers.interval", triggers_interval_mod)


@pytest.mark.asyncio
async def test_does_not_start_scheduler_when_enable_scheduler_not_1(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)

    main = _reload_main(monkeypatch)
    await main.start_scheduler()

    assert not hasattr(main.app.state, "scheduler")


@pytest.mark.asyncio
async def test_uses_america_phoenix_timezone_when_available(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ENABLE_SCHEDULER", "1")

    class FakeTz:
        key = "America/Phoenix"

    main = _reload_main(monkeypatch, zoneinfo_zoneinfo_override=lambda _name: FakeTz())
    assert main.PHOENIX_TZ is not None

    _install_apscheduler_stubs(scheduler_cls=DummyScheduler)

    await main.start_scheduler()

    scheduler = main.app.state.scheduler
    assert scheduler.started is True

    scan_jobs = [j for j in scheduler.jobs if j["func"] == main._run_scheduled_scan_job]
    assert len(scan_jobs) == 2
    assert all(getattr(j["trigger"], "timezone", None) == main.PHOENIX_TZ for j in scan_jobs)


@pytest.mark.asyncio
async def test_skips_scheduled_scans_cleanly_if_phoenix_zone_cannot_load(monkeypatch, capsys):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ENABLE_SCHEDULER", "1")

    def _raise_zoneinfo(_name: str):
        raise Exception("ZoneInfo not available")

    main = _reload_main(monkeypatch, zoneinfo_zoneinfo_override=_raise_zoneinfo)
    assert main.PHOENIX_TZ is None

    _install_apscheduler_stubs(scheduler_cls=DummyScheduler)

    await main.start_scheduler()
    scheduler = main.app.state.scheduler

    scan_jobs = [j for j in scheduler.jobs if j["func"] == main._run_scheduled_scan_job]
    assert scan_jobs == []

    out = capsys.readouterr().out
    assert "Failed to load America/Phoenix timezone" in out or "Phoenix timezone unavailable" in out


@pytest.mark.asyncio
async def test_scheduled_scan_job_continues_if_one_sport_scan_throws(monkeypatch):
    main = _reload_main(monkeypatch)

    called = []

    async def fake_get_cached_or_scan(sport, source="unknown"):
        called.append(sport)
        if sport == "bad_sport":
            raise RuntimeError("boom")
        return {"sides": [], "events_fetched": 1, "events_with_both_books": 1}

    import services.odds_api as odds_api
    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ["good1", "bad_sport", "good2"], raising=True)
    monkeypatch.setattr(odds_api, "get_cached_or_scan", fake_get_cached_or_scan, raising=True)

    await main._run_scheduled_scan_job()

    assert called == ["good1", "bad_sport", "good2"]


@pytest.mark.asyncio
async def test_scheduled_scan_job_calls_get_cached_or_scan_for_all_supported_sports(monkeypatch):
    main = _reload_main(monkeypatch)

    called = []

    async def fake_get_cached_or_scan(sport, source="unknown"):
        called.append(sport)
        return {"sides": [1], "events_fetched": 1, "events_with_both_books": 1}

    import services.odds_api as odds_api
    sports = ["s1", "s2", "s3", "s4"]
    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", sports, raising=True)
    monkeypatch.setattr(odds_api, "get_cached_or_scan", fake_get_cached_or_scan, raising=True)

    await main._run_scheduled_scan_job()

    assert called == sports


def test_scheduler_freshness_uses_startup_grace_when_no_success(monkeypatch):
    main = _reload_main(monkeypatch)
    main._init_scheduler_heartbeats()
    main.app.state.scheduler_started_at = datetime.now(UTC).isoformat() + "Z"

    fresh, details = main._check_scheduler_freshness(True)

    assert fresh is True
    for job_name, state in details["jobs"].items():
        assert state["fresh"] is True
        assert state["freshness_reason"] == "waiting_first_run"


def test_scheduler_freshness_fails_if_no_success_past_stale_window(monkeypatch):
    main = _reload_main(monkeypatch)
    main._init_scheduler_heartbeats()
    main.app.state.scheduler_started_at = (datetime.now(UTC) - timedelta(hours=48)).isoformat() + "Z"

    fresh, details = main._check_scheduler_freshness(True)

    assert fresh is False
    assert any(not state["fresh"] for state in details["jobs"].values())
    assert any(state["freshness_reason"] == "stale_no_success" for state in details["jobs"].values())


def test_ops_status_requires_valid_cron_token(monkeypatch):
    main = _reload_main(monkeypatch)
    main._init_ops_status()
    monkeypatch.setenv("CRON_TOKEN", "secret-token")

    with pytest.raises(HTTPException) as exc:
        main.ops_status(x_cron_token="wrong")

    assert exc.value.status_code == 401


def test_ops_status_returns_snapshot_when_token_valid(monkeypatch):
    main = _reload_main(monkeypatch)
    main._init_ops_status()
    monkeypatch.setenv("CRON_TOKEN", "secret-token")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")

    payload = main.ops_status(x_cron_token="secret-token")

    assert "runtime" in payload
    assert "checks" in payload
    assert "ops" in payload
    assert payload["runtime"]["scheduler_expected"] is False
    assert "odds_api_activity" in payload["ops"]
    assert "summary" in payload["ops"]["odds_api_activity"]
    assert "recent_calls" in payload["ops"]["odds_api_activity"]

