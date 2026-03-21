"""
EV Tracker API
FastAPI backend for sports betting EV tracking.
"""

import asyncio
import json
import logging
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, UTC, timedelta
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
    compute_blend_weight, estimate_bonus_retention,
)
from auth import get_current_user
from services.shared_state import allow_fixed_window_rate_limit, is_redis_enabled
from services.scan_cache import persist_latest_full_scan as persist_latest_full_scan_service
from services.settings_response import build_settings_response as build_settings_response_service

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


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _team_from_bet_row(row: dict) -> str:
    team = _normalize_text(row.get("clv_team"))
    if team:
        return team
    event = str(row.get("event") or "").strip()
    if event.upper().endswith(" ML"):
        return _normalize_text(event[:-3])
    return ""


def _event_ref(event_id: str | None, commence_time: str | None) -> str:
    normalized_id = _normalize_text(event_id)
    if normalized_id:
        return f"id:{normalized_id}"
    return f"time:{str(commence_time or '').strip()}"


def _scanner_match_key_from_side(side: dict) -> tuple[str, str, str, str, str]:
    return (
        _normalize_text(side.get("sport")),
        _event_ref(side.get("event_id"), side.get("commence_time")),
        "ml",
        _normalize_text(side.get("team")),
        _normalize_text(side.get("sportsbook")),
    )


def _scanner_match_key_from_bet(row: dict) -> tuple[str, str, str, str, str]:
    return (
        _normalize_text(row.get("clv_sport_key") or row.get("sport")),
        _event_ref(row.get("clv_event_id"), row.get("commence_time")),
        _normalize_text(row.get("market")),
        _team_from_bet_row(row),
        _normalize_text(row.get("sportsbook")),
    )


def _scanner_legacy_match_key_from_side(side: dict) -> tuple[str, str, str, str, str]:
    return (
        _normalize_text(side.get("sport")),
        str(side.get("commence_time") or "").strip(),
        "ml",
        _normalize_text(side.get("team")),
        _normalize_text(side.get("sportsbook")),
    )


def _scanner_legacy_match_key_from_bet(row: dict) -> tuple[str, str, str, str, str]:
    return (
        _normalize_text(row.get("clv_sport_key") or row.get("sport")),
        str(row.get("commence_time") or "").strip(),
        _normalize_text(row.get("market")),
        _team_from_bet_row(row),
        _normalize_text(row.get("sportsbook")),
    )


def _price_quality_from_american(american: float | int | None) -> float | None:
    if american is None:
        return None
    try:
        return american_to_decimal(float(american))
    except Exception:
        return None


def _annotate_sides_with_duplicate_state(db, user_id: str, sides: list[dict]) -> list[dict]:
    """
    Backend-owned scanner duplicate state.

    Matching scope: pending (unsettled exposure) only.
    State enum: new | already_logged | better_now
    """
    if not sides:
        return sides

    pending_res = (
        db.table("bets")
        .select("id,odds_american,sport,market,sportsbook,commence_time,clv_team,event,clv_sport_key,clv_event_id,result")
        .eq("user_id", user_id)
        .eq("result", "pending")
        .eq("market", "ML")
        .execute()
    )

    matches_by_key: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for row in pending_res.data or []:
        key = _scanner_match_key_from_bet(row)
        legacy_key = _scanner_legacy_match_key_from_bet(row)
        if not all([key[0], key[1], key[2], key[3], key[4]]):
            continue
        matches_by_key.setdefault(key, []).append(row)
        matches_by_key.setdefault(legacy_key, []).append(row)

    annotated: list[dict] = []
    for side in sides:
        side_out = dict(side)
        key = _scanner_match_key_from_side(side)
        legacy_key = _scanner_legacy_match_key_from_side(side)
        matched = matches_by_key.get(key, [])
        if not matched:
            matched = matches_by_key.get(legacy_key, [])
        current_odds = side.get("book_odds")
        current_quality = _price_quality_from_american(current_odds)
        side_out["current_odds_american"] = current_odds

        if not matched:
            side_out["scanner_duplicate_state"] = "new"
            side_out["best_logged_odds_american"] = None
            side_out["matched_pending_bet_id"] = None
            annotated.append(side_out)
            continue

        best_row = None
        best_quality = None
        for row in matched:
            q = _price_quality_from_american(row.get("odds_american"))
            if q is None:
                continue
            if best_quality is None or q > best_quality:
                best_quality = q
                best_row = row

        if best_row is None:
            side_out["scanner_duplicate_state"] = "already_logged"
            side_out["best_logged_odds_american"] = None
            side_out["matched_pending_bet_id"] = matched[0].get("id") if matched else None
            annotated.append(side_out)
            continue

        side_out["best_logged_odds_american"] = best_row.get("odds_american")
        side_out["matched_pending_bet_id"] = best_row.get("id")
        if current_quality is not None and best_quality is not None and current_quality > best_quality:
            side_out["scanner_duplicate_state"] = "better_now"
        else:
            side_out["scanner_duplicate_state"] = "already_logged"
        annotated.append(side_out)

    return annotated


def annotate_sides_with_duplicate_state(db, user_id: str, sides: list[dict]) -> list[dict]:
    """Backward-compatible alias for tests and internal callers."""
    return _annotate_sides_with_duplicate_state(db, user_id, sides)


def _cohort_for_side(side: dict) -> str | None:
    sport = _normalize_text(side.get("sport"))
    if sport not in LONGSHOT_AUTOLOG_SPORTS:
        return None

    try:
        ev = float(side.get("ev_percentage"))
        odds = float(side.get("book_odds"))
    except Exception:
        return None

    if LOW_EDGE_EV_MIN <= ev <= LOW_EDGE_EV_MAX and LOW_EDGE_ODDS_MIN <= odds <= LOW_EDGE_ODDS_MAX:
        return LOW_EDGE_COHORT
    if ev >= HIGH_EDGE_EV_MIN and odds >= HIGH_EDGE_ODDS_MIN:
        return HIGH_EDGE_COHORT
    return None


def _sport_display(sport_key: str) -> str:
    mapping = {
        "basketball_nba": "NBA",
        "basketball_ncaab": "NCAAB",
    }
    return mapping.get(sport_key, sport_key)


def _autolog_key_for_side(side: dict, cohort: str) -> str:
    event_ref = _event_ref(side.get("event_id"), side.get("commence_time"))
    return "|".join([
        "v1",
        cohort,
        _normalize_text(side.get("sport")),
        event_ref,
        _normalize_text(side.get("team")),
        _normalize_text(side.get("sportsbook")),
        "ml",
    ])


def _autolog_legacy_key_for_side(side: dict, cohort: str) -> str:
    return "|".join([
        "v1",
        cohort,
        _normalize_text(side.get("sport")),
        str(side.get("commence_time") or "").strip(),
        _normalize_text(side.get("team")),
        _normalize_text(side.get("sportsbook")),
        "ml",
    ])


def _autolog_key_from_pending_row(row: dict) -> str:
    event_ref = _event_ref(row.get("clv_event_id"), row.get("commence_time"))
    return "|".join([
        "v1",
        str(row.get("strategy_cohort") or ""),
        _normalize_text(row.get("clv_sport_key") or row.get("sport")),
        event_ref,
        _normalize_text(row.get("clv_team")),
        _normalize_text(row.get("sportsbook")),
        _normalize_text(row.get("market")),
    ])


def _autolog_legacy_key_from_pending_row(row: dict) -> str:
    return "|".join([
        "v1",
        str(row.get("strategy_cohort") or ""),
        _normalize_text(row.get("clv_sport_key") or row.get("sport")),
        str(row.get("commence_time") or "").strip(),
        _normalize_text(row.get("clv_team")),
        _normalize_text(row.get("sportsbook")),
        _normalize_text(row.get("market")),
    ])


async def _run_longshot_autolog_for_sides(db, *, run_id: str, sides: list[dict]) -> dict:
    """Autolog paper tickets from existing scan sides with deterministic caps and dedupe."""
    if not _is_paper_experiment_autolog_enabled():
        return {"enabled": False, "inserted_total": 0}

    user_id = _paper_experiment_account_user_id()
    if not user_id:
        return {"enabled": True, "configured": False, "inserted_total": 0, "reason": "missing_user_id"}

    eligible: list[dict] = []
    for side in sides:
        cohort = _cohort_for_side(side)
        if not cohort:
            continue
        side_copy = dict(side)
        side_copy["strategy_cohort"] = cohort
        eligible.append(side_copy)

    # Deterministic ordering: higher EV first, then kickoff, then stable composite key.
    eligible.sort(
        key=lambda s: (
            -float(s.get("ev_percentage") or 0),
            str(s.get("commence_time") or ""),
            _autolog_key_for_side(s, s["strategy_cohort"]),
        )
    )

    existing_pending = (
        db.table("bets")
        .select("strategy_cohort,clv_sport_key,commence_time,clv_team,clv_event_id,sportsbook,market")
        .eq("user_id", user_id)
        .eq("result", "pending")
        .eq("market", "ML")
        .in_("strategy_cohort", [LOW_EDGE_COHORT, HIGH_EDGE_COHORT])
        .execute()
    )
    pending_keys = set()
    for row in existing_pending.data or []:
        pending_keys.add(_autolog_key_from_pending_row(row))
        pending_keys.add(_autolog_legacy_key_from_pending_row(row))

    inserted_total = 0
    selected_by_cohort = {LOW_EDGE_COHORT: 0, HIGH_EDGE_COHORT: 0}
    inserted_by_cohort = {LOW_EDGE_COHORT: 0, HIGH_EDGE_COHORT: 0}
    skipped_duplicate = 0
    skipped_rule = 0
    run_at = datetime.now(UTC).isoformat()
    in_run_keys: set[str] = set()

    for side in eligible:
        cohort = side["strategy_cohort"]
        key = _autolog_key_for_side(side, cohort)
        legacy_key = _autolog_legacy_key_for_side(side, cohort)

        if key in pending_keys or key in in_run_keys or legacy_key in pending_keys or legacy_key in in_run_keys:
            skipped_duplicate += 1
            continue

        if inserted_total >= AUTOLOG_MAX_TOTAL:
            skipped_rule += 1
            continue

        if cohort == LOW_EDGE_COHORT and inserted_by_cohort[LOW_EDGE_COHORT] >= AUTOLOG_MAX_LOW:
            skipped_rule += 1
            continue
        if cohort == HIGH_EDGE_COHORT and inserted_by_cohort[HIGH_EDGE_COHORT] >= AUTOLOG_MAX_HIGH:
            skipped_rule += 1
            continue

        selected_by_cohort[cohort] += 1

        run_key = f"{run_id}|{key}"
        existing_run = (
            db.table("bets")
            .select("id")
            .eq("user_id", user_id)
            .eq("auto_log_run_key", run_key)
            .limit(1)
            .execute()
        )
        if existing_run.data:
            skipped_duplicate += 1
            continue

        commence_time = str(side.get("commence_time") or "")
        event_date = commence_time[:10] if len(commence_time) >= 10 else datetime.now(UTC).date().isoformat()

        payload = {
            "user_id": user_id,
            "sport": _sport_display(str(side.get("sport") or "")),
            "event": f"{side.get('team')} ML",
            "market": "ML",
            "sportsbook": side.get("sportsbook"),
            "promo_type": "standard",
            "odds_american": side.get("book_odds"),
            "stake": AUTOLOG_PAPER_STAKE,
            "result": BetResult.PENDING.value,
            "event_date": event_date,
            "pinnacle_odds_at_entry": side.get("pinnacle_odds"),
            "commence_time": commence_time,
            "clv_team": side.get("team"),
            "clv_sport_key": side.get("sport"),
            "clv_event_id": side.get("event_id"),
            "true_prob_at_entry": side.get("true_prob"),
            "is_paper": True,
            "strategy_cohort": cohort,
            "auto_logged": True,
            "auto_log_run_at": run_at,
            "auto_log_run_key": run_key,
            "scan_ev_percent_at_log": side.get("ev_percentage"),
            "book_odds_at_log": side.get("book_odds"),
            "reference_odds_at_log": side.get("pinnacle_odds"),
        }

        db.table("bets").insert(payload).execute()
        inserted_total += 1
        inserted_by_cohort[cohort] += 1
        in_run_keys.add(key)
        in_run_keys.add(legacy_key)
        pending_keys.add(key)
        pending_keys.add(legacy_key)

    return {
        "enabled": True,
        "configured": True,
        "run_id": run_id,
        "candidates_seen": len(sides),
        "eligible_seen": len(eligible),
        "selected_by_cohort": selected_by_cohort,
        "inserted_total": inserted_total,
        "inserted_by_cohort": inserted_by_cohort,
        "skipped_duplicate": skipped_duplicate,
        "skipped_rule": skipped_rule,
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


def _get_environment() -> str:
    return os.getenv("ENVIRONMENT", "production").lower()


def _scanner_supported_sports(surface: str) -> list[str]:
    if surface == "player_props":
        from services.odds_api import SUPPORTED_SPORTS

        return SUPPORTED_SPORTS
    from services.odds_api import SUPPORTED_SPORTS

    return SUPPORTED_SPORTS


async def _get_cached_or_scan_for_surface(surface: str, sport: str, *, source: str = "unknown") -> dict:
    if surface == "player_props":
        from services.player_props import get_cached_or_scan_player_props

        return await get_cached_or_scan_player_props(sport, source=source)
    from services.odds_api import get_cached_or_scan

    return await get_cached_or_scan(sport, source=source)


async def _scan_for_ev_surface(sport: str) -> dict:
    from services.odds_api import scan_for_ev

    return await scan_for_ev(sport)


def _build_scan_response(*, sport: str, result: dict) -> ScanResponse:
    return ScanResponse(
        sport=sport,
        opportunities=result["opportunities"],
        events_fetched=result["events_fetched"],
        events_with_both_books=result["events_with_both_books"],
        api_requests_remaining=result.get("api_requests_remaining"),
    )


def _build_full_scan_response(payload: dict) -> FullScanResponse:
    return FullScanResponse(**payload)


def _persist_latest_full_scan(
    *,
    db,
    surface: str,
    sport: str,
    sides: list[dict],
    events_fetched: int,
    events_with_both_books: int,
    api_requests_remaining: str | None,
    scanned_at: str | None,
    retry_supabase,
    log_event,
):
    return persist_latest_full_scan_service(
        db=db,
        surface=surface,
        sport=sport,
        sides=sides,
        events_fetched=events_fetched,
        events_with_both_books=events_with_both_books,
        api_requests_remaining=api_requests_remaining,
        scanned_at=scanned_at,
        retry_supabase=retry_supabase,
        log_event=log_event,
    )


def _with_surface(surface: str, sides: list[dict]) -> list[dict]:
    return [
        side if isinstance(side, dict) and side.get("surface") else {"surface": surface, **side}
        for side in sides
    ]


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
        "last_ops_trigger_scan": None,
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


def _require_ops_token(x_ops_token: str | None, x_cron_token: str | None = None) -> None:
    expected = os.getenv("CRON_TOKEN")
    ops_token = x_ops_token if isinstance(x_ops_token, str) else None
    cron_token = x_cron_token if isinstance(x_cron_token, str) else None
    provided = ops_token or cron_token
    if not provided:
        raise HTTPException(status_code=401, detail="Invalid ops token")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_TOKEN not configured on server")
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid ops token")

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

    run_id = _new_run_id("clv_daily")
    started_at = time.monotonic()
    _record_scheduler_heartbeat("clv_daily", run_id, "started")
    _log_event("scheduler.clv_daily.started", run_id=run_id)
    db = get_db()
    try:
        updated = await fetch_clv_for_pending_bets(db)
        _log_event(
            "scheduler.clv_daily.completed",
            run_id=run_id,
            updated=updated,
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )
        _record_scheduler_heartbeat(
            "clv_daily",
            run_id,
            "success",
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )
    except Exception as e:
        _record_scheduler_heartbeat(
            "clv_daily",
            run_id,
            "failure",
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            error=str(e),
        )
        _log_event(
            "scheduler.clv_daily.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )


async def _run_jit_clv_snatcher_job():
    """JIT CLV Snatcher: capture closing Pinnacle lines for games starting in the next 20 min."""
    from services.odds_api import run_jit_clv_snatcher

    run_id = _new_run_id("jit_clv")
    started_at = time.monotonic()
    _record_scheduler_heartbeat("jit_clv", run_id, "started")
    _log_event("scheduler.jit_clv.started", run_id=run_id)
    db = get_db()
    try:
        updated = await run_jit_clv_snatcher(db)
        _log_event(
            "scheduler.jit_clv.completed",
            run_id=run_id,
            updated=updated,
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )
        _record_scheduler_heartbeat(
            "jit_clv",
            run_id,
            "success",
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )
        if updated:
            print(f"[JIT CLV] Captured closing lines for {updated} bet(s).")
            # Optional notification (guarded to avoid Discord spam).
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
                asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))
    except Exception as e:
        _record_scheduler_heartbeat(
            "jit_clv",
            run_id,
            "failure",
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            error=str(e),
        )
        _log_event(
            "scheduler.jit_clv.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )


async def _run_auto_settler_job():
    """Auto-Settler: grade completed ML bets using The Odds API /scores endpoint."""
    from services.odds_api import run_auto_settler, get_last_auto_settler_summary

    run_id = _new_run_id("auto_settler")
    started_at = time.monotonic()
    _record_scheduler_heartbeat("auto_settler", run_id, "started")
    _log_event("scheduler.auto_settler.started", run_id=run_id)
    db = get_db()
    try:
        settled = await run_auto_settler(db, source="auto_settle_scheduler")
        _log_event(
            "scheduler.auto_settler.completed",
            run_id=run_id,
            settled=settled,
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )
        _record_scheduler_heartbeat(
            "auto_settler",
            run_id,
            "success",
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        )
        _set_ops_status(
            "last_auto_settle",
            {
                "source": "scheduler",
                "run_id": run_id,
                "settled": settled,
                "duration_ms": round((time.monotonic() - started_at) * 1000, 2),
                "captured_at": _utc_now_iso(),
            },
        )
        summary = get_last_auto_settler_summary()
        if summary:
            _set_ops_status("last_auto_settle_summary", summary)
        if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1":
            from services.discord_alerts import send_discord_webhook

            payload = {
                "embeds": [
                    {
                        "title": "Auto-settle run complete",
                        "description": f"Graded **{settled}** bet(s).",
                        "fields": [
                            {"name": "Source", "value": "scheduler", "inline": True},
                            {"name": "Run id", "value": run_id, "inline": True},
                            {
                                "name": "Duration",
                                "value": f"{round((time.monotonic() - started_at) * 1000, 2)} ms",
                                "inline": True,
                            },
                        ],
                    }
                ]
            }
            asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))
    except Exception as e:
        _record_scheduler_heartbeat(
            "auto_settler",
            run_id,
            "failure",
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            error=str(e),
        )
        _log_event(
            "scheduler.auto_settler.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
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

    total_sides = 0
    alerts_scheduled = 0
    hard_errors = 0
    all_sides: list[dict] = []
    total_events = 0
    total_with_both = 0
    min_remaining: str | None = None
    oldest_fetched: float | None = None
    from services.discord_alerts import schedule_alerts

    for sport_key in SUPPORTED_SPORTS:
        try:
            result = await get_cached_or_scan(sport_key, source="scheduled_scan")
            sides_count = len(result.get("sides") or [])
            fetched = result.get("events_fetched")
            with_both = result.get("events_with_both_books")
            sides = result.get("sides") or []
            all_sides.extend(sides)
            total_sides += len(sides)
            total_events += int(fetched or 0)
            total_with_both += int(with_both or 0)

            rem = result.get("api_requests_remaining")
            if rem is not None:
                try:
                    r = int(rem)
                    min_remaining = str(r) if min_remaining is None else str(min(r, int(min_remaining)))
                except ValueError:
                    min_remaining = str(rem)

            ft = result.get("fetched_at")
            if ft is not None:
                oldest_fetched = ft if oldest_fetched is None else min(oldest_fetched, ft)

            alerts_scheduled += schedule_alerts(sides)
            _log_event(
                "scheduler.scan.sport_completed",
                run_id=run_id,
                sport=sport_key,
                sides=sides_count,
                events_fetched=fetched,
                events_with_both_books=with_both,
            )
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                _log_event(
                    "scheduler.scan.sport_skipped",
                    run_id=run_id,
                    sport=sport_key,
                    status=404,
                    reason="no odds",
                )
                continue
            _log_event(
                "scheduler.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                error_class=type(e).__name__,
                error=str(e),
            )
            hard_errors += 1
        except Exception as e:
            # Never crash the server/scheduler; log and continue.
            _log_event(
                "scheduler.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                error_class=type(e).__name__,
                error=str(e),
            )
            hard_errors += 1

    scanned_at = (
        datetime.fromtimestamp(oldest_fetched, tz=UTC).isoformat().replace("+00:00", "Z")
        if oldest_fetched
        else _utc_now_iso()
    )

    # Keep Scanner's "latest scan" payload in sync for scheduled runs, not only manual scans.
    try:
        _persist_latest_full_scan(
            db=get_db(),
            surface="straight_bets",
            sport="all",
            sides=all_sides,
            events_fetched=total_events,
            events_with_both_books=total_with_both,
            api_requests_remaining=min_remaining,
            scanned_at=scanned_at,
            retry_supabase=_retry_supabase,
            log_event=_log_event,
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
    autolog_summary = None
    try:
        autolog_summary = await _run_longshot_autolog_for_sides(db=get_db(), run_id=run_id, sides=all_sides)
    except Exception as e:
        autolog_summary = {
            "enabled": _is_paper_experiment_autolog_enabled(),
            "error": f"{type(e).__name__}: {e}",
        }
        _log_event(
            "scheduler.scan.autolog.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
        )

    _log_event(
        "scheduler.scan.completed",
        run_id=run_id,
        finished_at=finished + "Z",
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        autolog_summary=autolog_summary,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
    )
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    if hard_errors:
        _record_scheduler_heartbeat(
            "scheduled_scan",
            run_id,
            "failure",
            duration_ms=duration_ms,
            error=f"{hard_errors} sport(s) failed",
        )
    else:
        _record_scheduler_heartbeat(
            "scheduled_scan",
            run_id,
            "success",
            duration_ms=duration_ms,
        )

    _set_ops_status(
        "last_scheduler_scan",
        {
            "run_id": run_id,
            "started_at": started + "Z",
            "finished_at": finished + "Z",
            "duration_ms": duration_ms,
            "total_sides": total_sides,
            "alerts_scheduled": alerts_scheduled,
            "hard_errors": hard_errors,
            "autolog_summary": autolog_summary,
        },
    )

    # Optional heartbeat so we can confirm the scheduled scan ran even when it finds no lines.
    # Send only when enabled and when no alerts were scheduled.
    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1" and alerts_scheduled == 0:
        from services.discord_alerts import send_discord_webhook

        payload = {
            "embeds": [
                {
                    "title": "Scheduled scan complete (no alerts)",
                    "description": "The scheduled scan ran successfully but found no qualifying lines to alert on.",
                    "fields": [
                        {"name": "Started (UTC)", "value": started + "Z", "inline": True},
                        {"name": "Finished (UTC)", "value": finished + "Z", "inline": True},
                        {"name": "Total sides", "value": str(total_sides), "inline": True},
                        {"name": "Alerts scheduled", "value": str(alerts_scheduled), "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))


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
    # Explicit timezone keeps scheduler behavior consistent across hosts.
    auto_settle_trigger = (
        CronTrigger(hour=4, minute=0, timezone=PHOENIX_TZ)
        if PHOENIX_TZ is not None
        else CronTrigger(hour=4, minute=0)
    )
    scheduler.add_job(
        _run_auto_settler_job,
        auto_settle_trigger,
        misfire_grace_time=60 * 60,
        coalesce=True,
    )
    if PHOENIX_TZ is not None:
        scheduled_scan_times: list[tuple[int, int]] = [(16, 30), (18, 30)]
        temp_scan_time = _parse_hhmm(os.getenv(SCHEDULED_SCAN_TEMP_TIME_ENV))
        if temp_scan_time is not None and temp_scan_time not in scheduled_scan_times:
            scheduled_scan_times.append(temp_scan_time)

        for hour, minute in scheduled_scan_times:
            scheduler.add_job(
                _run_scheduled_scan_job,
                CronTrigger(hour=hour, minute=minute, timezone=PHOENIX_TZ),
            )
    else:
        print("[Scheduler] Phoenix timezone unavailable; skipping scheduled scan jobs.")
    scheduler.start()
    app.state.scheduler_started_at = _utc_now_iso()
    if hasattr(scheduler, "get_jobs"):
        jobs_count = len(scheduler.get_jobs())
    else:
        jobs_count = len(getattr(scheduler, "jobs", []))
    _log_event("scheduler.started", jobs=jobs_count)
    app.state.scheduler = scheduler


async def stop_scheduler():
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
            _log_event("scheduler.stopped")
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

# Route modules (APIRouter)
from routes.scan_routes import router as scan_router
from routes.ops_cron import router as ops_router
from routes.settings_routes import router as settings_router
from routes.transactions_routes import router as transactions_router
from routes.utility_routes import router as utility_router
from routes.admin_routes import router as admin_router

app.include_router(scan_router)
app.include_router(ops_router)
app.include_router(settings_router)
app.include_router(transactions_router)
app.include_router(utility_router)
app.include_router(admin_router)

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
        "onboarding_state": {
            "version": 1,
            "completed": [],
            "dismissed": [],
            "last_seen_at": None,
        },
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
            .gte("created_at", (datetime.now(UTC) - timedelta(days=999)).isoformat())  # All settled bets
            .neq("result", "pending")  # Exclude pending bets
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
        surface=row.get("surface") or "straight_bets",
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
        clv_event_id=row.get("clv_event_id"),
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
        source_event_id=row.get("source_event_id"),
        source_market_key=row.get("source_market_key"),
        source_selection_key=row.get("source_selection_key"),
        participant_name=row.get("participant_name"),
        participant_id=row.get("participant_id"),
        selection_side=row.get("selection_side"),
        line_value=row.get("line_value"),
        selection_meta=row.get("selection_meta"),
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
        "surface": bet.surface,
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
        "clv_event_id": bet.clv_event_id,
        "true_prob_at_entry": bet.true_prob_at_entry,
        "source_event_id": bet.source_event_id,
        "source_market_key": bet.source_market_key,
        "source_selection_key": bet.source_selection_key,
        "participant_name": bet.participant_name,
        "participant_id": bet.participant_id,
        "selection_side": bet.selection_side,
        "line_value": bet.line_value,
        "selection_meta": bet.selection_meta,
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
    if bet.surface is not None:
        data["surface"] = bet.surface
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


def backfill_ev_locks(user: dict = Depends(get_current_user)):
    """
    One-off endpoint: freeze EV on all existing promo bets that don't yet have
    locked EV fields. Safe to call multiple times (idempotent: skips rows that
    already have ev_locked_at set).
    """
    db = get_db()
    settings = get_user_settings(db, user["id"])

    res = _retry_supabase(lambda: (
        db.table("bets")
        .select("*")
        .eq("user_id", user["id"])
        .is_("ev_locked_at", "null")
        .in_("promo_type", list(EV_LOCK_PROMO_TYPES))
        .execute()
    ))
    rows = res.data or []
    locked = 0
    for row in rows:
        try:
            _lock_ev_for_row(db, row["id"], user["id"], row, settings)
            locked += 1
        except Exception as e:
            logger.warning("backfill_ev_lock.failed bet_id=%s err=%s", row["id"], e)
    return {"backfilled": locked, "total_eligible": len(rows)}


# ============ Summary / Dashboard ============

@app.get("/summary", response_model=SummaryResponse)
def get_summary(user: dict = Depends(get_current_user)):
    """Get dashboard summary statistics."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    k_factor = settings["k_factor"]

    result = _retry_supabase(lambda: db.table("bets").select("*").eq("user_id", user["id"]).execute())
    bets = result.data

    if not bets:
        return SummaryResponse(
            total_bets=0,
            pending_bets=0,
            total_ev=0.0,
            total_real_profit=0.0,
            variance=0.0,
            win_count=0,
            loss_count=0,
            win_rate=None,
            ev_by_sportsbook={},
            profit_by_sportsbook={},
            ev_by_sport={},
        )

    total_ev = 0.0
    total_real_profit = 0.0
    win_count = 0
    loss_count = 0
    pending_count = 0

    ev_by_sportsbook: dict[str, float] = {}
    profit_by_sportsbook: dict[str, float] = {}
    ev_by_sport: dict[str, float] = {}

    for row in bets:
        bet_response = build_bet_response(row, k_factor)

        # Totals
        total_ev += bet_response.ev_total
        if bet_response.real_profit is not None:
            total_real_profit += bet_response.real_profit

        # Counts
        if bet_response.result == BetResult.WIN:
            win_count += 1
        elif bet_response.result == BetResult.LOSS:
            loss_count += 1
        elif bet_response.result == BetResult.PENDING:
            pending_count += 1

        # By sportsbook
        book = bet_response.sportsbook
        ev_by_sportsbook[book] = ev_by_sportsbook.get(book, 0) + bet_response.ev_total
        if bet_response.real_profit is not None:
            profit_by_sportsbook[book] = profit_by_sportsbook.get(book, 0) + bet_response.real_profit

        # By sport
        sport = bet_response.sport
        ev_by_sport[sport] = ev_by_sport.get(sport, 0) + bet_response.ev_total

    settled_count = win_count + loss_count
    win_rate = (win_count / settled_count) if settled_count > 0 else None

    return SummaryResponse(
        total_bets=len(bets),
        pending_bets=pending_count,
        total_ev=round(total_ev, 2),
        total_real_profit=round(total_real_profit, 2),
        variance=round(total_real_profit - total_ev, 2),
        win_count=win_count,
        loss_count=loss_count,
        win_rate=round(win_rate, 4) if win_rate else None,
        ev_by_sportsbook={k: round(v, 2) for k, v in ev_by_sportsbook.items()},
        profit_by_sportsbook={k: round(v, 2) for k, v in profit_by_sportsbook.items()},
        ev_by_sport={k: round(v, 2) for k, v in ev_by_sport.items()},
    )


# ============ Transactions ============

def create_transaction(
    transaction: TransactionCreate,
    user: dict = Depends(get_current_user),
):
    """Create a new deposit or withdrawal."""
    db = get_db()

    data = {
        "user_id": user["id"],
        "sportsbook": transaction.sportsbook,
        "type": transaction.type.value,
        "amount": transaction.amount,
        "notes": transaction.notes,
    }

    # If created_at is provided (for undo), use it; otherwise let database set it
    if transaction.created_at:
        data["created_at"] = transaction.created_at.isoformat()

    result = db.table("transactions").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create transaction")

    row = result.data[0]
    return TransactionResponse(
        id=row["id"],
        created_at=row["created_at"],
        sportsbook=row["sportsbook"],
        type=row["type"],
        amount=row["amount"],
        notes=row.get("notes"),
    )


def list_transactions(
    sportsbook: str | None = None,
    user: dict = Depends(get_current_user),
):
    """List all transactions, optionally filtered by sportsbook."""
    db = get_db()

    query = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
    )

    if sportsbook:
        query = query.eq("sportsbook", sportsbook)

    result = query.execute()

    return [
        TransactionResponse(
            id=row["id"],
            created_at=row["created_at"],
            sportsbook=row["sportsbook"],
            type=row["type"],
            amount=row["amount"],
            notes=row.get("notes"),
        )
        for row in result.data
    ]


def delete_transaction(
    transaction_id: str,
    user: dict = Depends(get_current_user),
):
    """Delete a transaction."""
    db = get_db()
    result = (
        db.table("transactions")
        .delete()
        .eq("id", transaction_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if result.status_code and result.status_code >= 400:
        raise HTTPException(status_code=500, detail="Failed to delete transaction")

    if not result.data:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {"deleted": True, "id": transaction_id}


@app.get("/balances", response_model=list[BalanceResponse])
def get_balances(user: dict = Depends(get_current_user)):
    """Get computed balance for each sportsbook."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    k_factor = settings["k_factor"]

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
    bets = bets_result.data or []

    # Aggregate by sportsbook
    sportsbook_data = {}

    # Process transactions
    for tx in transactions:
        book = tx["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0, "withdrawals": 0, "profit": 0, "pending": 0}

        if tx["type"] == "deposit":
            sportsbook_data[book]["deposits"] += float(tx["amount"])
        else:
            sportsbook_data[book]["withdrawals"] += float(tx["amount"])

    # Process bets for profit and pending
    for row in bets:
        book = row["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0, "withdrawals": 0, "profit": 0, "pending": 0}

        bet = build_bet_response(row, k_factor)

        if bet.result == BetResult.PENDING:
            # Pending cash exposure: bonus bet stake is not real cash.
            if bet.promo_type != "bonus_bet":
                sportsbook_data[book]["pending"] += bet.stake
        elif bet.real_profit is not None:
            sportsbook_data[book]["profit"] += bet.real_profit

    # Build response
    balances = []
    for book, data in sorted(sportsbook_data.items()):
        net_deposits = data["deposits"] - data["withdrawals"]
        balance = net_deposits + data["profit"] - data["pending"]

        balances.append(BalanceResponse(
            sportsbook=book,
            deposits=round(data["deposits"], 2),
            withdrawals=round(data["withdrawals"], 2),
            net_deposits=round(net_deposits, 2),
            profit=round(data["profit"], 2),
            pending=round(data["pending"], 2),
            balance=round(balance, 2),
        ))

    return balances


# ============ Settings ============

def _build_settings_response(db, user_id: str, s: dict) -> SettingsResponse:
    """Construct SettingsResponse including derived k-factor fields."""
    return build_settings_response_service(
        db=db,
        user_id=user_id,
        settings=s,
        default_sportsbooks=DEFAULT_SPORTSBOOKS,
        compute_k_user=compute_k_user,
        build_effective_k=build_effective_k,
        settings_response_cls=SettingsResponse,
    )


def get_settings(user: dict = Depends(get_current_user)):
    """Get user settings."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    return _build_settings_response(db, user["id"], settings)


def update_settings(
    settings: SettingsUpdate,
    user: dict = Depends(get_current_user),
):
    """Update user settings."""
    db = get_db()

    # Ensure settings row exists
    get_user_settings(db, user["id"])

    data = {}
    if settings.k_factor is not None:
        data["k_factor"] = settings.k_factor
    if settings.default_stake is not None:
        data["default_stake"] = settings.default_stake
    if settings.preferred_sportsbooks is not None:
        data["preferred_sportsbooks"] = settings.preferred_sportsbooks
    if settings.k_factor_mode is not None:
        data["k_factor_mode"] = settings.k_factor_mode
    if settings.k_factor_min_stake is not None:
        data["k_factor_min_stake"] = settings.k_factor_min_stake
    if settings.k_factor_smoothing is not None:
        data["k_factor_smoothing"] = settings.k_factor_smoothing
    if settings.k_factor_clamp_min is not None:
        data["k_factor_clamp_min"] = settings.k_factor_clamp_min
    if settings.k_factor_clamp_max is not None:
        data["k_factor_clamp_max"] = settings.k_factor_clamp_max
    if settings.onboarding_state is not None:
        data["onboarding_state"] = settings.onboarding_state

    if data:
        data["updated_at"] = datetime.now(UTC).isoformat()
        db.table("settings").update(data).eq("user_id", user["id"]).execute()

    updated = get_user_settings(db, user["id"])
    return _build_settings_response(db, user["id"], updated)


# ============ Utility ============

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
    db = get_db()
    settings = get_user_settings(db, user["id"])

    decimal_odds = american_to_decimal(odds_american)

    result = calculate_ev(
        stake=stake,
        decimal_odds=decimal_odds,
        promo_type=promo_type.value,
        k_factor=settings["k_factor"],
        boost_percent=boost_percent,
        winnings_cap=winnings_cap,
    )

    return {
        "odds_american": odds_american,
        "odds_decimal": decimal_odds,
        "stake": stake,
        "promo_type": promo_type.value,
        **result,
    }


# ============ Odds Scanner ============

async def scan_bets(
    sport: str = "basketball_nba",
    user: dict = Depends(require_scan_rate_limit),
):
    """
    Scan live odds: de-vig Pinnacle, compare to DraftKings,
    return any +EV moneyline opportunities.
    """
    from services.odds_api import scan_for_ev, fetch_odds, SUPPORTED_SPORTS

    if sport not in SUPPORTED_SPORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(SUPPORTED_SPORTS)}",
        )

    try:
        result = await scan_for_ev(sport)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Odds API error: {e}")

    return _build_scan_response(sport=sport, result=result)


async def scan_markets(
    surface: str = "straight_bets",
    sport: str | None = None,
    user: dict = Depends(require_scan_rate_limit),
):
    """
    Full market scan: returns every matched side between Pinnacle and the target
    books with de-vigged true probabilities. Uses server-side 5-min TTL cache per
    sport. If sport is omitted, scans all supported sports (cached per sport; only
    stale sports hit the API).
    """
    from datetime import datetime, timezone

    db = get_db()
    supported_sports = _scanner_supported_sports(surface)

    if sport is not None and sport not in supported_sports:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(supported_sports)}",
        )

    try:
        if sport is not None:
            result = await _get_cached_or_scan_for_surface(surface, sport, source="manual_scan")
            base_sides = _with_surface(surface, result["sides"])
            response_sides = _with_surface(surface, _annotate_sides_with_duplicate_state(db, user["id"], base_sides))
            scanned_at = datetime.fromtimestamp(result["fetched_at"], tz=UTC).isoformat().replace("+00:00", "Z")
            _set_ops_status(
                "last_manual_scan",
                {
                    "captured_at": _utc_now_iso(),
                    "sport": sport,
                    "events_fetched": result.get("events_fetched"),
                    "events_with_both_books": result.get("events_with_both_books"),
                    "total_sides": len(base_sides or []),
                    "api_requests_remaining": result.get("api_requests_remaining"),
                },
            )
            # Piggyback CLV update — zero extra API calls
            if surface == "straight_bets":
                asyncio.create_task(_piggyback_clv(base_sides))
            response = FullScanResponse(
                surface=surface,
                sport=sport,
                sides=response_sides,
                events_fetched=result["events_fetched"],
                events_with_both_books=result["events_with_both_books"],
                api_requests_remaining=result.get("api_requests_remaining"),
                scanned_at=scanned_at,
            )
            _persist_latest_full_scan(
                db=db,
                surface=surface,
                sport=sport,
                sides=base_sides,
                events_fetched=result["events_fetched"],
                events_with_both_books=result["events_with_both_books"],
                api_requests_remaining=result.get("api_requests_remaining"),
                scanned_at=scanned_at,
                retry_supabase=_retry_supabase,
                log_event=_log_event,
            )
            return response
        # Full scan: all sports (skip any that 404 — e.g. out of season)
        all_sides = []
        total_events = 0
        total_with_both = 0
        min_remaining = None
        oldest_fetched = None
        from os import getenv
        env = getenv("ENVIRONMENT", "production").lower()
        sports_to_scan = ["basketball_nba"] if env == "development" else supported_sports
        for s in sports_to_scan:
            try:
                result = await _get_cached_or_scan_for_surface(surface, s, source="manual_scan")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue  # sport has no odds right now (e.g. off-season)
                raise
            all_sides.extend(result["sides"])
            total_events += result["events_fetched"]
            total_with_both += result["events_with_both_books"]
            rem = result.get("api_requests_remaining")
            if rem is not None:
                try:
                    r = int(rem)
                    min_remaining = str(r) if min_remaining is None else str(min(r, int(min_remaining)))
                except ValueError:
                    min_remaining = rem
            ft = result.get("fetched_at")
            if ft is not None:
                oldest_fetched = ft if oldest_fetched is None else min(oldest_fetched, ft)
        scanned_at = (
            datetime.fromtimestamp(oldest_fetched, tz=UTC).isoformat().replace("+00:00", "Z")
            if oldest_fetched
            else None
        )
        _set_ops_status(
            "last_manual_scan",
            {
                "captured_at": _utc_now_iso(),
                "sport": "all",
                "events_fetched": total_events,
                "events_with_both_books": total_with_both,
                "total_sides": len(all_sides),
                "api_requests_remaining": min_remaining,
            },
        )
        # Piggyback CLV update across all scanned sides — zero extra API calls
        all_sides = _with_surface(surface, all_sides)
        if surface == "straight_bets":
            asyncio.create_task(_piggyback_clv(all_sides))
        response_sides = _with_surface(surface, _annotate_sides_with_duplicate_state(db, user["id"], all_sides))
        response = FullScanResponse(
            surface=surface,
            sport="all",
            sides=response_sides,
            events_fetched=total_events,
            events_with_both_books=total_with_both,
            api_requests_remaining=min_remaining,
            scanned_at=scanned_at,
        )
        _persist_latest_full_scan(
            db=db,
            surface=surface,
            sport="all",
            sides=all_sides,
            events_fetched=total_events,
            events_with_both_books=total_with_both,
            api_requests_remaining=min_remaining,
            scanned_at=scanned_at,
            retry_supabase=_retry_supabase,
            log_event=_log_event,
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Odds API error: {e}")


async def scan_latest(
    surface: str = "straight_bets",
    user: dict = Depends(require_scan_rate_limit),
):
    """
    Return the most recent *global* scan payload, even if stale.

    This is a UX convenience so the Scanner can show something on first load
    (across devices/accounts) without requiring an immediate rescan.
    """
    db = get_db()
    try:
        try:
            cache_key = f"{surface}:latest"
            res = _retry_supabase(lambda: (
                db.table("global_scan_cache")
                .select("payload")
                .eq("key", cache_key)
                .limit(1)
                .execute()
            ))
        except Exception as e:
            # Supabase PostgREST returns PGRST205 when the table doesn't exist / schema cache is stale.
            # Treat as "no scans yet" so the UI doesn't show scary errors.
            msg = str(e)
            if "PGRST205" in msg or ("global_scan_cache" in msg and "schema cache" in msg):
                return FullScanResponse(
                    surface=surface,
                    sport="all",
                    sides=[],
                    events_fetched=0,
                    events_with_both_books=0,
                    api_requests_remaining=None,
                    scanned_at=None,
                )
            raise
        if not res.data and surface == "straight_bets":
            res = _retry_supabase(lambda: (
                db.table("global_scan_cache")
                .select("payload")
                .eq("key", "latest")
                .limit(1)
                .execute()
            ))
        if not res.data:
            # Return an empty payload (200) so the UI doesn't treat this as an error.
            return FullScanResponse(
                surface=surface,
                sport="all",
                sides=[],
                events_fetched=0,
                events_with_both_books=0,
                api_requests_remaining=None,
                scanned_at=None,
            )
        payload = res.data[0].get("payload")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Invalid scan cache payload")
        sides = payload.get("sides") if isinstance(payload.get("sides"), list) else []
        payload["surface"] = payload.get("surface") or surface
        payload["sides"] = [
            side if isinstance(side, dict) and side.get("surface") else {"surface": surface, **side}
            for side in _annotate_sides_with_duplicate_state(db, user["id"], sides)
        ]
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load scan cache: {e}")


async def ops_trigger_scan(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Manual operator scan trigger.

    Security: requires X-Ops-Token header matching CRON_TOKEN.
    """
    _require_ops_token(x_ops_token, x_cron_token)

    run_id = _new_run_id("ops_scan")
    started_clock = time.monotonic()
    _log_event("ops.trigger.scan.started", run_id=run_id)

    from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS

    started = datetime.now(UTC).isoformat() + "Z"
    scanned = []
    errors: list[dict] = []
    total_sides = 0
    alerts_scheduled = 0
    from services.discord_alerts import schedule_alerts

    for sport_key in SUPPORTED_SPORTS:
        try:
            result = await get_cached_or_scan(sport_key, source="ops_trigger_scan")
            sides = result.get("sides") or []
            scanned.append(
                {
                    "sport": sport_key,
                    "sides": len(sides),
                    "events_fetched": result.get("events_fetched"),
                    "events_with_both_books": result.get("events_with_both_books"),
                    "api_requests_remaining": result.get("api_requests_remaining"),
                }
            )
            total_sides += len(sides)
            alerts_scheduled += schedule_alerts(sides)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            # 404 just means out of season / no odds; treat as non-fatal.
            if status == 404:
                errors.append({"sport": sport_key, "status": 404, "error": "no odds"})
                _log_event("ops.trigger.scan.sport_skipped", run_id=run_id, sport=sport_key, status=404, reason="no odds")
                continue
            errors.append({"sport": sport_key, "status": status, "error": str(e)})
            _log_event(
                "ops.trigger.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                status=status,
                error_class=type(e).__name__,
                error=str(e),
            )
        except Exception as e:
            errors.append({"sport": sport_key, "error": str(e)})
            _log_event(
                "ops.trigger.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                error_class=type(e).__name__,
                error=str(e),
            )

    finished = datetime.now(UTC).isoformat() + "Z"
    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    _log_event(
        "ops.trigger.scan.completed",
        run_id=run_id,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        error_count=len(errors),
        duration_ms=duration_ms,
    )

    _set_ops_status(
        "last_ops_trigger_scan",
        {
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "total_sides": total_sides,
            "alerts_scheduled": alerts_scheduled,
            "error_count": len(errors),
            "errors": errors,
        },
    )

    # Optional heartbeat so we can confirm the scheduled scan ran even when it finds no lines.
    # Reuse the existing heartbeat flag to avoid adding another env var.
    # Sends only when enabled and when no alerts were scheduled.
    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1" and alerts_scheduled == 0:
        from services.discord_alerts import send_discord_webhook

        payload = {
            "embeds": [
                {
                    "title": "Scan run complete (no alerts)",
                    "description": "The scheduled scan ran successfully but found no qualifying lines to alert on.",
                    "fields": [
                        {"name": "Started (UTC)", "value": started, "inline": True},
                        {"name": "Finished (UTC)", "value": finished, "inline": True},
                        {"name": "Total sides", "value": str(total_sides), "inline": True},
                        {"name": "Alerts scheduled", "value": str(alerts_scheduled), "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "sports_scanned": scanned,
        "errors": errors,
        "total_sides": total_sides,
        "alerts_scheduled": alerts_scheduled,
    }


async def ops_trigger_auto_settle(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Manual operator auto-settler trigger.

    Security: requires X-Ops-Token header matching CRON_TOKEN.
    """
    _require_ops_token(x_ops_token, x_cron_token)

    run_id = _new_run_id("ops_auto_settle")
    started_clock = time.monotonic()
    _log_event("ops.trigger.auto_settle.started", run_id=run_id)

    from services.odds_api import get_last_auto_settler_summary

    db = get_db()
    started = datetime.now(UTC).isoformat() + "Z"
    try:
        from services.odds_api import run_auto_settler

        settled = await run_auto_settler(db, source="auto_settle_ops_trigger")
        _log_event("ops.trigger.auto_settle.completed", run_id=run_id, settled=settled)
    except Exception as e:
        # Never crash the server; return error for cron logs.
        _log_event(
            "ops.trigger.auto_settle.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=round((time.monotonic() - started_clock) * 1000, 2),
        )
        raise HTTPException(status_code=502, detail=f"Auto-settler error: {e}")
    finally:
        finished = datetime.now(UTC).isoformat() + "Z"

    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)

    _set_ops_status(
        "last_auto_settle",
        {
            "source": "ops_trigger",
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "settled": settled,
        },
    )
    summary = get_last_auto_settler_summary()
    if summary:
        _set_ops_status("last_auto_settle_summary", summary)

    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1":
        from services.discord_alerts import send_discord_webhook

        payload = {
            "embeds": [
                {
                    "title": "Auto-settle run complete",
                    "description": f"Graded **{settled}** bet(s).",
                    "fields": [
                        {"name": "Started (UTC)", "value": started, "inline": True},
                        {"name": "Finished (UTC)", "value": finished, "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "settled": settled,
    }


def ops_status(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Protected operator status endpoint.

    Uses CRON_TOKEN auth (via X-Ops-Token) to avoid exposing internals publicly.
    """
    _require_ops_token(x_ops_token, x_cron_token)

    runtime = _runtime_state()
    db_ok, db_error = _check_db_ready()
    scheduler_fresh_ok, scheduler_freshness = _check_scheduler_freshness(runtime["scheduler_expected"])
    ops = getattr(app.state, "ops_status", {})
    from services.odds_api import get_odds_api_activity_snapshot

    odds_api_activity = get_odds_api_activity_snapshot()
    if isinstance(ops, dict):
        ops["odds_api_activity"] = odds_api_activity

    return {
        "timestamp": _utc_now_iso(),
        "runtime": runtime,
        "checks": {
            "db_connectivity": db_ok,
            "scheduler_freshness": scheduler_fresh_ok,
        },
        "db_error": db_error,
        "scheduler_freshness": scheduler_freshness,
        "ops": ops,
    }


async def ops_trigger_test_discord(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Send a test Discord message (no EV/odds filtering).

    Security: requires X-Ops-Token header matching CRON_TOKEN.
    """
    _require_ops_token(x_ops_token, x_cron_token)

    run_id = _new_run_id("ops_discord_test")
    started_at = time.monotonic()
    _log_event("ops.trigger.discord_test.started", run_id=run_id)

    from services.discord_alerts import send_discord_webhook

    payload = {
        "embeds": [
            {
                "title": "Webhook test",
                "description": "If you can read this, DISCORD_WEBHOOK_URL is working.",
                "fields": [
                    {"name": "Server time (UTC)", "value": datetime.now(UTC).isoformat() + "Z", "inline": False},
                ],
            }
        ]
    }

    # Keep the explicit test routing in production, but fall back for simple
    # monkeypatched stubs that only accept the payload argument in contract tests.
    try:
        await send_discord_webhook(payload, message_type="test")
    except TypeError as exc:
        if "message_type" not in str(exc):
            raise
        await send_discord_webhook(payload)
    _log_event(
        "ops.trigger.discord_test.completed",
        run_id=run_id,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
    )
    return {"ok": True, "scheduled": True, "run_id": run_id}


async def ops_trigger_test_discord_alert(
    x_ops_token: str | None = None, x_cron_token: str | None = None
) -> dict[str, bool | str]:
    """
    Trigger a test message to the alert webhook (DISCORD_ALERT_WEBHOOK_URL).
    Useful for verifying the dedicated alert webhook is configured and working.
    Security: requires X-Ops-Token header matching CRON_TOKEN.
    """
    _require_ops_token(x_ops_token, x_cron_token)

    run_id = _new_run_id("ops_discord_alert_test")
    started_at = time.monotonic()
    _log_event("ops.trigger.discord_alert_test.started", run_id=run_id)

    from services.discord_alerts import send_discord_webhook

    payload = {
        "embeds": [
            {
                "title": "Alert Webhook Test",
                "description": "If you can read this, DISCORD_ALERT_WEBHOOK_URL is working.",
                "fields": [
                    {"name": "Server time (UTC)", "value": datetime.now(UTC).isoformat() + "Z", "inline": False},
                ],
            }
        ]
    }

    # Awaited directly so any Discord error surfaces in logs/response.
    await send_discord_webhook(payload, message_type="alert")
    _log_event(
        "ops.trigger.discord_alert_test.completed",
        run_id=run_id,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
    )
    return {"ok": True, "scheduled": True, "run_id": run_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
