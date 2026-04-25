"""Canonical ops status, readiness, and scheduler heartbeat runtime state."""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI

from database import get_db
from services.runtime_support import log_event, retry_supabase, utc_now_iso
from services.shared_state import is_redis_enabled

SCHEDULER_STALE_WINDOWS = {
    "jit_clv": timedelta(minutes=45),
    "auto_settler": timedelta(hours=30),
    "scheduled_scan": timedelta(hours=20),
}

_app: FastAPI | None = None


def configure_app(app: FastAPI) -> None:
    global _app
    _app = app


def get_app() -> FastAPI:
    if _app is None:
        raise RuntimeError("ops runtime app has not been configured")
    return _app


def get_ops_status() -> dict:
    try:
        state = getattr(get_app().state, "ops_status", {})
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def init_scheduler_heartbeats() -> None:
    app = get_app()
    app.state.scheduler_heartbeats = {
        job: {
            "last_started_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_run_id": None,
            "last_duration_ms": None,
            "last_error": None,
        }
        for job in SCHEDULER_STALE_WINDOWS.keys()
    }
    app.state.scheduler_started_at = utc_now_iso()


def record_scheduler_heartbeat(
    job_name: str,
    run_id: str,
    status: str,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    try:
        heartbeats = getattr(get_app().state, "scheduler_heartbeats", None)
    except Exception:
        return
    if not isinstance(heartbeats, dict) or job_name not in heartbeats:
        return

    job_state = heartbeats[job_name]
    job_state["last_run_id"] = run_id
    if status == "started":
        job_state["last_started_at"] = utc_now_iso()
    elif status == "success":
        job_state["last_success_at"] = utc_now_iso()
        job_state["last_duration_ms"] = duration_ms
        job_state["last_error"] = None
    elif status == "failure":
        job_state["last_failure_at"] = utc_now_iso()
        job_state["last_duration_ms"] = duration_ms
        job_state["last_error"] = error


def parse_utc_iso(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        normalized = timestamp.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1]
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        try:
            parsed = datetime.fromisoformat(f"{timestamp.strip()}+00:00")
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except Exception:
            return None


def check_scheduler_freshness(scheduler_expected: bool) -> tuple[bool, dict]:
    if not scheduler_expected:
        return True, {"enabled": False, "fresh": True, "jobs": {}}

    app_role = (os.getenv("APP_ROLE") or "").strip().lower()
    if app_role == "api":
        try:
            from services.ops_history import load_scheduler_job_snapshot

            snapshot = load_scheduler_job_snapshot(
                db=get_db(),
                retry_supabase=retry_supabase,
            )
            now = datetime.now(UTC)

            def _fresh_from(snapshot_key: str, stale_window: timedelta) -> tuple[bool, str | None, str]:
                entry = snapshot.get(snapshot_key) if isinstance(snapshot, dict) else None
                captured_at = parse_utc_iso(entry.get("captured_at") if isinstance(entry, dict) else None)
                if captured_at is None:
                    return False, None, "missing_snapshot"
                age_seconds = (now - captured_at).total_seconds()
                is_fresh = age_seconds <= stale_window.total_seconds()
                return is_fresh, (entry.get("captured_at") if isinstance(entry, dict) else None), (
                    "fresh_snapshot" if is_fresh else "stale_snapshot"
                )

            job_map = {
                "jit_clv": "jit_clv",
                "auto_settler": "auto_settle",
                "scheduled_scan": "scheduled_scan",
            }
            jobs: dict[str, dict] = {}
            all_fresh = True
            for job_name, stale_window in SCHEDULER_STALE_WINDOWS.items():
                snapshot_key = job_map.get(job_name, job_name)
                fresh, last_success_at, reason = _fresh_from(snapshot_key, stale_window)
                all_fresh = all_fresh and fresh
                jobs[job_name] = {
                    "fresh": fresh,
                    "freshness_reason": reason,
                    "last_success_at": last_success_at,
                    "last_failure_at": None,
                    "last_run_id": None,
                    "last_error": None,
                    "stale_after_seconds": int(stale_window.total_seconds()),
                    "age_seconds": None,
                }
            return all_fresh, {"enabled": True, "fresh": all_fresh, "jobs": jobs}
        except Exception:
            pass

    try:
        app = get_app()
        heartbeats = getattr(app.state, "scheduler_heartbeats", None)
        scheduler_started_at = parse_utc_iso(getattr(app.state, "scheduler_started_at", None))
    except Exception:
        heartbeats = None
        scheduler_started_at = None
    if not isinstance(heartbeats, dict):
        return False, {
            "enabled": True,
            "fresh": False,
            "reason": "scheduler heartbeats unavailable",
            "jobs": {},
        }

    now = datetime.now(UTC)
    all_fresh = True
    jobs: dict[str, dict] = {}
    for job_name, stale_window in SCHEDULER_STALE_WINDOWS.items():
        state = heartbeats.get(job_name) or {}
        last_success = parse_utc_iso(state.get("last_success_at"))
        freshness_reason = "fresh_success"

        if last_success is not None:
            age_seconds = (now - last_success).total_seconds()
            is_fresh = age_seconds <= stale_window.total_seconds()
            if not is_fresh:
                freshness_reason = "stale_success"
        else:
            age_seconds = None
            if scheduler_started_at is not None:
                startup_age = (now - scheduler_started_at).total_seconds()
                is_fresh = startup_age <= stale_window.total_seconds()
                freshness_reason = "waiting_first_run" if is_fresh else "stale_no_success"
            else:
                is_fresh = False
                freshness_reason = "unknown_start_time"

        all_fresh = all_fresh and is_fresh
        jobs[job_name] = {
            "fresh": is_fresh,
            "freshness_reason": freshness_reason,
            "last_success_at": state.get("last_success_at"),
            "last_failure_at": state.get("last_failure_at"),
            "last_run_id": state.get("last_run_id"),
            "last_error": state.get("last_error"),
            "stale_after_seconds": int(stale_window.total_seconds()),
            "age_seconds": round(age_seconds, 2) if age_seconds is not None else None,
        }

    return all_fresh, {"enabled": True, "fresh": all_fresh, "jobs": jobs}


def runtime_state() -> dict:
    from services.scheduler_runtime import scan_alert_mode

    environment = os.getenv("ENVIRONMENT", "production").lower()
    scheduler_expected = os.getenv("ENABLE_SCHEDULER") == "1" and os.getenv("TESTING") != "1"
    try:
        scheduler_running = bool(getattr(get_app().state, "scheduler", None))
    except Exception:
        scheduler_running = False
    heartbeat_enabled = os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1"

    discord_runtime: dict[str, Any] = {
        "heartbeat_enabled": heartbeat_enabled,
        "scan_alert_mode": scan_alert_mode(),
        "alert_delivery": {
            "message_type": "alert",
            "requested_message_type": "alert",
            "delivery_context": "scheduled_board_drop",
            "alert_route_guarded": False,
            "route_kind": "alert_unconfigured",
            "webhook_configured": False,
            "webhook_source": None,
            "role_configured": False,
            "role_source": None,
            "dedupe_ttl_seconds": None,
            "redis_enabled": is_redis_enabled(),
        },
        "test_delivery": {
            "message_type": "test",
            "requested_message_type": "test",
            "delivery_context": None,
            "alert_route_guarded": False,
            "route_kind": "test_unconfigured",
            "webhook_configured": False,
            "webhook_source": None,
            "role_configured": False,
            "role_source": None,
            "dedupe_ttl_seconds": None,
            "redis_enabled": is_redis_enabled(),
        },
        "last_schedule_stats": {},
    }

    try:
        from services.discord_alerts import describe_discord_delivery_target, get_last_schedule_stats

        discord_runtime["alert_delivery"] = describe_discord_delivery_target(
            "alert",
            delivery_context="scheduled_board_drop",
        )
        discord_runtime["test_delivery"] = describe_discord_delivery_target("test")
        discord_runtime["last_schedule_stats"] = get_last_schedule_stats()
    except Exception:
        pass

    return {
        "environment": environment,
        "scheduler_expected": scheduler_expected,
        "scheduler_running": scheduler_running,
        "redis_configured": is_redis_enabled(),
        "cron_token_configured": bool(os.getenv("CRON_TOKEN")),
        "odds_api_key_configured": bool(os.getenv("ODDS_API_KEY")),
        "supabase_url_configured": bool(os.getenv("SUPABASE_URL")),
        "supabase_service_role_configured": bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
        "discord": discord_runtime,
    }


def check_db_ready() -> tuple[bool, str | None]:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return False, "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY"

    timeout_raw = os.getenv("READINESS_DB_TIMEOUT_SECONDS", "2.5")
    try:
        timeout_seconds = max(0.25, float(timeout_raw))
    except ValueError:
        timeout_seconds = 2.5

    params = urllib.parse.urlencode({"select": "user_id", "limit": "1"})
    request = urllib.request.Request(
        f"{url}/rest/v1/settings?{params}",
        headers={
            "apikey": key,
            "authorization": f"Bearer {key}",
            "accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if 200 <= response.status < 300:
                response.read(256)
                return True, None
            return False, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTPError: {exc.code}"
    except TimeoutError:
        return False, f"TimeoutError: readiness DB probe exceeded {timeout_seconds:g}s"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def check_db_ready_via_client() -> tuple[bool, str | None]:
    """Legacy Supabase SDK probe kept for targeted tests/manual debugging."""
    try:
        db = get_db()
        db.table("settings").select("user_id").limit(1).execute()
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def init_ops_status() -> None:
    from services.ops_history import build_empty_ops_status

    get_app().state.ops_status = build_empty_ops_status()


def set_ops_status(key: str, value: dict) -> None:
    try:
        state = getattr(get_app().state, "ops_status", None)
        if not isinstance(state, dict):
            init_ops_status()
            state = get_app().state.ops_status
        state[key] = value
    except Exception as exc:
        log_event(
            "ops_status.set_failed",
            level="warning",
            key=key,
            error_class=type(exc).__name__,
            error=str(exc),
        )


def persist_ops_job_run(**kwargs: Any) -> None:
    from services.ops_history import persist_ops_job_run as persist_ops_job_run_service

    try:
        db = get_db()
    except Exception as exc:
        log_event(
            "ops_history.get_db_failed",
            level="warning",
            error_class=type(exc).__name__,
            error=str(exc),
        )
        db = None

    persist_ops_job_run_service(
        db=db,
        retry_supabase=retry_supabase,
        log_event=log_event,
        **kwargs,
    )
