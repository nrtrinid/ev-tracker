from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from .test_utils import ensure_supabase_stub, reload_service_module


class _FakeTable:
    def __init__(self, table_name: str, tables: dict[str, list[dict]]):
        self.table_name = table_name
        self.tables = tables
        self._mode = "select"
        self._eq_filters: list[tuple[str, object]] = []
        self._lt_filters: list[tuple[str, object]] = []
        self._order_field: str | None = None
        self._order_desc = False
        self._limit: int | None = None
        self._insert_payload = None

    def select(self, *_args, **_kwargs):
        self._mode = "select"
        return self

    def eq(self, field, value):
        self._eq_filters.append((field, value))
        return self

    def lt(self, field, value):
        self._lt_filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self._order_field = field
        self._order_desc = bool(desc)
        return self

    def limit(self, count):
        self._limit = count
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._insert_payload = payload
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def execute(self):
        rows = self.tables.setdefault(self.table_name, [])

        if self._mode == "insert":
            payloads = self._insert_payload if isinstance(self._insert_payload, list) else [self._insert_payload]
            inserted = []
            for payload in payloads:
                row = dict(payload)
                row.setdefault("id", f"{self.table_name}-{len(rows) + 1}")
                row.setdefault("created_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
                rows.append(row)
                inserted.append(row)
            return SimpleNamespace(data=inserted)

        if self._mode == "delete":
            survivors = []
            deleted = []
            for row in rows:
                should_delete = True
                for field, value in self._lt_filters:
                    row_value = row.get(field)
                    if row_value is None or not (str(row_value) < str(value)):
                        should_delete = False
                        break
                if should_delete:
                    deleted.append(row)
                else:
                    survivors.append(row)
            self.tables[self.table_name] = survivors
            return SimpleNamespace(data=deleted)

        result = list(rows)
        for field, value in self._eq_filters:
            result = [row for row in result if row.get(field) == value]
        if self._order_field is not None:
            result = sorted(
                result,
                key=lambda row: row.get(self._order_field) or "",
                reverse=self._order_desc,
            )
        if self._limit is not None:
            result = result[: self._limit]
        return SimpleNamespace(data=result)


class _FakeDB:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables = tables or {}

    def table(self, name: str):
        return _FakeTable(name, self.tables)


def _iso(minutes_ago: int = 0, *, days_ago: int = 0) -> str:
    return (
        datetime.now(UTC) - timedelta(minutes=minutes_ago, days=days_ago)
    ).isoformat().replace("+00:00", "Z")


def test_load_ops_status_snapshot_prefers_durable_rows_and_rebuilds_activity():
    ensure_supabase_stub()
    mod = reload_service_module("ops_history")

    db = _FakeDB(
        {
            "ops_job_runs": [
                {
                    "job_kind": "manual_scan",
                    "source": "manual_scan",
                    "status": "completed",
                    "captured_at": _iso(minutes_ago=4),
                    "surface": "player_props",
                    "requested_sport": "basketball_nba",
                    "events_fetched": 12,
                    "events_with_both_books": 9,
                    "total_sides": 31,
                    "api_requests_remaining": "211",
                },
                {
                    "job_kind": "jit_clv",
                    "source": "scheduler",
                    "status": "completed",
                    "run_id": "jit-1",
                    "captured_at": _iso(minutes_ago=6),
                    "started_at": _iso(minutes_ago=7),
                    "finished_at": _iso(minutes_ago=6),
                    "duration_ms": 222.0,
                    "meta": {"updated": 4},
                },
                {
                    "job_kind": "scheduled_scan",
                    "source": "scheduler",
                    "status": "completed",
                    "run_id": "scheduled-1",
                    "captured_at": _iso(minutes_ago=8),
                    "started_at": _iso(minutes_ago=9),
                    "finished_at": _iso(minutes_ago=8),
                    "duration_ms": 980.5,
                    "total_sides": 44,
                    "alerts_scheduled": 3,
                    "hard_errors": 0,
                    "meta": {
                        "autolog_summary": {"enabled": False},
                        "scan_window": {
                            "label": "Early-Look / Injury-Watch Scan",
                            "anchor_timezone": "America/Phoenix",
                            "anchor_time_mst": "10:30",
                        },
                        "board_alert": {
                            "attempted": True,
                            "delivery_status": "failed",
                            "status_code": 429,
                            "error": "rate limited",
                        },
                    },
                },
                {
                    "job_kind": "ops_trigger_scan",
                    "source": "ops_trigger",
                    "status": "completed_with_errors",
                    "run_id": "ops-1",
                    "captured_at": _iso(minutes_ago=12),
                    "started_at": _iso(minutes_ago=13),
                    "finished_at": _iso(minutes_ago=12),
                    "duration_ms": 1200.0,
                    "total_sides": 18,
                    "alerts_scheduled": 0,
                    "error_count": 1,
                    "errors": [{"sport": "basketball_nba", "error": "boom"}],
                },
                {
                    "job_kind": "auto_settle",
                    "source": "scheduler",
                    "status": "completed",
                    "run_id": "settle-1",
                    "captured_at": _iso(minutes_ago=16),
                    "started_at": _iso(minutes_ago=17),
                    "finished_at": _iso(minutes_ago=16),
                    "duration_ms": 456.0,
                    "settled": 5,
                    "skipped_totals": {"missing_score": 2},
                    "meta": {"sports": [{"sport_key": "basketball_nba", "bets_considered": 9}]},
                },
                {
                    "job_kind": "readiness_failure",
                    "source": "readiness",
                    "status": "failed",
                    "captured_at": _iso(minutes_ago=20),
                    "checks": {"db_connectivity": False, "scheduler_freshness": True},
                    "meta": {"db_error": "database timeout"},
                },
            ],
            "odds_api_activity_events": [
                {
                    "activity_kind": "raw_call",
                    "captured_at": _iso(minutes_ago=2),
                    "source": "manual_scan",
                    "endpoint": "/sports/basketball_nba/odds",
                    "sport": "basketball_nba",
                    "cache_hit": False,
                    "outbound_call_made": True,
                    "status_code": 200,
                    "duration_ms": 123.4,
                    "api_requests_remaining": "210",
                    "error_type": None,
                    "error_message": None,
                },
                {
                    "activity_kind": "raw_call",
                    "captured_at": _iso(minutes_ago=3),
                    "source": "manual_scan",
                    "endpoint": "/sports/basketball_nba/scores",
                    "sport": "basketball_nba",
                    "cache_hit": False,
                    "outbound_call_made": True,
                    "status_code": 502,
                    "duration_ms": 111.0,
                    "api_requests_remaining": "209",
                    "error_type": "HTTPStatusError",
                    "error_message": "bad gateway",
                },
                {
                    "activity_kind": "scan_detail",
                    "captured_at": _iso(minutes_ago=5),
                    "scan_session_id": "manual-1",
                    "source": "manual_scan",
                    "surface": "straight_bets",
                    "scan_scope": "single_sport",
                    "requested_sport": "basketball_nba",
                    "sport": "basketball_nba",
                    "actor_label": "ops@example.com",
                    "run_id": None,
                    "cache_hit": False,
                    "outbound_call_made": True,
                    "duration_ms": 250.0,
                    "events_fetched": 4,
                    "events_with_both_books": 3,
                    "sides_count": 8,
                    "api_requests_remaining": "210",
                    "status_code": 200,
                    "error_type": None,
                    "error_message": None,
                },
                {
                    "activity_kind": "scan_detail",
                    "captured_at": _iso(minutes_ago=4),
                    "scan_session_id": "manual-1",
                    "source": "manual_scan",
                    "surface": "straight_bets",
                    "scan_scope": "single_sport",
                    "requested_sport": "basketball_nba",
                    "sport": "basketball_ncaab",
                    "actor_label": "ops@example.com",
                    "run_id": None,
                    "cache_hit": True,
                    "outbound_call_made": False,
                    "duration_ms": 0.0,
                    "events_fetched": 2,
                    "events_with_both_books": 1,
                    "sides_count": 4,
                    "api_requests_remaining": "210",
                    "status_code": 200,
                    "error_type": None,
                    "error_message": None,
                },
            ],
        }
    )

    snapshot = mod.load_ops_status_snapshot(
        db=db,
        retry_supabase=lambda f: f(),
        log_event=None,
        fallback_ops_status={"last_manual_scan": {"sport": "fallback"}},
        fallback_odds_api_activity=mod.build_empty_odds_api_activity_snapshot(),
    )

    assert snapshot["last_manual_scan"]["sport"] == "basketball_nba"
    assert snapshot["last_jit_clv"]["run_id"] == "jit-1"
    assert snapshot["last_jit_clv"]["updated"] == 4
    assert snapshot["last_manual_scan"]["total_sides"] == 31
    assert snapshot["last_scheduler_scan"]["run_id"] == "scheduled-1"
    assert snapshot["last_scheduler_scan"]["autolog_summary"] == {"enabled": False}
    assert snapshot["last_scheduler_scan"]["scan_window"]["anchor_time_mst"] == "10:30"
    assert snapshot["last_scheduler_scan"]["board_alert"]["delivery_status"] == "failed"
    assert snapshot["last_scheduler_scan"]["board_alert_attempted"] is True
    assert snapshot["last_scheduler_scan"]["board_alert_http_status"] == 429
    assert snapshot["last_scheduler_scan"]["board_alert_error"] == "rate limited"
    assert snapshot["last_ops_trigger_scan"]["error_count"] == 1
    assert snapshot["last_auto_settle"]["settled"] == 5
    assert snapshot["last_auto_settle_summary"]["skipped_totals"] == {"missing_score": 2}
    assert snapshot["last_readiness_failure"]["db_error"] == "database timeout"
    assert snapshot["odds_api_activity"]["summary"]["calls_last_hour"] == 2
    assert snapshot["odds_api_activity"]["summary"]["errors_last_hour"] == 1
    assert snapshot["odds_api_activity"]["recent_scans"][0]["scan_session_id"] == "manual-1"
    assert snapshot["odds_api_activity"]["recent_scans"][0]["total_sides"] == 12
    assert snapshot["odds_api_activity"]["recent_calls"][0]["endpoint"] == "/sports/basketball_nba/odds"


def test_load_ops_status_snapshot_falls_back_cleanly_on_query_failure():
    ensure_supabase_stub()
    mod = reload_service_module("ops_history")

    class _BrokenDB:
        def table(self, _name):
            raise RuntimeError("db unavailable")

    fallback_activity = {
        "summary": {
            "calls_last_hour": 7,
            "errors_last_hour": 2,
            "last_success_at": "2026-03-20T17:54:00Z",
            "last_error_at": "2026-03-20T17:56:00Z",
        },
        "recent_scans": [],
        "recent_calls": [],
    }
    fallback_ops = {
        "last_manual_scan": {"sport": "all", "total_sides": 12},
        "last_readiness_failure": {"captured_at": "2026-03-20T17:58:00Z"},
    }

    snapshot = mod.load_ops_status_snapshot(
        db=_BrokenDB(),
        retry_supabase=lambda f: f(),
        log_event=None,
        fallback_ops_status=fallback_ops,
        fallback_odds_api_activity=fallback_activity,
    )

    assert snapshot["last_manual_scan"] == {"sport": "all", "total_sides": 12}
    assert snapshot["last_readiness_failure"] == {"captured_at": "2026-03-20T17:58:00Z"}
    assert snapshot["odds_api_activity"] == fallback_activity


def test_persist_helpers_are_best_effort_and_prune_old_rows():
    ensure_supabase_stub()
    mod = reload_service_module("ops_history")
    mod._LAST_PRUNE_ATTEMPT_MONOTONIC = 0.0

    db = _FakeDB(
        {
            "ops_job_runs": [
                {
                    "job_kind": "manual_scan",
                    "source": "manual_scan",
                    "status": "completed",
                    "captured_at": _iso(days_ago=31),
                }
            ],
            "odds_api_activity_events": [
                {
                    "activity_kind": "raw_call",
                    "source": "manual_scan",
                    "captured_at": _iso(days_ago=31),
                }
            ],
        }
    )

    mod.persist_ops_job_run(
        job_kind="manual_scan",
        source="manual_scan",
        status="completed",
        captured_at=_iso(minutes_ago=1),
        db=db,
        retry_supabase=lambda f: f(),
        log_event=None,
        total_sides=9,
    )
    mod.persist_odds_api_activity_event(
        activity_kind="raw_call",
        source="manual_scan",
        captured_at=_iso(minutes_ago=1),
        db=db,
        retry_supabase=lambda f: f(),
        log_event=None,
        endpoint="/sports/basketball_nba/odds",
        sport="basketball_nba",
    )

    assert len(db.tables["ops_job_runs"]) == 1
    assert db.tables["ops_job_runs"][0]["total_sides"] == 9
    assert len(db.tables["odds_api_activity_events"]) == 1
    assert db.tables["odds_api_activity_events"][0]["endpoint"] == "/sports/basketball_nba/odds"
