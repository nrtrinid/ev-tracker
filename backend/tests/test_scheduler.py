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

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, "kwargs": kwargs})

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
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")

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

    scan_jobs = [j for j in scheduler.jobs if j["func"] == main._run_scheduled_board_drop_job]
    assert len(scan_jobs) == 2
    assert {(j["trigger"].hour, j["trigger"].minute) for j in scan_jobs} == {(10, 30), (15, 30)}
    assert all(getattr(j["trigger"], "timezone", None) == main.PHOENIX_TZ for j in scan_jobs)

    auto_settle_jobs = [j for j in scheduler.jobs if j["func"] == main._run_auto_settler_job]
    assert len(auto_settle_jobs) == 1
    assert getattr(auto_settle_jobs[0]["trigger"], "timezone", None) == main.PHOENIX_TZ
    assert auto_settle_jobs[0]["kwargs"].get("misfire_grace_time") == 3600
    assert auto_settle_jobs[0]["kwargs"].get("coalesce") is True


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

    scan_jobs = [j for j in scheduler.jobs if j["func"] == main._run_scheduled_board_drop_job]
    assert scan_jobs == []

    out = capsys.readouterr().out
    assert "Failed to load America/Phoenix timezone" in out or "Phoenix timezone unavailable" in out


@pytest.mark.asyncio
async def test_scheduled_board_drop_job_runs_daily_board_pipeline(monkeypatch):
    main = _reload_main(monkeypatch)

    called = []

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        called.append(
            {
                "db_is_none": db is None,
                "source": source,
                "scan_label": scan_label,
                "mst_anchor_time": mst_anchor_time,
                "retry_supabase_is_callable": callable(retry_supabase),
                "log_event_is_callable": callable(log_event),
            }
        )
        return {
            "straight_sides": 6,
            "props_sides": 4,
            "featured_games_count": 3,
            "game_line_sports_scanned": ["basketball_nba", "baseball_mlb"],
            "props_events_scanned": 7,
            "game_lines_events_fetched": 2,
            "game_lines_events_with_both_books": 2,
            "game_lines_api_requests_remaining": "91",
            "props_events_fetched": 7,
            "props_events_with_both_books": 6,
            "props_api_requests_remaining": "90",
            "fresh_straight_sides": [],
            "fresh_prop_sides": [],
        }

    import services.daily_board as daily_board

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)

    await main._run_scheduled_board_drop_job()

    assert len(called) == 1
    assert called[0]["source"] == "scheduled_board_drop"
    assert called[0]["scan_label"] in {"Early-Look / Injury-Watch Scan", "Final Board / Bet Placement Scan"}
    assert called[0]["mst_anchor_time"] in {"10:30", "15:30"}
    assert called[0]["retry_supabase_is_callable"] is True
    assert called[0]["log_event_is_callable"] is True


@pytest.mark.asyncio
async def test_scheduled_scan_aliases_use_board_drop_job(monkeypatch):
    main = _reload_main(monkeypatch)

    calls: list[str] = []

    async def _fake_run_scheduled_board_drop_job():
        calls.append("scheduled_board_drop")

    monkeypatch.setattr(main, "_run_scheduled_board_drop_job", _fake_run_scheduled_board_drop_job, raising=True)

    await main._run_scheduled_scan_job()
    await main._run_early_look_scan_job()

    assert calls == ["scheduled_board_drop", "scheduled_board_drop"]


@pytest.mark.asyncio
async def test_scheduled_board_drop_job_timed_ping_mode_sends_single_board_alert(monkeypatch):
    main = _reload_main(monkeypatch)
    monkeypatch.setenv("DISCORD_SCAN_ALERT_MODE", "timed_ping")

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        return {
            "straight_sides": 5,
            "props_sides": 3,
            "featured_games_count": 2,
            "game_line_sports_scanned": ["basketball_nba", "baseball_mlb"],
            "props_events_scanned": 5,
            "game_lines_events_fetched": 2,
            "game_lines_events_with_both_books": 2,
            "game_lines_api_requests_remaining": "99",
            "props_events_fetched": 5,
            "props_events_with_both_books": 4,
            "props_api_requests_remaining": "98",
            "fresh_straight_sides": [],
            "fresh_prop_sides": [],
        }

    import services.daily_board as daily_board

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)

    import services.discord_alerts as discord_alerts

    def _fail_if_edge_alerts_called(_sides):
        raise AssertionError("schedule_alerts should not run in timed_ping mode")

    sent: list[tuple[dict, str]] = []

    async def _fake_send_discord_webhook(payload, message_type="alert"):
        sent.append((payload, message_type))
        return {
            "delivery_status": "delivered",
            "status_code": 204,
            "route_kind": "alert_dedicated",
            "webhook_source": "DISCORD_ALERT_WEBHOOK_URL",
        }

    monkeypatch.setattr(discord_alerts, "schedule_alerts", _fail_if_edge_alerts_called, raising=True)
    monkeypatch.setattr(discord_alerts, "send_discord_webhook", _fake_send_discord_webhook, raising=True)

    await main._run_scheduled_board_drop_job()

    assert len(sent) == 1
    payload, message_type = sent[0]
    assert message_type == "alert"
    assert payload["embeds"][0]["title"] == "Trusted Beta Board Live"

    snapshot = main.app.state.ops_status["last_scheduler_scan"]
    assert snapshot["scan_alert_mode"] == "timed_ping"
    assert snapshot["alerts_scheduled"] == 0
    assert snapshot["straight_sides"] == 5
    assert snapshot["props_sides"] == 3
    assert snapshot["board_alert_attempted"] is True
    assert snapshot["board_alert_delivery_status"] == "delivered"
    assert snapshot["board_alert_http_status"] == 204
    assert snapshot["scan_window"]["anchor_time_mst"] in {"10:30", "15:30"}


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


def test_app_role_normalization(monkeypatch):
    main = _reload_main(monkeypatch)

    monkeypatch.delenv("APP_ROLE", raising=False)
    assert main._app_role() == "api"

    monkeypatch.setenv("APP_ROLE", "scheduler")
    assert main._app_role() == "scheduler"

    monkeypatch.setenv("APP_ROLE", "api")
    assert main._app_role() == "api"

    monkeypatch.setenv("APP_ROLE", "unexpected")
    assert main._app_role() == "api"


def test_paper_autolog_env_variables(monkeypatch):
    main = _reload_main(monkeypatch)

    monkeypatch.delenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG", raising=False)
    monkeypatch.delenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID", raising=False)

    assert main._is_paper_experiment_autolog_enabled() is False
    assert main._paper_experiment_account_user_id() == ""

    monkeypatch.setenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG", "1")
    monkeypatch.setenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID", "user-a")
    assert main._is_paper_experiment_autolog_enabled() is True
    assert main._paper_experiment_account_user_id() == "user-a"


def test_validate_environment_warns_when_autolog_enabled_without_user_id(monkeypatch):
    main = _reload_main(monkeypatch)

    monkeypatch.setenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG", "1")
    monkeypatch.delenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID", raising=False)

    captured = []

    def _capture(event: str, level: str = "info", **fields):
        captured.append((event, level, fields))

    monkeypatch.setattr(main, "_log_event", _capture, raising=True)

    main._validate_environment()

    warning_events = [e for e, _level, _f in captured]
    assert "startup.env_paper_autolog_without_user_id" in warning_events


def test_validate_environment_warns_when_scheduler_enabled_without_discord_alert_webhook(monkeypatch):
    main = _reload_main(monkeypatch)

    monkeypatch.setenv("ENABLE_SCHEDULER", "1")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)

    captured = []

    def _capture(event: str, level: str = "info", **fields):
        captured.append((event, level, fields))

    monkeypatch.setattr(main, "_log_event", _capture, raising=True)

    main._validate_environment()

    warning_events = [e for e, _level, _f in captured]
    assert "startup.env_discord_alert_webhook_missing" in warning_events


def test_annotate_sides_with_duplicate_state_uses_pending_best_price(monkeypatch):
    main = _reload_main(monkeypatch)

    class _FakeQuery:
        def __init__(self, data):
            self._data = data

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def execute(self):
            return types.SimpleNamespace(data=self._data)

    class _FakeDB:
        def __init__(self, data):
            self._data = data

        def table(self, _name):
            return _FakeQuery(self._data)

    pending_rows = [
        {
            "id": "bet-old",
            "odds_american": 120,
            "market": "ML",
            "sportsbook": "DraftKings",
            "commence_time": "2026-03-19T20:00:00Z",
            "clv_team": "Lakers",
            "clv_sport_key": "basketball_nba",
        },
        {
            "id": "bet-best",
            "odds_american": 130,
            "market": "ML",
            "sportsbook": "DraftKings",
            "commence_time": "2026-03-19T20:00:00Z",
            "clv_team": "Lakers",
            "clv_sport_key": "basketball_nba",
        },
    ]

    db = _FakeDB(pending_rows)

    sides = [
        {
            "sport": "basketball_nba",
            "commence_time": "2026-03-19T20:00:00Z",
            "team": "Lakers",
            "sportsbook": "DraftKings",
            "book_odds": 125,
        },
        {
            "sport": "basketball_nba",
            "commence_time": "2026-03-19T20:00:00Z",
            "team": "Lakers",
            "sportsbook": "DraftKings",
            "book_odds": 145,
        },
        {
            "sport": "basketball_nba",
            "commence_time": "2026-03-19T21:00:00Z",
            "team": "Celtics",
            "sportsbook": "DraftKings",
            "book_odds": 140,
        },
    ]

    annotated = main._annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert annotated[0]["scanner_duplicate_state"] == "already_logged"
    assert annotated[0]["best_logged_odds_american"] == 130
    assert annotated[0]["matched_pending_bet_id"] == "bet-best"

    assert annotated[1]["scanner_duplicate_state"] == "better_now"
    assert annotated[1]["best_logged_odds_american"] == 130

    assert annotated[2]["scanner_duplicate_state"] == "new"
    assert annotated[2]["matched_pending_bet_id"] is None


@pytest.mark.asyncio
async def test_longshot_autolog_guardrails(monkeypatch):
    main = _reload_main(monkeypatch)

    class _FakeQuery:
        def __init__(self, db):
            self._db = db
            self._eq_filters = []
            self._in_filters = []

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, field, value):
            self._eq_filters.append((field, value))
            return self

        def in_(self, field, values):
            self._in_filters.append((field, set(values)))
            return self

        def limit(self, _n):
            return self

        def insert(self, payload):
            self._db.rows.append(payload)
            return self

        def execute(self):
            rows = list(self._db.rows)
            for field, value in self._eq_filters:
                rows = [r for r in rows if r.get(field) == value]
            for field, values in self._in_filters:
                rows = [r for r in rows if r.get(field) in values]
            return types.SimpleNamespace(data=rows)

    class _FakeDB:
        def __init__(self):
            self.rows = []

        def table(self, _name):
            return _FakeQuery(self)

    db = _FakeDB()
    sides = [
        {
            "sport": "basketball_nba",
            "ev_percentage": 1.0,
            "book_odds": 120,
            "commence_time": "2026-03-19T20:00:00Z",
            "team": "Lakers",
            "sportsbook": "DraftKings",
            "pinnacle_odds": 110,
            "true_prob": 0.51,
        }
    ]

    monkeypatch.setenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG", "0")
    monkeypatch.setenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID", "user-a")
    out = await main._run_longshot_autolog_for_sides(db, run_id="run-1", sides=sides)
    assert out["enabled"] is False
    assert len(db.rows) == 0

    monkeypatch.setenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG", "1")
    monkeypatch.delenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID", raising=False)
    out = await main._run_longshot_autolog_for_sides(db, run_id="run-2", sides=sides)
    assert out["enabled"] is True
    assert out["configured"] is False
    assert len(db.rows) == 0


@pytest.mark.asyncio
async def test_longshot_autolog_caps_and_idempotency(monkeypatch):
    main = _reload_main(monkeypatch)

    class _FakeQuery:
        def __init__(self, db):
            self._db = db
            self._eq_filters = []
            self._in_filters = []

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, field, value):
            self._eq_filters.append((field, value))
            return self

        def in_(self, field, values):
            self._in_filters.append((field, set(values)))
            return self

        def limit(self, _n):
            return self

        def insert(self, payload):
            payload = dict(payload)
            payload.setdefault("id", f"insert-{len(self._db.rows)+1}")
            self._db.rows.append(payload)
            return self

        def execute(self):
            rows = list(self._db.rows)
            for field, value in self._eq_filters:
                rows = [r for r in rows if r.get(field) == value]
            for field, values in self._in_filters:
                rows = [r for r in rows if r.get(field) in values]
            return types.SimpleNamespace(data=rows)

    class _FakeDB:
        def __init__(self):
            self.rows = []

        def table(self, _name):
            return _FakeQuery(self)

    db = _FakeDB()

    monkeypatch.setenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG", "1")
    monkeypatch.setenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID", "user-a")

    # 3 low-edge candidates and 4 high-edge candidates. Cap should keep at most 2 low + 3 high.
    sides = []
    for i in range(3):
        sides.append(
            {
                "sport": "basketball_nba",
                "ev_percentage": 1.0,
                "book_odds": 110 + i,
                "commence_time": f"2026-03-19T2{i}:00:00Z",
                "team": f"LowTeam{i}",
                "sportsbook": "DraftKings",
                "pinnacle_odds": 100,
                "true_prob": 0.5,
            }
        )
    for i in range(4):
        sides.append(
            {
                "sport": "basketball_ncaab",
                "ev_percentage": 12.0,
                "book_odds": 700 + i,
                "commence_time": f"2026-03-20T2{i}:00:00Z",
                "team": f"HighTeam{i}",
                "sportsbook": "FanDuel",
                "pinnacle_odds": 650,
                "true_prob": 0.2,
            }
        )

    out = await main._run_longshot_autolog_for_sides(db, run_id="run-1", sides=sides)
    assert out["inserted_total"] == 5
    assert out["inserted_by_cohort"][main.LOW_EDGE_COHORT] == 2
    assert out["inserted_by_cohort"][main.HIGH_EDGE_COHORT] == 3

    # Re-run with same run_id and sides: idempotency avoids duplicate inserts for already-written keys,
    # but remaining eligible keys can still be inserted on later runs because of per-run caps.
    out2 = await main._run_longshot_autolog_for_sides(db, run_id="run-1", sides=sides)
    assert out2["inserted_total"] == 2

    # Third run should be fully exhausted for this side set.
    out3 = await main._run_longshot_autolog_for_sides(db, run_id="run-1", sides=sides)
    assert out3["inserted_total"] == 0


@pytest.mark.asyncio
async def test_scan_markets_returns_backend_duplicate_state_enum(monkeypatch):
    main = _reload_main(monkeypatch)

    class _FakeQuery:
        def __init__(self, table_name, db):
            self._table = table_name
            self._db = db
            self._eq_filters = []

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, field, value):
            self._eq_filters.append((field, value))
            return self

        def limit(self, _n):
            return self

        def upsert(self, payload, **_kwargs):
            if self._table == "global_scan_cache":
                self._db.cache_payload = payload.get("payload")
            return self

        def execute(self):
            if self._table == "bets":
                rows = list(self._db.pending_rows)
                for field, value in self._eq_filters:
                    rows = [r for r in rows if r.get(field) == value]
                return types.SimpleNamespace(data=rows)
            if self._table == "global_scan_cache":
                return types.SimpleNamespace(data=[{"payload": self._db.cache_payload}] if self._db.cache_payload else [])
            return types.SimpleNamespace(data=[])

    class _FakeDB:
        def __init__(self, pending_rows):
            self.pending_rows = pending_rows
            self.cache_payload = None

        def table(self, name):
            return _FakeQuery(name, self)

    db = _FakeDB(
        pending_rows=[
            {
                "id": "pending-1",
                "user_id": "user-1",
                "result": "pending",
                "market": "ML",
                "odds_american": 120,
                "sportsbook": "DraftKings",
                "commence_time": "2026-03-19T20:00:00Z",
                "clv_team": "Lakers",
                "clv_sport_key": "basketball_nba",
            }
        ]
    )

    monkeypatch.setattr(main, "get_db", lambda: db, raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f, retries=2: f(), raising=True)

    import services.odds_api as odds_api

    async def _fake_cached_or_scan(_sport, source="unknown"):
        return {
            "sides": [
                {
                    "sportsbook": "DraftKings",
                    "sport": "basketball_nba",
                    "event": "Lakers @ Celtics",
                    "commence_time": "2026-03-19T20:00:00Z",
                    "team": "Lakers",
                    "pinnacle_odds": 110,
                    "book_odds": 130,
                    "true_prob": 0.52,
                    "base_kelly_fraction": 0.01,
                    "book_decimal": 2.3,
                    "ev_percentage": 2.0,
                },
                {
                    "sportsbook": "DraftKings",
                    "sport": "basketball_nba",
                    "event": "Knicks @ Bulls",
                    "commence_time": "2026-03-19T21:00:00Z",
                    "team": "Knicks",
                    "pinnacle_odds": 105,
                    "book_odds": 120,
                    "true_prob": 0.5,
                    "base_kelly_fraction": 0.01,
                    "book_decimal": 2.2,
                    "ev_percentage": 1.0,
                },
            ],
            "events_fetched": 2,
            "events_with_both_books": 2,
            "api_requests_remaining": "100",
            "fetched_at": 1_700_000_000,
        }

    monkeypatch.setattr(odds_api, "get_cached_or_scan", _fake_cached_or_scan, raising=True)
    monkeypatch.setattr(odds_api, "SUPPORTED_SPORTS", ["basketball_nba"], raising=True)

    response = await main.scan_markets(sport="basketball_nba", user={"id": "user-1"})

    assert len(response.sides) == 2
    assert response.sides[0].scanner_duplicate_state == "better_now"
    assert response.sides[0].best_logged_odds_american == 120
    assert response.sides[0].matched_pending_bet_id == "pending-1"
    assert response.sides[1].scanner_duplicate_state == "new"


@pytest.mark.asyncio
async def test_scan_latest_enriches_duplicate_state_from_cached_payload(monkeypatch):
    main = _reload_main(monkeypatch)

    class _FakeQuery:
        def __init__(self, table_name, db):
            self._table = table_name
            self._db = db
            self._eq_filters = []

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, field, value):
            self._eq_filters.append((field, value))
            return self

        def limit(self, _n):
            return self

        def execute(self):
            if self._table == "global_scan_cache":
                return types.SimpleNamespace(data=[{"payload": self._db.cache_payload}])
            if self._table == "bets":
                rows = list(self._db.pending_rows)
                for field, value in self._eq_filters:
                    rows = [r for r in rows if r.get(field) == value]
                return types.SimpleNamespace(data=rows)
            return types.SimpleNamespace(data=[])

    class _FakeDB:
        def __init__(self):
            self.pending_rows = [
                {
                    "id": "pending-1",
                    "user_id": "user-1",
                    "result": "pending",
                    "market": "ML",
                    "odds_american": 120,
                    "sportsbook": "DraftKings",
                    "commence_time": "2026-03-19T20:00:00Z",
                    "clv_team": "Lakers",
                    "clv_sport_key": "basketball_nba",
                }
            ]
            self.cache_payload = {
                "sport": "all",
                "sides": [
                    {
                        "sportsbook": "DraftKings",
                        "sport": "basketball_nba",
                        "event": "Lakers @ Celtics",
                        "commence_time": "2026-03-19T20:00:00Z",
                        "team": "Lakers",
                        "pinnacle_odds": 110,
                        "book_odds": 130,
                        "true_prob": 0.52,
                        "base_kelly_fraction": 0.01,
                        "book_decimal": 2.3,
                        "ev_percentage": 2.0,
                    }
                ],
                "events_fetched": 1,
                "events_with_both_books": 1,
                "api_requests_remaining": "100",
                "scanned_at": "2026-03-19T19:55:00Z",
            }

        def table(self, name):
            return _FakeQuery(name, self)

    db = _FakeDB()
    monkeypatch.setattr(main, "get_db", lambda: db, raising=True)
    monkeypatch.setattr(main, "_retry_supabase", lambda f, retries=2: f(), raising=True)

    payload = await main.scan_latest(user={"id": "user-1"})
    assert payload["sides"][0]["scanner_duplicate_state"] == "better_now"
    assert payload["sides"][0]["best_logged_odds_american"] == 120


@pytest.mark.asyncio
async def test_scheduled_board_drop_ops_status_includes_autolog_summary(monkeypatch):
    main = _reload_main(monkeypatch)

    async def _fake_run_daily_board_drop(*, db, source, scan_label, mst_anchor_time, retry_supabase, log_event):
        return {
            "straight_sides": 0,
            "props_sides": 0,
            "featured_games_count": 0,
            "game_line_sports_scanned": ["basketball_nba", "baseball_mlb"],
            "props_events_scanned": 0,
            "game_lines_events_fetched": 0,
            "game_lines_events_with_both_books": 0,
            "game_lines_api_requests_remaining": "99",
            "props_events_fetched": 0,
            "props_events_with_both_books": 0,
            "props_api_requests_remaining": "99",
            "fresh_straight_sides": [],
            "fresh_prop_sides": [],
        }

    import services.daily_board as daily_board

    monkeypatch.setattr(daily_board, "run_daily_board_drop", _fake_run_daily_board_drop, raising=True)

    async def _fake_autolog(db, *, run_id: str, sides: list[dict]):
        return {
            "enabled": True,
            "configured": True,
            "run_id": run_id,
            "inserted_total": 0,
            "selected_by_cohort": {main.LOW_EDGE_COHORT: 0, main.HIGH_EDGE_COHORT: 0},
        }

    monkeypatch.setattr(main, "_run_longshot_autolog_for_sides", _fake_autolog, raising=True)

    await main._run_scheduled_board_drop_job()

    snapshot = main.app.state.ops_status["last_scheduler_scan"]
    assert isinstance(snapshot, dict)
    assert "autolog_summary" in snapshot
    assert snapshot["autolog_summary"]["enabled"] is True
    assert snapshot["autolog_summary"]["configured"] is True

