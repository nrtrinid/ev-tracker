"""
EV Tracker API
FastAPI backend for sports betting EV tracking.
"""

import asyncio
import json
import logging
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, UTC, timedelta, timezone
from contextlib import asynccontextmanager
import os
import time
from uuid import uuid4
from dotenv import load_dotenv
import httpx
from zoneinfo import ZoneInfo

from models import (
    BetCreate, BetUpdate, BetResponse, BetResult, PromoType,
    SettingsUpdate, SettingsResponse, SummaryResponse,
    TransactionCreate, TransactionResponse, BalanceResponse,
    ScanResponse, FullScanResponse,
)
from calculations import (
    american_to_decimal, calculate_ev, calculate_real_profit, calculate_clv,
    compute_blend_weight,
)
from auth import get_current_user
from services.shared_state import allow_fixed_window_rate_limit, is_redis_enabled
from services.scanner_duplicate_detection import annotate_sides_with_duplicate_state
from services.scheduler_utils import (
    merge_scheduled_scan_times,
    scanned_at_from_oldest_fetch,
    scheduled_scan_rollup,
)
from services.scheduler_bootstrap import (
    build_auto_settle_trigger,
    register_scheduled_scan_jobs,
    mark_scheduler_started,
    shutdown_scheduler,
)
from services.scheduler_scan import (
    run_scheduled_scan_sports,
    persist_latest_scheduled_scan_payload,
    maybe_send_scheduled_scan_no_alert_heartbeat,
    run_scheduled_scan_autolog,
    finalize_scheduled_scan_run,
)
from services.scheduler_runner import run_scheduler_job
from services.scan_cache import (
    persist_latest_full_scan,
    load_and_enrich_latest_scan_payload,
    resolve_scan_latest_response,
    scan_cache_exception_to_http_exception,
)
from services.scan_markets import (
    run_single_sport_manual_scan,
    run_all_sports_manual_scan,
    apply_manual_scan_bundle,
    scan_exception_to_http_exception,
)
from services.balance_stats import compute_balances_by_sportsbook
from services.summary_stats import summarize_bets
from services.transaction_records import (
    build_transaction_insert_payload,
    transaction_row_to_response_payload,
    transaction_rows_to_response_payloads,
)
from services.settings_response import build_settings_response
from services.paper_autolog_runner import execute_longshot_autolog
from routes.ops_cron import (
    cron_run_scan_impl,
    cron_run_auto_settle_impl,
    ops_status_impl,
    cron_test_discord_impl,
)
from routes.scan_routes import scan_latest_impl, scan_impl, scan_markets_impl
from routes.transactions_routes import (
    create_transaction_impl,
    list_transactions_impl,
    delete_transaction_impl,
)
from routes.settings_routes import (
    build_settings_update_payload,
    get_settings_impl,
    update_settings_impl,
)
from routes.utility_routes import calculate_ev_preview_impl
from routes.admin_routes import backfill_ev_locks_impl

load_dotenv()

app: FastAPI

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(message)s")
logger = logging.getLogger("ev_tracker")

SCHEDULER_STALE_WINDOWS = {
    "clv_daily": timedelta(hours=30),
    "jit_clv": timedelta(minutes=45),
    "auto_settler": timedelta(hours=30),
    "scheduled_scan": timedelta(hours=20),
}

# ---- V1 paper autolog constants ----
LONGSHOT_AUTOLOG_SPORTS = {"basketball_nba", "basketball_ncaab"}
LOW_EDGE_COHORT = "low_edge_test"
HIGH_EDGE_COHORT = "high_edge_longshot_test"
LOW_EDGE_EV_MIN = 0.5
LOW_EDGE_EV_MAX = 1.5
LOW_EDGE_ODDS_MIN = -200
LOW_EDGE_ODDS_MAX = 300
HIGH_EDGE_EV_MIN = 10.0
# V1 decision: hard-code stricter floor to suppress noisy longshot volume.
HIGH_EDGE_ODDS_MIN = 700
AUTOLOG_MAX_TOTAL = 5
AUTOLOG_MAX_LOW = 2
AUTOLOG_MAX_HIGH = 3
AUTOLOG_PAPER_STAKE = 10.0

# Optional one-off scan schedule in Phoenix local time, format HH:MM (24h).
# Example: SCHEDULED_SCAN_TEMP_TIME_PHOENIX=14:45
SCHEDULED_SCAN_TEMP_TIME_ENV = "SCHEDULED_SCAN_TEMP_TIME_PHOENIX"


def _is_paper_experiment_autolog_enabled() -> bool:
    return (os.getenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG") or "0") == "1"


def _paper_experiment_account_user_id() -> str:
    return (os.getenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID") or "").strip()


def _parse_hhmm(value: str | None) -> tuple[int, int] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return (hour, minute)


def _new_run_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _log_event(event: str, level: str = "info", **fields):
    payload = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat() + "Z",
        **fields,
    }
    message = json.dumps(payload, default=str)
    getattr(logger, level.lower(), logger.info)(message)


async def _run_longshot_autolog_for_sides(db, *, run_id: str, sides: list[dict]) -> dict:
    """Autolog paper tickets from existing scan sides with deterministic caps and dedupe."""
    if not _is_paper_experiment_autolog_enabled():
        return {"enabled": False, "inserted_total": 0}

    user_id = _paper_experiment_account_user_id()
    if not user_id:
        return {"enabled": True, "configured": False, "inserted_total": 0, "reason": "missing_user_id"}

    summary = execute_longshot_autolog(
        db=db,
        run_id=run_id,
        user_id=user_id,
        sides=sides,
        supported_sports=LONGSHOT_AUTOLOG_SPORTS,
        low_edge_cohort=LOW_EDGE_COHORT,
        high_edge_cohort=HIGH_EDGE_COHORT,
        low_edge_ev_min=LOW_EDGE_EV_MIN,
        low_edge_ev_max=LOW_EDGE_EV_MAX,
        low_edge_odds_min=LOW_EDGE_ODDS_MIN,
        low_edge_odds_max=LOW_EDGE_ODDS_MAX,
        high_edge_ev_min=HIGH_EDGE_EV_MIN,
        high_edge_odds_min=HIGH_EDGE_ODDS_MIN,
        max_total=AUTOLOG_MAX_TOTAL,
        max_low=AUTOLOG_MAX_LOW,
        max_high=AUTOLOG_MAX_HIGH,
        paper_stake=AUTOLOG_PAPER_STAKE,
        pending_result_value=BetResult.PENDING.value,
        now_iso=datetime.now(UTC).isoformat(),
        today_iso=datetime.now(UTC).date().isoformat(),
    )

    return {
        "enabled": True,
        "configured": True,
        **summary,
    }


def _validate_environment() -> None:
    required = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    environment = os.getenv("ENVIRONMENT", "production").lower()
    if environment not in {"development", "production", "testing", "staging"}:
        _log_event(
            "startup.env_environment_unexpected",
            level="warning",
            environment=environment,
        )

    scheduler_enabled = os.getenv("ENABLE_SCHEDULER") == "1"
    odds_api_configured = bool(os.getenv("ODDS_API_KEY"))
    cron_token_configured = bool(os.getenv("CRON_TOKEN"))
    paper_autolog_enabled = _is_paper_experiment_autolog_enabled()
    paper_autolog_user_id = _paper_experiment_account_user_id()
    temp_scan_time_raw = os.getenv(SCHEDULED_SCAN_TEMP_TIME_ENV)

    if scheduler_enabled and not odds_api_configured:
        _log_event(
            "startup.env_scheduler_without_odds_key",
            level="warning",
            message="ENABLE_SCHEDULER=1 but ODDS_API_KEY is missing; scan jobs will fail.",
        )

    if not cron_token_configured:
        _log_event(
            "startup.env_cron_token_missing",
            level="warning",
            message="CRON_TOKEN is missing; cron endpoints will reject requests.",
        )

    if paper_autolog_enabled and not paper_autolog_user_id:
        _log_event(
            "startup.env_paper_autolog_without_user_id",
            level="warning",
            message="Paper autolog is enabled but no account user id is configured; autolog inserts will be skipped.",
        )

    if temp_scan_time_raw and _parse_hhmm(temp_scan_time_raw) is None:
        _log_event(
            "startup.env_temp_scan_time_invalid",
            level="warning",
            env_var=SCHEDULED_SCAN_TEMP_TIME_ENV,
            provided_value=temp_scan_time_raw,
            message="Invalid temp scan time format; expected HH:MM in 24h format.",
        )

    _log_event(
        "startup.env_validated",
        environment=environment,
        scheduler_enabled=scheduler_enabled,
        cron_token_configured=cron_token_configured,
        odds_api_key_configured=odds_api_configured,
        paper_autolog_enabled=paper_autolog_enabled,
        paper_autolog_user_id_configured=bool(paper_autolog_user_id),
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _init_scheduler_heartbeats() -> None:
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
    app.state.scheduler_started_at = _utc_now_iso()


def _record_scheduler_heartbeat(
    job_name: str,
    run_id: str,
    status: str,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    heartbeats = getattr(app.state, "scheduler_heartbeats", None)
    if not isinstance(heartbeats, dict):
        return
    if job_name not in heartbeats:
        return

    job_state = heartbeats[job_name]
    job_state["last_run_id"] = run_id
    if status == "started":
        job_state["last_started_at"] = _utc_now_iso()
    elif status == "success":
        job_state["last_success_at"] = _utc_now_iso()
        job_state["last_duration_ms"] = duration_ms
        job_state["last_error"] = None
    elif status == "failure":
        job_state["last_failure_at"] = _utc_now_iso()
        job_state["last_duration_ms"] = duration_ms
        job_state["last_error"] = error


def _parse_utc_iso(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        normalized = timestamp.strip()

        # Accept both normalized UTC timestamps (e.g. 2026-...Z)
        # and legacy values that may look like 2026-...+00:00Z.
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


def _check_scheduler_freshness(scheduler_expected: bool) -> tuple[bool, dict]:
    if not scheduler_expected:
        return True, {"enabled": False, "fresh": True, "jobs": {}}

    heartbeats = getattr(app.state, "scheduler_heartbeats", None)
    if not isinstance(heartbeats, dict):
        return False, {
            "enabled": True,
            "fresh": False,
            "reason": "scheduler heartbeats unavailable",
            "jobs": {},
        }

    now = datetime.now(UTC)
    scheduler_started_at = _parse_utc_iso(getattr(app.state, "scheduler_started_at", None))
    all_fresh = True
    jobs: dict[str, dict] = {}
    for job_name, stale_window in SCHEDULER_STALE_WINDOWS.items():
        state = heartbeats.get(job_name) or {}
        last_success = _parse_utc_iso(state.get("last_success_at"))
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

        if not is_fresh:
            all_fresh = False
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


def _runtime_state() -> dict:
    environment = os.getenv("ENVIRONMENT", "production").lower()
    scheduler_expected = os.getenv("ENABLE_SCHEDULER") == "1" and os.getenv("TESTING") != "1"
    scheduler_running = bool(getattr(app.state, "scheduler", None))
    return {
        "environment": environment,
        "scheduler_expected": scheduler_expected,
        "scheduler_running": scheduler_running,
        "redis_configured": is_redis_enabled(),
        "cron_token_configured": bool(os.getenv("CRON_TOKEN")),
        "odds_api_key_configured": bool(os.getenv("ODDS_API_KEY")),
        "supabase_url_configured": bool(os.getenv("SUPABASE_URL")),
        "supabase_service_role_configured": bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
    }


def _check_db_ready() -> tuple[bool, str | None]:
    try:
        db = get_db()
        # Cheap DB probe through PostgREST with minimal payload.
        db.table("settings").select("user_id").limit(1).execute()
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _init_ops_status() -> None:
    app.state.ops_status = {
        "last_scheduler_scan": None,
        "last_cron_scan": None,
        "last_manual_scan": None,
        "last_auto_settle": None,
        "last_auto_settle_summary": None,
        "last_readiness_failure": None,
        "odds_api_activity": {
            "summary": {
                "calls_last_hour": 0,
                "errors_last_hour": 0,
                "last_success_at": None,
                "last_error_at": None,
            },
            "recent_calls": [],
        },
    }


def _set_ops_status(key: str, value: dict) -> None:
    state = getattr(app.state, "ops_status", None)
    if not isinstance(state, dict):
        _init_ops_status()
        state = app.state.ops_status
    state[key] = value


def _require_valid_cron_token(x_cron_token: str | None) -> None:
    expected = os.getenv("CRON_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_TOKEN not configured on server")
    if not x_cron_token or x_cron_token != expected:
        raise HTTPException(status_code=401, detail="Invalid cron token")

PHOENIX_TZ = None
try:
    PHOENIX_TZ = ZoneInfo("America/Phoenix")
except Exception as e:
    # If the runtime lacks IANA tzdata, scheduled scans should not run at wrong times.
    # Install the `tzdata` package if this occurs in production.
    print(f"[Scheduler] Failed to load America/Phoenix timezone: {e}")


# ---------- CLV daily safety-net scheduler ----------
# Fires once per day at 23:30 UTC (6:30 PM ET). Makes one fetch_odds call per
# active sport and updates pinnacle_odds_at_close for all pending tracked bets.
# This is a backstop — the piggyback in scan_markets does most of the work for free.

async def _run_clv_daily_job():
    """Safety-net: fetch closing Pinnacle lines for all pending CLV-tracked bets."""
    from services.odds_api import fetch_clv_for_pending_bets

    async def _run(_run_id: str):
        updated = await fetch_clv_for_pending_bets(get_db())
        return {"updated": updated}

    await run_scheduler_job(
        job_name="clv_daily",
        runner=_run,
        new_run_id=_new_run_id,
        record_scheduler_heartbeat=_record_scheduler_heartbeat,
        log_event=_log_event,
    )


async def _run_jit_clv_snatcher_job():
    """JIT CLV Snatcher: capture closing Pinnacle lines for games starting in the next 20 min."""
    from services.odds_api import run_jit_clv_snatcher

    async def _run(_run_id: str):
        updated = await run_jit_clv_snatcher(get_db())
        return {"updated": updated}

    async def _on_success(_run_id: str, details: dict, _duration_ms: float):
        updated = int(details.get("updated") or 0)
        if updated:
            print(f"[JIT CLV] Captured closing lines for {updated} bet(s).")
            if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1":
                from services.discord_alerts import send_discord_webhook

                payload = {
                    "embeds": [
                        {
                            "title": "JIT CLV update",
                            "description": f"Captured closing lines for **{updated}** bet(s).",
                            "fields": [
                                {"name": "Time (UTC)", "value": datetime.now(UTC).isoformat() + "Z", "inline": True},
                            ],
                        }
                    ]
                }
                asyncio.create_task(send_discord_webhook(payload))

    await run_scheduler_job(
        job_name="jit_clv",
        runner=_run,
        new_run_id=_new_run_id,
        record_scheduler_heartbeat=_record_scheduler_heartbeat,
        log_event=_log_event,
        on_success=_on_success,
    )


async def _run_auto_settler_job():
    """Auto-Settler: grade completed ML bets using The Odds API /scores endpoint."""
    from services.odds_api import run_auto_settler, get_last_auto_settler_summary

    async def _run(_run_id: str):
        settled = await run_auto_settler(get_db(), source="auto_settle_scheduler")
        return {"settled": settled}

    async def _on_success(run_id: str, details: dict, duration_ms: float):
        settled = details.get("settled")
        _set_ops_status(
            "last_auto_settle",
            {
                "source": "scheduler",
                "run_id": run_id,
                "settled": settled,
                "duration_ms": duration_ms,
                "captured_at": _utc_now_iso(),
            },
        )
        summary = get_last_auto_settler_summary()
        if summary:
            _set_ops_status("last_auto_settle_summary", summary)

    await run_scheduler_job(
        job_name="auto_settler",
        runner=_run,
        new_run_id=_new_run_id,
        record_scheduler_heartbeat=_record_scheduler_heartbeat,
        log_event=_log_event,
        on_success=_on_success,
    )


async def _run_scheduled_scan_job():
    """
    Scheduled scan job: warms the same cache used by GET /api/scan-markets by
    calling services.odds_api.get_cached_or_scan across SUPPORTED_SPORTS.
    """
    from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS

    run_id = _new_run_id("scheduled_scan")
    started = datetime.now(UTC).isoformat()
    started_at = time.monotonic()
    _record_scheduler_heartbeat("scheduled_scan", run_id, "started")
    _log_event("scheduler.scan.started", run_id=run_id, started_at=started + "Z")

    from services.discord_alerts import schedule_alerts
    scan_summary = await run_scheduled_scan_sports(
        run_id=run_id,
        supported_sports=SUPPORTED_SPORTS,
        get_cached_or_scan=lambda sport_key: get_cached_or_scan(sport_key, source="scheduled_scan"),
        schedule_alerts=schedule_alerts,
        log_event=_log_event,
    )
    (
        total_sides,
        alerts_scheduled,
        hard_errors,
        all_sides,
        total_events,
        total_with_both,
        min_remaining,
        oldest_fetched,
    ) = scheduled_scan_rollup(scan_summary)

    scanned_at = scanned_at_from_oldest_fetch(
        oldest_fetched,
        _utc_now_iso(),
    )

    # Keep Scanner's "latest scan" payload in sync for scheduled runs, not only manual scans.
    try:
        persist_latest_scheduled_scan_payload(
            all_sides=all_sides,
            total_events=total_events,
            total_with_both=total_with_both,
            min_remaining=min_remaining,
            scanned_at=scanned_at,
            persist_latest_payload=lambda payload: _retry_supabase(lambda: (
                get_db().table("global_scan_cache").upsert(
                    {"key": "latest", "payload": payload},
                    on_conflict="key",
                ).execute()
            )),
        )
    except Exception as e:
        _log_event(
            "scheduler.scan.latest_cache_persist_failed",
            level="warning",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
        )

    finished = datetime.now(UTC).isoformat()
    autolog_summary = await run_scheduled_scan_autolog(
        run_id=run_id,
        all_sides=all_sides,
        run_autolog=lambda *, run_id, sides: _run_longshot_autolog_for_sides(db=get_db(), run_id=run_id, sides=sides),
        is_autolog_enabled=_is_paper_experiment_autolog_enabled,
        log_event=_log_event,
    )
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    finalize_scheduled_scan_run(
        run_id=run_id,
        started=started,
        finished=finished,
        duration_ms=duration_ms,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        hard_errors=hard_errors,
        autolog_summary=autolog_summary,
        log_event=_log_event,
        record_scheduler_heartbeat=_record_scheduler_heartbeat,
        set_ops_status=_set_ops_status,
    )

    # Optional heartbeat so we can confirm the scheduled scan ran even when it finds no lines.
    from services.discord_alerts import send_discord_webhook

    maybe_send_scheduled_scan_no_alert_heartbeat(
        heartbeat_enabled=os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1",
        started=started,
        finished=finished,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        send_discord_webhook=send_discord_webhook,
        create_task=lambda coro: asyncio.create_task(coro),
    )


async def _piggyback_clv(sides: list[dict]):
    """
    Fire-and-forget task: update CLV snapshots for all pending tracked bets
    from the just-completed scan. Errors are swallowed so they never affect
    the scan response the user sees.
    """
    from services.odds_api import update_clv_snapshots
    try:
        db = get_db()
        update_clv_snapshots(sides, db)
    except Exception as e:
        print(f"[CLV piggyback] Error: {e}")


async def start_scheduler():
    if os.getenv("TESTING") == "1":
        return  # Skip scheduler in integration tests so we don't hit Odds API or cron
    if os.getenv("ENABLE_SCHEDULER") != "1":
        return  # Only one instance should run background jobs (Render scaling/workers)
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    _init_scheduler_heartbeats()
    scheduler = AsyncIOScheduler()
    # 23:30 UTC = 6:30 PM ET (accounts for EST; shift to 22:30 during EDT if needed)
    scheduler.add_job(_run_clv_daily_job, CronTrigger(hour=23, minute=30))
    # Every 15 min: capture closing Pinnacle lines for games starting within 20 min
    scheduler.add_job(_run_jit_clv_snatcher_job, IntervalTrigger(minutes=15))
    # 4:00 AM Phoenix daily: auto-grade completed ML bets via /scores.
    auto_settle_trigger = build_auto_settle_trigger(cron_trigger_cls=CronTrigger, phoenix_tz=PHOENIX_TZ)
    scheduler.add_job(
        _run_auto_settler_job,
        auto_settle_trigger,
        misfire_grace_time=60 * 60,
        coalesce=True,
    )
    register_scheduled_scan_jobs(
        scheduler=scheduler,
        cron_trigger_cls=CronTrigger,
        phoenix_tz=PHOENIX_TZ,
        temp_scan_time_raw=os.getenv(SCHEDULED_SCAN_TEMP_TIME_ENV),
        parse_hhmm=_parse_hhmm,
        merge_scan_times=merge_scheduled_scan_times,
        run_scheduled_scan_job=_run_scheduled_scan_job,
    )
    scheduler.start()
    mark_scheduler_started(
        scheduler=scheduler,
        app_state=app.state,
        utc_now_iso=_utc_now_iso,
        log_event=_log_event,
    )


async def stop_scheduler():
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        try:
            shutdown_scheduler(scheduler=scheduler, log_event=_log_event)
        except Exception as e:
            _log_event(
                "scheduler.stop_failed",
                level="error",
                error_class=type(e).__name__,
                error=str(e),
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_environment()
    _init_ops_status()
    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


app = FastAPI(
    title="EV Tracker API",
    description="Track sports betting Expected Value",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import database after app setup to avoid circular imports
from database import get_db

# ---------- Scan rate limit ----------
# 12 full scans per 15 minutes per user; uses shared state when REDIS_URL is configured.
_scan_rate_window_sec = 15 * 60
_scan_rate_max = 12


async def require_scan_rate_limit(user: dict = Depends(get_current_user)) -> dict:
    """Allow at most _scan_rate_max scan requests per user per _scan_rate_window_sec."""
    uid = user["id"]
    allowed = allow_fixed_window_rate_limit(
        bucket_key=f"scan:{uid}",
        max_requests=_scan_rate_max,
        window_seconds=_scan_rate_window_sec,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many scan requests. Please try again in a few minutes.",
        )
    return user


def _retry_supabase(f, retries=2):
    """Retry a Supabase/PostgREST request on transient 'Server disconnected' errors."""
    last_err = None
    for attempt in range(retries):
        try:
            return f()
        except httpx.RemoteProtocolError as e:
            last_err = e
            if attempt == retries - 1:
                raise
            time.sleep(0.4)
    if last_err:
        raise last_err


DEFAULT_SPORTSBOOKS = [
    "DraftKings", "FanDuel", "BetMGM", "Caesars",
    "ESPN Bet", "Fanatics", "Hard Rock", "bet365"
]


def get_user_settings(db, user_id: str) -> dict:
    """Get settings from DB, creating defaults for new users."""
    result = _retry_supabase(lambda: db.table("settings").select("*").eq("user_id", user_id).execute())
    if result.data:
        return result.data[0]

    defaults = {
        "user_id": user_id,
        "k_factor": 0.78,
        "default_stake": None,
        "preferred_sportsbooks": DEFAULT_SPORTSBOOKS,
        "k_factor_mode": "baseline",
        "k_factor_min_stake": 300.0,
        "k_factor_smoothing": 700.0,
        "k_factor_clamp_min": 0.50,
        "k_factor_clamp_max": 0.95,
    }
    _retry_supabase(lambda: db.table("settings").upsert(defaults).execute())
    result = _retry_supabase(lambda: db.table("settings").select("*").eq("user_id", user_id).execute())
    return result.data[0]


def compute_k_user(db, user_id: str) -> dict:
    """
    Compute observed bonus retention from settled bonus bets.
    Returns k_obs (None if no data), bonus_stake_settled.
    """
    try:
        res = _retry_supabase(lambda: (
            db.table("bets")
            .select("stake, result, win_payout, payout_override, promo_type")
            .eq("user_id", user_id)
            .eq("promo_type", "bonus_bet")
            .in_("result", ["win", "loss", "push", "void"])
            .execute()
        ))
        rows = res.data or []
    except Exception:
        return {"k_obs": None, "bonus_stake_settled": 0.0}

    total_stake = 0.0
    total_profit = 0.0
    for row in rows:
        stake = float(row.get("stake") or 0)
        result = row.get("result")
        win_payout = float(row.get("payout_override") or row.get("win_payout") or 0)
        total_stake += stake
        if result == "win":
            # bonus_bet profit = win_payout (stake not returned)
            total_profit += win_payout
        # loss / push / void → 0 profit

    k_obs = (total_profit / total_stake) if total_stake > 0 else None
    return {"k_obs": k_obs, "bonus_stake_settled": total_stake}


def build_effective_k(settings: dict, k_obs: float | None, bonus_stake_settled: float) -> dict:
    """
    Compute all derived k fields returned to the frontend.
    Returns a dict with k_factor_observed, k_factor_weight, k_factor_effective.
    """
    k0 = float(settings.get("k_factor") or 0.78)
    mode = settings.get("k_factor_mode") or "baseline"
    min_stake = float(settings.get("k_factor_min_stake") or 300.0)
    smoothing = float(settings.get("k_factor_smoothing") or 700.0)
    clamp_min = float(settings.get("k_factor_clamp_min") or 0.50)
    clamp_max = float(settings.get("k_factor_clamp_max") or 0.95)

    w = 0.0
    k_effective = k0

    if mode == "auto" and k_obs is not None:
        k_clamped = max(clamp_min, min(clamp_max, k_obs))
        w = compute_blend_weight(bonus_stake_settled, min_stake, smoothing)
        k_effective = (1.0 - w) * k0 + w * k_clamped

    return {
        "k_factor_observed": k_obs,
        "k_factor_weight": round(w, 4),
        "k_factor_effective": round(k_effective, 4),
        "k_factor_bonus_stake_settled": round(bonus_stake_settled, 2),
    }


def build_bet_response(row: dict, k_factor: float) -> BetResponse:
    """Convert database row to BetResponse with calculated fields."""
    from calculations import calculate_hold_from_odds

    decimal_odds = american_to_decimal(row["odds_american"])
    decimal_odds_for_ev = decimal_odds

    # If payout_override is provided, keep EV math consistent with the displayed payout.
    # This is only unambiguous for markets where win_payout is stake * decimal_odds
    # (standard/no_sweat/promo_qualifier). For bonus bets and profit boosts, payout
    # semantics differ, so we do not try to back-solve odds automatically.
    payout_override = row.get("payout_override")
    promo_type = row.get("promo_type")
    stake = row.get("stake") or 0
    if (
        payout_override is not None
        and stake
        and promo_type in ("standard", "no_sweat", "promo_qualifier")
    ):
        try:
            implied_decimal = float(payout_override) / float(stake)
            if implied_decimal > 1:
                decimal_odds_for_ev = implied_decimal
        except Exception:
            pass

    vig = None
    if row.get("opposing_odds"):
        vig = calculate_hold_from_odds(row["odds_american"], row["opposing_odds"])

    ev_result = calculate_ev(
        stake=row["stake"],
        decimal_odds=decimal_odds_for_ev,
        promo_type=row["promo_type"],
        k_factor=k_factor,
        boost_percent=row.get("boost_percent"),
        winnings_cap=row.get("winnings_cap"),
        vig=vig,
        true_prob=row.get("true_prob_at_entry"),
    )

    # Use payout override if present
    win_payout = payout_override or ev_result["win_payout"]

    real_profit = calculate_real_profit(
        stake=row["stake"],
        win_payout=win_payout,
        result=row["result"],
        promo_type=row["promo_type"],
    )

    # CLV — compute only when we have both entry and close Pinnacle lines
    clv_ev_percent = None
    beat_close = None
    if row.get("pinnacle_odds_at_entry") and row.get("pinnacle_odds_at_close"):
        clv_result = calculate_clv(row["odds_american"], row["pinnacle_odds_at_close"])
        clv_ev_percent = clv_result["clv_ev_percent"]
        beat_close = clv_result["beat_close"]

    # Use locked EV when present (frozen at bet-creation time)
    ev_per_dollar_out = row.get("ev_per_dollar_locked") if row.get("ev_per_dollar_locked") is not None else ev_result["ev_per_dollar"]
    ev_total_out = row.get("ev_total_locked") if row.get("ev_total_locked") is not None else ev_result["ev_total"]
    win_payout_out = row.get("win_payout_locked") if row.get("win_payout_locked") is not None else win_payout

    return BetResponse(
        id=row["id"],
        created_at=row["created_at"],
        event_date=row["event_date"],
        settled_at=row.get("settled_at"),
        sport=row["sport"],
        event=row["event"],
        market=row["market"],
        sportsbook=row["sportsbook"],
        promo_type=row["promo_type"],
        odds_american=row["odds_american"],
        odds_decimal=decimal_odds,
        stake=row["stake"],
        boost_percent=row.get("boost_percent"),
        winnings_cap=row.get("winnings_cap"),
        notes=row.get("notes"),
        opposing_odds=row.get("opposing_odds"),
        result=row["result"],
        win_payout=win_payout_out,
        ev_per_dollar=ev_per_dollar_out,
        ev_total=ev_total_out,
        real_profit=real_profit,
        pinnacle_odds_at_entry=row.get("pinnacle_odds_at_entry"),
        pinnacle_odds_at_close=row.get("pinnacle_odds_at_close"),
        clv_updated_at=row.get("clv_updated_at"),
        commence_time=row.get("commence_time"),
        clv_team=row.get("clv_team"),
        clv_sport_key=row.get("clv_sport_key"),
        true_prob_at_entry=row.get("true_prob_at_entry"),
        clv_ev_percent=clv_ev_percent,
        beat_close=beat_close,
        ev_per_dollar_locked=row.get("ev_per_dollar_locked"),
        ev_total_locked=row.get("ev_total_locked"),
        win_payout_locked=row.get("win_payout_locked"),
        ev_lock_version=row.get("ev_lock_version") or 1,
        is_paper=bool(row.get("is_paper") or False),
        strategy_cohort=row.get("strategy_cohort"),
        auto_logged=bool(row.get("auto_logged") or False),
        auto_log_run_at=row.get("auto_log_run_at"),
        auto_log_run_key=row.get("auto_log_run_key"),
        scan_ev_percent_at_log=row.get("scan_ev_percent_at_log"),
        book_odds_at_log=row.get("book_odds_at_log"),
        reference_odds_at_log=row.get("reference_odds_at_log"),
    )


# ============ Health Check ============

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/ready")
def readiness_check():
    """
    Readiness endpoint.

    - liveness (`/health`) only checks that the process is up
    - readiness (`/ready`) checks core runtime dependencies
    """
    runtime = _runtime_state()
    db_ok, db_error = _check_db_ready()
    scheduler_fresh_ok, scheduler_freshness = _check_scheduler_freshness(runtime["scheduler_expected"])

    checks = {
        "supabase_env": runtime["supabase_url_configured"] and runtime["supabase_service_role_configured"],
        "db_connectivity": db_ok,
        "scheduler_state": (not runtime["scheduler_expected"]) or runtime["scheduler_running"],
        "scheduler_freshness": scheduler_fresh_ok,
    }
    ready = all(checks.values())

    if not ready:
        _log_event(
            "readiness.failed",
            level="warning",
            checks=checks,
            db_error=db_error,
            runtime=runtime,
        )
        _set_ops_status(
            "last_readiness_failure",
            {
                "captured_at": _utc_now_iso(),
                "checks": checks,
                "db_error": db_error,
            },
        )

    response = {
        "status": "ready" if ready else "not_ready",
        "timestamp": datetime.now(UTC).isoformat() + "Z",
        "checks": checks,
        "runtime": runtime,
        "scheduler_freshness": scheduler_freshness,
    }
    if db_error:
        response["db_error"] = db_error

    if ready:
        return response

    raise HTTPException(status_code=503, detail=response)


# ── EV freeze helper ─────────────────────────────────────────────────────────

EV_LOCK_PROMO_TYPES = {"bonus_bet", "no_sweat", "promo_qualifier",
                       "boost_30", "boost_50", "boost_100", "boost_custom"}


def _lock_ev_for_row(db, bet_id: str, user_id: str, row: dict, settings: dict) -> None:
    """
    Compute EV once using the current effective k and write locked fields to DB.
    Only runs for promo types where k has a meaningful effect.
    Does NOT update bets that already have a valid lock (ev_locked_at is set).
    """
    if row.get("ev_locked_at") is not None:
        return
    if row.get("promo_type") not in EV_LOCK_PROMO_TYPES:
        return

    k_data = compute_k_user(db, user_id)
    k_derived = build_effective_k(settings, k_data["k_obs"], k_data["bonus_stake_settled"])
    k_eff = k_derived["k_factor_effective"]

    from calculations import calculate_hold_from_odds
    decimal_odds = american_to_decimal(row["odds_american"])
    payout_override = row.get("payout_override")
    stake = float(row.get("stake") or 0)
    promo_type = row.get("promo_type")

    decimal_odds_for_ev = decimal_odds
    if (payout_override is not None and stake
            and promo_type in ("standard", "no_sweat", "promo_qualifier")):
        try:
            implied = float(payout_override) / float(stake)
            if implied > 1:
                decimal_odds_for_ev = implied
        except Exception:
            pass

    vig = None
    if row.get("opposing_odds"):
        vig = calculate_hold_from_odds(row["odds_american"], row["opposing_odds"])

    ev_result = calculate_ev(
        stake=stake,
        decimal_odds=decimal_odds_for_ev,
        promo_type=promo_type,
        k_factor=k_eff,
        boost_percent=row.get("boost_percent"),
        winnings_cap=row.get("winnings_cap"),
        vig=vig,
        true_prob=row.get("true_prob_at_entry"),
    )
    win_payout = payout_override or ev_result["win_payout"]

    try:
        db.table("bets").update({
            "ev_per_dollar_locked": ev_result["ev_per_dollar"],
            "ev_total_locked": ev_result["ev_total"],
            "win_payout_locked": win_payout,
            "ev_locked_at": datetime.now(UTC).isoformat(),
        }).eq("id", bet_id).eq("user_id", user_id).execute()
    except Exception as e:
        logger.warning("ev_lock.write_failed bet_id=%s err=%s", bet_id, e)


# ============ Bets CRUD ============

@app.post("/bets", response_model=BetResponse, status_code=201)
def create_bet(bet: BetCreate, user: dict = Depends(get_current_user)):
    """Create a new bet."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    data = {
        "user_id": user["id"],
        "sport": bet.sport,
        "event": bet.event,
        "market": bet.market,
        "sportsbook": bet.sportsbook,
        "promo_type": bet.promo_type.value,
        "odds_american": bet.odds_american,
        "stake": bet.stake,
        "boost_percent": bet.boost_percent,
        "winnings_cap": bet.winnings_cap,
        "notes": bet.notes,
        "payout_override": bet.payout_override,
        "opposing_odds": bet.opposing_odds,
        "result": BetResult.PENDING.value,
        # CLV tracking fields (None when betting manually, set when logging from scanner)
        "pinnacle_odds_at_entry": bet.pinnacle_odds_at_entry,
        "commence_time": bet.commence_time,
        "clv_team": bet.clv_team,
        "clv_sport_key": bet.clv_sport_key,
        "true_prob_at_entry": bet.true_prob_at_entry,
    }

    # Only include event_date if provided, otherwise let DB default to today
    if bet.event_date:
        data["event_date"] = bet.event_date.isoformat()

    result = db.table("bets").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create bet")

    row = result.data[0]
    _lock_ev_for_row(db, row["id"], user["id"], row, settings)
    # Re-fetch so locked fields are included in the response
    fresh = db.table("bets").select("*").eq("id", row["id"]).execute()
    return build_bet_response(fresh.data[0] if fresh.data else row, settings["k_factor"])


@app.get("/bets", response_model=list[BetResponse])
def get_bets(
    sport: str | None = None,
    sportsbook: str | None = None,
    result: BetResult | None = None,
    limit: int = 1000,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Get all bets with optional filters."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    query = (
        db.table("bets")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
    )

    if sport:
        query = query.eq("sport", sport)
    if sportsbook:
        query = query.eq("sportsbook", sportsbook)
    if result:
        query = query.eq("result", result.value)

    query = query.range(offset, offset + limit - 1)

    response = _retry_supabase(lambda: query.execute())

    return [build_bet_response(row, settings["k_factor"]) for row in response.data]


@app.get("/bets/{bet_id}", response_model=BetResponse)
def get_bet(bet_id: str, user: dict = Depends(get_current_user)):
    """Get a single bet by ID."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    result = (
        db.table("bets")
        .select("*")
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return build_bet_response(result.data[0], settings["k_factor"])


@app.patch("/bets/{bet_id}", response_model=BetResponse)
def update_bet(bet_id: str, bet: BetUpdate, user: dict = Depends(get_current_user)):
    """Update an existing bet."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    # Build update data, excluding None values
    data = {}
    if bet.sport is not None:
        data["sport"] = bet.sport
    if bet.event is not None:
        data["event"] = bet.event
    if bet.market is not None:
        data["market"] = bet.market
    if bet.sportsbook is not None:
        data["sportsbook"] = bet.sportsbook
    if bet.promo_type is not None:
        data["promo_type"] = bet.promo_type.value
    if bet.odds_american is not None:
        data["odds_american"] = bet.odds_american
    if bet.stake is not None:
        data["stake"] = bet.stake
    if bet.boost_percent is not None:
        data["boost_percent"] = bet.boost_percent
    if bet.winnings_cap is not None:
        data["winnings_cap"] = bet.winnings_cap
    if bet.notes is not None:
        data["notes"] = bet.notes
    if bet.result is not None:
        data["result"] = bet.result.value
        # Auto-set settled_at when result changes from pending
        current = (
            db.table("bets")
            .select("result")
            .eq("id", bet_id)
            .eq("user_id", user["id"])
            .execute()
        )
        if current.data and current.data[0]["result"] == "pending" and bet.result.value != "pending":
            data["settled_at"] = datetime.now(UTC).isoformat()
    if bet.payout_override is not None:
        data["payout_override"] = bet.payout_override
    if bet.opposing_odds is not None:
        data["opposing_odds"] = bet.opposing_odds
    if bet.event_date is not None:
        data["event_date"] = bet.event_date.isoformat()

    # If any EV-relevant field changed, clear the lock so it gets recomputed
    EV_RELEVANT = {"odds_american", "stake", "promo_type", "boost_percent",
                   "winnings_cap", "payout_override", "opposing_odds"}
    if data.keys() & EV_RELEVANT:
        data["ev_per_dollar_locked"] = None
        data["ev_total_locked"] = None
        data["win_payout_locked"] = None
        data["ev_locked_at"] = None

    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        db.table("bets")
        .update(data)
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    row = result.data[0]
    _lock_ev_for_row(db, bet_id, user["id"], row, settings)
    fresh = db.table("bets").select("*").eq("id", bet_id).execute()
    return build_bet_response(fresh.data[0] if fresh.data else row, settings["k_factor"])


@app.patch("/bets/{bet_id}/result")
def update_bet_result(
    bet_id: str,
    result: BetResult,
    user: dict = Depends(get_current_user),
):
    """Quick endpoint to just update bet result (win/loss)."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    # Build update data
    update_data = {"result": result.value}

    # Auto-set settled_at when changing from pending to settled
    current = (
        db.table("bets")
        .select("result")
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if not current.data:
        raise HTTPException(status_code=404, detail="Bet not found")
    if current.data[0]["result"] == "pending" and result.value != "pending":
        update_data["settled_at"] = datetime.now(UTC).isoformat()

    response = (
        db.table("bets")
        .update(update_data)
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return build_bet_response(response.data[0], settings["k_factor"])


@app.delete("/bets/{bet_id}")
def delete_bet(bet_id: str, user: dict = Depends(get_current_user)):
    """Delete a bet."""
    db = get_db()

    result = (
        db.table("bets")
        .delete()
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return {"deleted": True, "id": bet_id}


@app.post("/admin/backfill-ev-locks")
def backfill_ev_locks(user: dict = Depends(get_current_user)):
    """
    One-off endpoint: freeze EV on all existing promo bets that don't yet have
    locked EV fields. Safe to call multiple times (idempotent: skips rows that
    already have ev_locked_at set).
    """
    return backfill_ev_locks_impl(
        user=user,
        get_db=get_db,
        get_user_settings=get_user_settings,
        retry_supabase=_retry_supabase,
        ev_lock_promo_types=EV_LOCK_PROMO_TYPES,
        lock_ev_for_row=_lock_ev_for_row,
        log_warning=logger.warning,
    )


# ============ Summary / Dashboard ============

@app.get("/summary", response_model=SummaryResponse)
def get_summary(user: dict = Depends(get_current_user)):
    """Get dashboard summary statistics."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    result = _retry_supabase(lambda: db.table("bets").select("*").eq("user_id", user["id"]).execute())
    payload = summarize_bets(
        bets=result.data,
        k_factor=settings["k_factor"],
        build_bet_response=build_bet_response,
    )
    return SummaryResponse(**payload)


# ============ Transactions ============

@app.post("/transactions", response_model=TransactionResponse, status_code=201)
def create_transaction(
    transaction: TransactionCreate,
    user: dict = Depends(get_current_user),
):
    """Create a new deposit or withdrawal."""
    return create_transaction_impl(
        transaction=transaction,
        user=user,
        get_db=get_db,
        build_insert_payload=build_transaction_insert_payload,
        map_row_to_response_payload=transaction_row_to_response_payload,
        build_transaction_response=lambda payload: TransactionResponse(**payload),
    )


@app.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(
    sportsbook: str | None = None,
    user: dict = Depends(get_current_user),
):
    """List all transactions, optionally filtered by sportsbook."""
    return list_transactions_impl(
        sportsbook=sportsbook,
        user=user,
        get_db=get_db,
        map_rows_to_response_payloads=transaction_rows_to_response_payloads,
        build_transaction_response=lambda payload: TransactionResponse(**payload),
    )


@app.delete("/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: str,
    user: dict = Depends(get_current_user),
):
    """Delete a transaction."""
    return delete_transaction_impl(
        transaction_id=transaction_id,
        user=user,
        get_db=get_db,
    )


@app.get("/balances", response_model=list[BalanceResponse])
def get_balances(user: dict = Depends(get_current_user)):
    """Get computed balance for each sportsbook."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    # Get all transactions for this user
    tx_result = _retry_supabase(lambda: (
        db.table("transactions")
        .select("*")
        .eq("user_id", user["id"])
        .execute()
    ))
    transactions = tx_result.data or []

    # Get all bets for profit calculation
    bets_result = _retry_supabase(lambda: db.table("bets").select("*").eq("user_id", user["id"]).execute())
    payload = compute_balances_by_sportsbook(
        transactions=transactions,
        bets=bets_result.data or [],
        k_factor=settings["k_factor"],
        build_bet_response=build_bet_response,
    )
    return [BalanceResponse(**row) for row in payload]


# ============ Settings ============


@app.get("/settings", response_model=SettingsResponse)
def get_settings(user: dict = Depends(get_current_user)):
    """Get user settings."""
    return get_settings_impl(
        user=user,
        get_db=get_db,
        get_user_settings=get_user_settings,
        build_settings_response=lambda db, user_id, settings: build_settings_response(
            db=db,
            user_id=user_id,
            settings=settings,
            default_sportsbooks=DEFAULT_SPORTSBOOKS,
            compute_k_user=compute_k_user,
            build_effective_k=build_effective_k,
            settings_response_cls=SettingsResponse,
        ),
    )


@app.patch("/settings", response_model=SettingsResponse)
def update_settings(
    settings: SettingsUpdate,
    user: dict = Depends(get_current_user),
):
    """Update user settings."""
    return update_settings_impl(
        settings_update=settings,
        user=user,
        get_db=get_db,
        get_user_settings=get_user_settings,
        build_settings_response=lambda db, user_id, settings_data: build_settings_response(
            db=db,
            user_id=user_id,
            settings=settings_data,
            default_sportsbooks=DEFAULT_SPORTSBOOKS,
            compute_k_user=compute_k_user,
            build_effective_k=build_effective_k,
            settings_response_cls=SettingsResponse,
        ),
        build_update_payload=build_settings_update_payload,
        utc_now_iso=lambda: datetime.now(UTC).isoformat(),
    )


# ============ Utility ============

@app.get("/calculate-ev")
def calculate_ev_preview(
    odds_american: float,
    stake: float,
    promo_type: PromoType,
    boost_percent: float | None = None,
    winnings_cap: float | None = None,
    user: dict = Depends(get_current_user),
):
    """
    Preview EV calculation without saving a bet.
    Useful for real-time calculation as user types.
    """
    return calculate_ev_preview_impl(
        odds_american=odds_american,
        stake=stake,
        promo_type=promo_type,
        boost_percent=boost_percent,
        winnings_cap=winnings_cap,
        user=user,
        get_db=get_db,
        get_user_settings=get_user_settings,
        american_to_decimal=american_to_decimal,
        calculate_ev=calculate_ev,
    )


# ============ Odds Scanner ============

@app.get("/api/scan-bets", response_model=ScanResponse)
async def scan_bets(
    sport: str = "basketball_nba",
    user: dict = Depends(require_scan_rate_limit),
):
    """
    Scan live odds: de-vig Pinnacle, compare to DraftKings,
    return any +EV moneyline opportunities.
    """
    from services.odds_api import scan_for_ev, SUPPORTED_SPORTS

    return await scan_impl(
        sport=sport,
        supported_sports=SUPPORTED_SPORTS,
        scan_for_ev=scan_for_ev,
        map_error=scan_exception_to_http_exception,
        build_scan_response=lambda result: ScanResponse(
            sport=sport,
            opportunities=result["opportunities"],
            events_fetched=result["events_fetched"],
            events_with_both_books=result["events_with_both_books"],
            api_requests_remaining=result.get("api_requests_remaining"),
        ),
    )


@app.get("/api/scan-markets", response_model=FullScanResponse)
async def scan_markets(
    sport: str | None = None,
    user: dict = Depends(require_scan_rate_limit),
):
    """
    Full market scan: returns every matched side between Pinnacle and the target
    books with de-vigged true probabilities. Uses server-side 5-min TTL cache per
    sport. If sport is omitted, scans all supported sports (cached per sport; only
    stale sports hit the API).
    """
    from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS

    return await scan_markets_impl(
        sport=sport,
        user=user,
        get_db=get_db,
        supported_sports=SUPPORTED_SPORTS,
        get_cached_or_scan=get_cached_or_scan,
        run_single_sport_manual_scan=run_single_sport_manual_scan,
        run_all_sports_manual_scan=run_all_sports_manual_scan,
        apply_manual_scan_bundle=apply_manual_scan_bundle,
        set_ops_status=_set_ops_status,
        utc_now_iso=_utc_now_iso,
        piggyback_clv=lambda sides: asyncio.create_task(_piggyback_clv(sides)),
        persist_latest_full_scan=persist_latest_full_scan,
        retry_supabase=_retry_supabase,
        log_event=_log_event,
        annotate_sides=annotate_sides_with_duplicate_state,
        map_error=scan_exception_to_http_exception,
        build_full_scan_response=lambda payload: FullScanResponse(**payload),
        get_environment=lambda: os.getenv("ENVIRONMENT", "production").lower(),
    )


@app.get("/api/scan-latest", response_model=FullScanResponse)
async def scan_latest(user: dict = Depends(require_scan_rate_limit)):
    """
    Return the most recent *global* scan payload, even if stale.

    This is a UX convenience so the Scanner can show something on first load
    (across devices/accounts) without requiring an immediate rescan.
    """
    return scan_latest_impl(
        user=user,
        get_db=get_db,
        resolve_scan_latest_response=resolve_scan_latest_response,
        retry_supabase=_retry_supabase,
        annotate_sides=annotate_sides_with_duplicate_state,
        map_error=scan_cache_exception_to_http_exception,
    )


@app.post("/api/cron/run-scan")
async def cron_run_scan(x_cron_token: str | None = Header(default=None, alias="X-Cron-Token")):
    """
    Cron-triggered scan runner (for Render free sleep). This endpoint is intended to be
    called by an external scheduler (cron-job.org, GitHub Actions, etc.) to wake the
    service and warm the scan cache.

    Security: requires X-Cron-Token header matching the CRON_TOKEN environment variable.
    """
    return await cron_run_scan_impl(
        x_cron_token,
        require_valid_cron_token=_require_valid_cron_token,
        new_run_id=_new_run_id,
        log_event=_log_event,
        set_ops_status=_set_ops_status,
    )


@app.post("/api/cron/run-auto-settle")
async def cron_run_auto_settle(
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Cron-triggered auto-settler runner (for Render free sleep).

    Security: requires X-Cron-Token header matching the CRON_TOKEN environment variable.
    """
    return await cron_run_auto_settle_impl(
        x_cron_token,
        require_valid_cron_token=_require_valid_cron_token,
        new_run_id=_new_run_id,
        log_event=_log_event,
        set_ops_status=_set_ops_status,
        get_db=get_db,
    )


@app.get("/api/ops/status")
def ops_status(x_cron_token: str | None = Header(default=None, alias="X-Cron-Token")):
    """
    Protected operator status endpoint.

    Uses the same CRON_TOKEN auth as cron routes to avoid exposing internals publicly.
    """
    return ops_status_impl(
        x_cron_token,
        require_valid_cron_token=_require_valid_cron_token,
        runtime_state=_runtime_state,
        check_db_ready=_check_db_ready,
        check_scheduler_freshness=_check_scheduler_freshness,
        utc_now_iso=_utc_now_iso,
        get_ops_status=lambda: getattr(app.state, "ops_status", {}),
    )


@app.post("/api/cron/test-discord")
async def cron_test_discord(
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Send a test Discord message (no EV/odds filtering).

    Security: requires X-Cron-Token header matching the CRON_TOKEN environment variable.
    """
    return await cron_test_discord_impl(
        x_cron_token,
        require_valid_cron_token=_require_valid_cron_token,
        new_run_id=_new_run_id,
        log_event=_log_event,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
