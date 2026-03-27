import copy
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from database import get_db


OPS_JOB_RUNS_TABLE = "ops_job_runs"
ODDS_API_ACTIVITY_EVENTS_TABLE = "odds_api_activity_events"
OPS_HISTORY_RETENTION_DAYS = 30
OPS_HISTORY_PRUNE_INTERVAL_SECONDS = 6 * 60 * 60
RECENT_CALL_LIMIT = 50
RECENT_SCAN_SESSION_LIMIT = 18
RECENT_RAW_CALL_QUERY_LIMIT = 200
RECENT_SCAN_DETAIL_QUERY_LIMIT = 200
BOARD_DROP_SOURCES = {"scheduled_board_drop", "ops_trigger_board_drop", "cron_board_drop"}

_PRUNE_LOCK = threading.Lock()
_LAST_PRUNE_ATTEMPT_MONOTONIC = 0.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_empty_odds_api_activity_snapshot() -> dict[str, Any]:
    return {
        "summary": {
            "calls_last_hour": 0,
            "errors_last_hour": 0,
            "last_success_at": None,
            "last_error_at": None,
        },
        "recent_scans": [],
        "recent_calls": [],
    }


def build_empty_ops_status() -> dict[str, Any]:
    return {
        "last_scheduler_scan": None,
        "last_ops_trigger_scan": None,
        "last_manual_scan": None,
        "last_auto_settle": None,
        "last_auto_settle_summary": None,
        "last_readiness_failure": None,
        "odds_api_activity": build_empty_odds_api_activity_snapshot(),
    }


def _log_warning(
    log_event: Callable[..., None] | None,
    event_name: str,
    **kwargs,
) -> None:
    if log_event is None:
        return
    try:
        log_event(event_name, level="warning", **kwargs)
    except Exception:
        return


def _resolve_db(db: Any | None) -> Any | None:
    if db is not None:
        return db
    try:
        return get_db()
    except Exception:
        return None


def _run_query(
    operation: Callable[[], Any],
    *,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
) -> Any:
    if retry_supabase is not None:
        return retry_supabase(operation)
    return operation()


def _maybe_prune_ops_history(
    *,
    db: Any | None,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    log_event: Callable[..., None] | None,
) -> None:
    global _LAST_PRUNE_ATTEMPT_MONOTONIC

    now = time.monotonic()
    with _PRUNE_LOCK:
        if (
            _LAST_PRUNE_ATTEMPT_MONOTONIC > 0
            and now - _LAST_PRUNE_ATTEMPT_MONOTONIC < OPS_HISTORY_PRUNE_INTERVAL_SECONDS
        ):
            return
        _LAST_PRUNE_ATTEMPT_MONOTONIC = now

    resolved_db = _resolve_db(db)
    if resolved_db is None:
        return

    cutoff = (
        datetime.now(UTC) - timedelta(days=OPS_HISTORY_RETENTION_DAYS)
    ).isoformat().replace("+00:00", "Z")

    for table_name in (OPS_JOB_RUNS_TABLE, ODDS_API_ACTIVITY_EVENTS_TABLE):
        try:
            _run_query(
                lambda table_name=table_name: (
                    resolved_db.table(table_name).delete().lt("captured_at", cutoff).execute()
                ),
                retry_supabase=retry_supabase,
            )
        except Exception as exc:
            _log_warning(
                log_event,
                "ops_history.prune_failed",
                table=table_name,
                error_class=type(exc).__name__,
                error=str(exc),
            )


def persist_ops_job_run(
    *,
    job_kind: str,
    source: str,
    status: str,
    db: Any | None = None,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
    log_event: Callable[..., None] | None = None,
    run_id: str | None = None,
    scan_session_id: str | None = None,
    surface: str | None = None,
    scan_scope: str | None = None,
    requested_sport: str | None = None,
    captured_at: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_ms: float | int | None = None,
    events_fetched: int | None = None,
    events_with_both_books: int | None = None,
    total_sides: int | None = None,
    alerts_scheduled: int | None = None,
    hard_errors: int | None = None,
    error_count: int | None = None,
    settled: int | None = None,
    api_requests_remaining: str | int | None = None,
    checks: dict[str, Any] | None = None,
    skipped_totals: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    resolved_db = _resolve_db(db)
    if resolved_db is None:
        return

    payload = {
        "job_kind": job_kind,
        "source": source,
        "status": status,
        "run_id": run_id,
        "scan_session_id": scan_session_id,
        "surface": surface,
        "scan_scope": scan_scope,
        "requested_sport": requested_sport,
        "captured_at": captured_at or finished_at or started_at or _utc_now_iso(),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round(float(duration_ms), 2) if isinstance(duration_ms, (int, float)) else None,
        "events_fetched": events_fetched,
        "events_with_both_books": events_with_both_books,
        "total_sides": total_sides,
        "alerts_scheduled": alerts_scheduled,
        "hard_errors": hard_errors,
        "error_count": error_count,
        "settled": settled,
        "api_requests_remaining": str(api_requests_remaining) if api_requests_remaining is not None else None,
        "checks": checks,
        "skipped_totals": skipped_totals,
        "errors": errors,
        "meta": meta,
    }

    try:
        _run_query(
            lambda: resolved_db.table(OPS_JOB_RUNS_TABLE).insert(payload).execute(),
            retry_supabase=retry_supabase,
        )
    except Exception as exc:
        _log_warning(
            log_event,
            "ops_history.persist_job_run_failed",
            table=OPS_JOB_RUNS_TABLE,
            job_kind=job_kind,
            source=source,
            error_class=type(exc).__name__,
            error=str(exc),
        )
        return

    _maybe_prune_ops_history(db=resolved_db, retry_supabase=retry_supabase, log_event=log_event)


def persist_odds_api_activity_event(
    *,
    activity_kind: str,
    source: str,
    db: Any | None = None,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
    log_event: Callable[..., None] | None = None,
    captured_at: str | None = None,
    scan_session_id: str | None = None,
    surface: str | None = None,
    scan_scope: str | None = None,
    requested_sport: str | None = None,
    sport: str | None = None,
    actor_label: str | None = None,
    run_id: str | None = None,
    endpoint: str | None = None,
    cache_hit: bool | None = None,
    outbound_call_made: bool | None = None,
    duration_ms: float | int | None = None,
    events_fetched: int | None = None,
    events_with_both_books: int | None = None,
    sides_count: int | None = None,
    api_requests_remaining: str | int | None = None,
    credits_used_last: int | None = None,
    status_code: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    resolved_db = _resolve_db(db)
    if resolved_db is None:
        return

    payload = {
        "activity_kind": activity_kind,
        "captured_at": captured_at or _utc_now_iso(),
        "scan_session_id": scan_session_id,
        "source": source,
        "surface": surface,
        "scan_scope": scan_scope,
        "requested_sport": requested_sport,
        "sport": sport,
        "actor_label": actor_label,
        "run_id": run_id,
        "endpoint": endpoint,
        "cache_hit": cache_hit,
        "outbound_call_made": outbound_call_made,
        "duration_ms": round(float(duration_ms), 2) if isinstance(duration_ms, (int, float)) else None,
        "events_fetched": events_fetched,
        "events_with_both_books": events_with_both_books,
        "sides_count": sides_count,
        "api_requests_remaining": str(api_requests_remaining) if api_requests_remaining is not None else None,
        "credits_used_last": credits_used_last,
        "status_code": status_code,
        "error_type": error_type,
        "error_message": error_message,
    }

    try:
        _run_query(
            lambda: resolved_db.table(ODDS_API_ACTIVITY_EVENTS_TABLE).insert(payload).execute(),
            retry_supabase=retry_supabase,
        )
    except Exception as exc:
        _log_warning(
            log_event,
            "ops_history.persist_activity_failed",
            table=ODDS_API_ACTIVITY_EVENTS_TABLE,
            activity_kind=activity_kind,
            source=source,
            error_class=type(exc).__name__,
            error=str(exc),
        )
        return

    _maybe_prune_ops_history(db=resolved_db, retry_supabase=retry_supabase, log_event=log_event)


def _parse_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _is_activity_error(row: dict[str, Any]) -> bool:
    status_code = row.get("status_code")
    return bool(row.get("error_type")) or (isinstance(status_code, int) and status_code >= 400)


def _try_parse_remaining(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sanitize_raw_activity_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_kind": "raw_call",
        "timestamp": row.get("captured_at"),
        "source": row.get("source"),
        "endpoint": row.get("endpoint"),
        "sport": row.get("sport"),
        "cache_hit": bool(row.get("cache_hit")),
        "outbound_call_made": bool(row.get("outbound_call_made")),
        "status_code": row.get("status_code"),
        "duration_ms": row.get("duration_ms"),
        "api_requests_remaining": row.get("api_requests_remaining"),
        "credits_used_last": row.get("credits_used_last"),
        "error_type": row.get("error_type"),
        "error_message": row.get("error_message"),
    }


def _sanitize_scan_activity_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_kind": "scan_detail",
        "timestamp": row.get("captured_at"),
        "source": row.get("source"),
        "surface": row.get("surface"),
        "scan_scope": row.get("scan_scope"),
        "requested_sport": row.get("requested_sport"),
        "sport": row.get("sport"),
        "actor_label": row.get("actor_label"),
        "run_id": row.get("run_id"),
        "cache_hit": bool(row.get("cache_hit")),
        "outbound_call_made": bool(row.get("outbound_call_made")),
        "duration_ms": row.get("duration_ms"),
        "events_fetched": row.get("events_fetched"),
        "events_with_both_books": row.get("events_with_both_books"),
        "sides_count": row.get("sides_count"),
        "api_requests_remaining": row.get("api_requests_remaining"),
        "credits_used_last": row.get("credits_used_last"),
        "status_code": row.get("status_code"),
        "error_type": row.get("error_type"),
        "error_message": row.get("error_message"),
    }


def _build_recent_scan_sessions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    ordered_rows = sorted(rows, key=lambda row: _parse_timestamp(row.get("captured_at")) or 0)
    for row in ordered_rows:
        session_id = str(row.get("scan_session_id") or "").strip()
        if not session_id:
            continue

        current = grouped.get(session_id)
        if current is None:
            current = {
                "activity_kind": "scan_session",
                "scan_session_id": session_id,
                "timestamp": row.get("captured_at"),
                "source": row.get("source"),
                "surface": row.get("surface"),
                "scan_scope": row.get("scan_scope"),
                "requested_sport": row.get("requested_sport"),
                "actor_label": row.get("actor_label"),
                "run_id": row.get("run_id"),
                "detail_count": 0,
                "live_call_count": 0,
                "cache_hit_count": 0,
                "other_count": 0,
                "total_events_fetched": 0,
                "total_events_with_both_books": 0,
                "total_sides": 0,
                "min_api_requests_remaining": None,
                "error_count": 0,
                "has_errors": False,
                "details": [],
                "_latest_ts_epoch": _parse_timestamp(row.get("captured_at")) or 0,
                "_min_remaining_numeric": None,
            }
            grouped[session_id] = current

        current["timestamp"] = row.get("captured_at") or current.get("timestamp")
        current["_latest_ts_epoch"] = max(
            current.get("_latest_ts_epoch") or 0,
            _parse_timestamp(row.get("captured_at")) or 0,
        )
        current["detail_count"] += 1
        if row.get("cache_hit"):
            current["cache_hit_count"] += 1
        elif row.get("outbound_call_made"):
            current["live_call_count"] += 1
        else:
            current["other_count"] += 1

        current["total_events_fetched"] += int(row.get("events_fetched") or 0)
        current["total_events_with_both_books"] += int(row.get("events_with_both_books") or 0)
        current["total_sides"] += int(row.get("sides_count") or 0)

        remaining_numeric = _try_parse_remaining(row.get("api_requests_remaining"))
        if remaining_numeric is not None:
            current_min = current.get("_min_remaining_numeric")
            if current_min is None or remaining_numeric < current_min:
                current["_min_remaining_numeric"] = remaining_numeric
                current["min_api_requests_remaining"] = remaining_numeric
        elif current.get("min_api_requests_remaining") is None and row.get("api_requests_remaining") is not None:
            current["min_api_requests_remaining"] = row.get("api_requests_remaining")

        if _is_activity_error(row):
            current["error_count"] += 1
            current["has_errors"] = True

        current["details"].append(_sanitize_scan_activity_row(row))

    recent = sorted(grouped.values(), key=lambda row: row.get("_latest_ts_epoch") or 0, reverse=True)[
        :RECENT_SCAN_SESSION_LIMIT
    ]
    for row in recent:
        row.pop("_latest_ts_epoch", None)
        row.pop("_min_remaining_numeric", None)
    return recent


def _select_latest_job_run(
    *,
    db: Any,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    job_kind: str,
) -> dict[str, Any] | None:
    result = _run_query(
        lambda: (
            db.table(OPS_JOB_RUNS_TABLE)
            .select("*")
            .eq("job_kind", job_kind)
            .order("captured_at", desc=True)
            .limit(1)
            .execute()
        ),
        retry_supabase=retry_supabase,
    )
    rows = getattr(result, "data", None) or []
    if not rows:
        return None
    return rows[0]


def _select_recent_activity_rows(
    *,
    db: Any,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    activity_kind: str,
    limit: int,
) -> list[dict[str, Any]]:
    result = _run_query(
        lambda: (
            db.table(ODDS_API_ACTIVITY_EVENTS_TABLE)
            .select("*")
            .eq("activity_kind", activity_kind)
            .order("captured_at", desc=True)
            .limit(limit)
            .execute()
        ),
        retry_supabase=retry_supabase,
    )
    return list(getattr(result, "data", None) or [])


def _map_last_manual_scan(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at": row.get("captured_at"),
        "surface": row.get("surface"),
        "sport": row.get("requested_sport"),
        "events_fetched": row.get("events_fetched"),
        "events_with_both_books": row.get("events_with_both_books"),
        "total_sides": row.get("total_sides"),
        "api_requests_remaining": row.get("api_requests_remaining"),
    }


def _map_scan_run(row: dict[str, Any]) -> dict[str, Any]:
    mapped = {
        "run_id": row.get("run_id"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "duration_ms": row.get("duration_ms"),
        "total_sides": row.get("total_sides"),
        "alerts_scheduled": row.get("alerts_scheduled"),
        "captured_at": row.get("captured_at"),
    }
    if row.get("hard_errors") is not None:
        mapped["hard_errors"] = row.get("hard_errors")
    if row.get("error_count") is not None:
        mapped["error_count"] = row.get("error_count")
    if row.get("errors") is not None:
        mapped["errors"] = row.get("errors")
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else None
    if meta and "autolog_summary" in meta:
        mapped["autolog_summary"] = meta.get("autolog_summary")
    return mapped


def _map_last_auto_settle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": row.get("source"),
        "run_id": row.get("run_id"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "duration_ms": row.get("duration_ms"),
        "settled": row.get("settled"),
        "captured_at": row.get("captured_at"),
    }


def _map_last_auto_settle_summary(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return {
        "captured_at": row.get("captured_at"),
        "total_settled": row.get("settled"),
        "skipped_totals": row.get("skipped_totals"),
        "sports": meta.get("sports"),
    }


def _map_last_readiness_failure(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return {
        "captured_at": row.get("captured_at"),
        "checks": row.get("checks"),
        "db_error": meta.get("db_error"),
    }


def _load_durable_odds_api_activity(
    *,
    db: Any,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
) -> dict[str, Any]:
    raw_rows = _select_recent_activity_rows(
        db=db,
        retry_supabase=retry_supabase,
        activity_kind="raw_call",
        limit=RECENT_RAW_CALL_QUERY_LIMIT,
    )
    scan_rows = _select_recent_activity_rows(
        db=db,
        retry_supabase=retry_supabase,
        activity_kind="scan_detail",
        limit=RECENT_SCAN_DETAIL_QUERY_LIMIT,
    )

    cutoff_epoch = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
    last_hour_rows = [
        row for row in raw_rows if (_parse_timestamp(row.get("captured_at")) or 0) >= cutoff_epoch
    ]
    errors_last_hour = [row for row in last_hour_rows if _is_activity_error(row)]

    last_success_at = None
    last_error_at = None
    for row in raw_rows:
        is_error = _is_activity_error(row)
        if last_error_at is None and is_error:
            last_error_at = row.get("captured_at")
        if last_success_at is None and not is_error and bool(row.get("outbound_call_made")):
            last_success_at = row.get("captured_at")
        if last_success_at and last_error_at:
            break

    board_drop_rows = [
        row
        for row in raw_rows
        if str(row.get("source") or "").strip().lower() in BOARD_DROP_SOURCES
    ]
    board_drop_remaining_values = [
        _try_parse_remaining(row.get("api_requests_remaining"))
        for row in board_drop_rows
    ]
    board_drop_remaining_numeric = [value for value in board_drop_remaining_values if value is not None]
    board_drop_errors = sum(1 for row in board_drop_rows if _is_activity_error(row))
    board_drop_last_run_at = board_drop_rows[0].get("captured_at") if board_drop_rows else None

    return {
        "summary": {
            "calls_last_hour": len(last_hour_rows),
            "errors_last_hour": len(errors_last_hour),
            "last_success_at": last_success_at,
            "last_error_at": last_error_at,
        },
        "recent_scans": _build_recent_scan_sessions(scan_rows),
        "recent_calls": [_sanitize_raw_activity_row(row) for row in raw_rows[:RECENT_CALL_LIMIT]],
        "board_drop": {
            "last_run_at": board_drop_last_run_at,
            "calls_count": len(board_drop_rows),
            "min_api_requests_remaining": (
                min(board_drop_remaining_numeric) if board_drop_remaining_numeric else None
            ),
            "errors": board_drop_errors,
        },
    }


def load_ops_status_snapshot(
    *,
    db: Any | None,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    log_event: Callable[..., None] | None,
    fallback_ops_status: dict[str, Any] | None,
    fallback_odds_api_activity: dict[str, Any] | None,
) -> dict[str, Any]:
    ops = build_empty_ops_status()
    if isinstance(fallback_ops_status, dict):
        ops.update(copy.deepcopy(fallback_ops_status))

    if not isinstance(ops.get("odds_api_activity"), dict):
        ops["odds_api_activity"] = build_empty_odds_api_activity_snapshot()

    if isinstance(fallback_odds_api_activity, dict):
        ops["odds_api_activity"] = copy.deepcopy(fallback_odds_api_activity)

    resolved_db = _resolve_db(db)
    if resolved_db is None:
        return ops

    try:
        manual = _select_latest_job_run(db=resolved_db, retry_supabase=retry_supabase, job_kind="manual_scan")
        scheduler = _select_latest_job_run(
            db=resolved_db, retry_supabase=retry_supabase, job_kind="scheduled_scan"
        )
        ops_trigger = _select_latest_job_run(
            db=resolved_db, retry_supabase=retry_supabase, job_kind="ops_trigger_scan"
        )
        auto_settle = _select_latest_job_run(
            db=resolved_db, retry_supabase=retry_supabase, job_kind="auto_settle"
        )
        readiness = _select_latest_job_run(
            db=resolved_db, retry_supabase=retry_supabase, job_kind="readiness_failure"
        )
        activity = _load_durable_odds_api_activity(db=resolved_db, retry_supabase=retry_supabase)
    except Exception as exc:
        _log_warning(
            log_event,
            "ops_history.load_snapshot_failed",
            error_class=type(exc).__name__,
            error=str(exc),
        )
        return ops

    if manual:
        ops["last_manual_scan"] = _map_last_manual_scan(manual)
    if scheduler:
        ops["last_scheduler_scan"] = _map_scan_run(scheduler)
    if ops_trigger:
        ops["last_ops_trigger_scan"] = _map_scan_run(ops_trigger)
    if auto_settle:
        ops["last_auto_settle"] = _map_last_auto_settle(auto_settle)
        ops["last_auto_settle_summary"] = _map_last_auto_settle_summary(auto_settle)
    if readiness:
        ops["last_readiness_failure"] = _map_last_readiness_failure(readiness)

    if isinstance(activity, dict):
        ops["odds_api_activity"] = activity

    return ops
