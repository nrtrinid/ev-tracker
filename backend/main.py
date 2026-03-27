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
    BetResult, PromoType,
    SettingsUpdate, SettingsResponse, SummaryResponse,
    TransactionCreate, TransactionResponse, BalanceResponse,
    ScanResponse, FullScanResponse,
)
from calculations import (
    american_to_decimal, calculate_ev,
    estimate_bonus_retention,
)
from auth import get_current_user
from services.shared_state import allow_fixed_window_rate_limit, is_redis_enabled
from services.scan_cache import persist_latest_full_scan as persist_latest_full_scan_service
from services.settings_response import build_settings_response as build_settings_response_service
from services.bet_crud import (
    DEFAULT_SPORTSBOOKS,
    EV_LOCK_PROMO_TYPES,
    _lock_ev_for_row,
    _retry_supabase,
    build_bet_response,
    build_effective_k,
    compute_k_user,
    get_user_settings,
)

load_dotenv()

app: FastAPI

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(message)s")
logger = logging.getLogger("ev_tracker")

SCHEDULER_STALE_WINDOWS = {
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
    from utils.time_utils import utc_now_iso_z

    payload = {
        "event": event,
        "timestamp": utc_now_iso_z(),
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
    State enum: new | logged_elsewhere | already_logged | better_now
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
    cross_book_matches_by_key: dict[tuple[str, str, str, str], list[dict]] = {}
    for row in pending_res.data or []:
        key = _scanner_match_key_from_bet(row)
        legacy_key = _scanner_legacy_match_key_from_bet(row)
        if not all([key[0], key[1], key[2], key[3], key[4]]):
            continue
        matches_by_key.setdefault(key, []).append(row)
        matches_by_key.setdefault(legacy_key, []).append(row)
        cross_book_matches_by_key.setdefault(key[:4], []).append(row)
        cross_book_matches_by_key.setdefault(legacy_key[:4], []).append(row)

    annotated: list[dict] = []
    for side in sides:
        side_out = dict(side)
        key = _scanner_match_key_from_side(side)
        legacy_key = _scanner_legacy_match_key_from_side(side)
        matched = matches_by_key.get(key, [])
        if not matched:
            matched = matches_by_key.get(legacy_key, [])
        cross_book_matched = cross_book_matches_by_key.get(key[:4], [])
        if not cross_book_matched:
            cross_book_matched = cross_book_matches_by_key.get(legacy_key[:4], [])
        current_odds = side.get("book_odds")
        current_quality = _price_quality_from_american(current_odds)
        side_out["current_odds_american"] = current_odds

        if not matched:
            if cross_book_matched:
                best_row = None
                best_quality = None
                for row in cross_book_matched:
                    q = _price_quality_from_american(row.get("odds_american"))
                    if q is None:
                        continue
                    if best_quality is None or q > best_quality:
                        best_quality = q
                        best_row = row

                side_out["scanner_duplicate_state"] = "logged_elsewhere"
                side_out["best_logged_odds_american"] = best_row.get("odds_american") if best_row else None
                side_out["matched_pending_bet_id"] = (
                    best_row.get("id") if best_row is not None else cross_book_matched[0].get("id")
                )
                annotated.append(side_out)
                continue
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


def _capture_research_opportunities(sides: list[dict], *, source: str) -> None:
    """Persist fresh scanner sides into the internal research ledger."""
    if not sides:
        return

    from services.research_opportunities import capture_scan_opportunities

    try:
        capture_scan_opportunities(
            get_db(),
            sides=sides,
            source=source,
            captured_at=_utc_now_iso(),
        )
    except Exception as e:
        _log_event(
            "research.capture.failed",
            level="warning",
            source=source,
            error_class=type(e).__name__,
            error=str(e),
        )


async def _apply_fresh_straight_scan_followups(result: dict, *, source: str) -> None:
    """Run research capture + CLV piggyback for fresh scan payloads."""
    sides = result.get("sides") or []
    if not sides or result.get("cache_hit"):
        return
    _capture_research_opportunities(sides, source=source)
    await _piggyback_clv(sides)


def _get_environment() -> str:
    return os.getenv("ENVIRONMENT", "production").lower()


def _scanner_supported_sports(surface: str) -> list[str]:
    if surface == "player_props":
        return ["basketball_nba"]
    from services.odds_api import SUPPORTED_SPORTS

    return SUPPORTED_SPORTS


def _append_scan_activity(**kwargs) -> None:
    from services.odds_api import append_scan_activity

    append_scan_activity(**kwargs)


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
    diagnostics: dict | None = None,
    prizepicks_cards: list[dict] | None = None,
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
        diagnostics=diagnostics,
        prizepicks_cards=prizepicks_cards,
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
    from services.ops_history import build_empty_ops_status

    app.state.ops_status = build_empty_ops_status()


def _set_ops_status(key: str, value: dict) -> None:
    state = getattr(app.state, "ops_status", None)
    if not isinstance(state, dict):
        _init_ops_status()
        state = app.state.ops_status
    state[key] = value


def _persist_ops_job_run(**kwargs) -> None:
    from services.ops_history import persist_ops_job_run

    try:
        db = get_db()
    except Exception as exc:
        _log_event(
            "ops_history.get_db_failed",
            level="warning",
            error_class=type(exc).__name__,
            error=str(exc),
        )
        db = None

    persist_ops_job_run(
        db=db,
        retry_supabase=_retry_supabase,
        log_event=_log_event,
        **kwargs,
    )


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


# In-process lock to prevent overlapping daily-board runs (scheduler + cron/ops triggers).
_DAILY_BOARD_RUN_LOCK = asyncio.Lock()


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
                                {"name": "Time (UTC)", "value": _utc_now_iso(), "inline": True},
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
    started = _utc_now_iso()
    started_at = time.monotonic()
    _record_scheduler_heartbeat("auto_settler", run_id, "started")
    _log_event("scheduler.auto_settler.started", run_id=run_id)
    db = get_db()
    try:
        settled = await run_auto_settler(db, source="auto_settle_scheduler")
        finished = _utc_now_iso()
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
                "started_at": started,
                "finished_at": finished,
                "settled": settled,
                "duration_ms": round((time.monotonic() - started_at) * 1000, 2),
                "captured_at": finished,
            },
        )
        summary = get_last_auto_settler_summary()
        if summary:
            _set_ops_status("last_auto_settle_summary", summary)
        _auto_meta = None
        if isinstance(summary, dict):
            _auto_meta = {}
            if isinstance(summary.get("sports"), list):
                _auto_meta["sports"] = summary["sports"]
            if isinstance(summary.get("prop_settle_telemetry"), dict):
                _auto_meta["prop_settle_telemetry"] = summary["prop_settle_telemetry"]
            if not _auto_meta:
                _auto_meta = None
        _persist_ops_job_run(
            job_kind="auto_settle",
            source="scheduler",
            status="completed",
            run_id=run_id,
            captured_at=finished,
            started_at=started,
            finished_at=finished,
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            settled=settled,
            skipped_totals=summary.get("skipped_totals") if isinstance(summary, dict) else None,
            meta=_auto_meta,
        )
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
    Daily board drop job (mobile-first board):
    - Broad NBA totals fetch for selection + context
    - Full-slate NBA props scan across 5 flagship markets
    - Persist board:latest snapshot with game_context
    """
    from services.daily_board import run_daily_board_drop

    run_id = _new_run_id("scheduled_scan")
    started = _utc_now_iso()
    started_at = time.monotonic()
    _record_scheduler_heartbeat("scheduled_scan", run_id, "started")
    _log_event("scheduler.daily_board.started", run_id=run_id, started_at=started)

    hard_errors = 0
    result: dict | None = None
    try:
        async with _DAILY_BOARD_RUN_LOCK:
            result = await run_daily_board_drop(
                db=get_db(),
                source="scheduled_board_drop",
                scan_label="Late-Afternoon / Final-Context Scan",
                mst_anchor_time="15:30",
                retry_supabase=_retry_supabase,
                log_event=_log_event,
            )
    except Exception as e:
        _log_event(
            "scheduler.daily_board.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
        )
        hard_errors = 1

    finished = _utc_now_iso()
    _log_event(
        "scheduler.daily_board.completed",
        run_id=run_id,
        finished_at=finished,
        result=result,
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
            "scan_window": {
                "label": "Late-Afternoon / Final-Context Scan",
                "anchor_timezone": "America/Phoenix",
                "anchor_time_mst": "15:30",
            },
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "total_sides": (result or {}).get("props_sides") if isinstance(result, dict) else None,
            "props_events_scanned": (result or {}).get("props_events_scanned") if isinstance(result, dict) else None,
            "featured_games_count": (result or {}).get("featured_games_count") if isinstance(result, dict) else None,
            "alerts_scheduled": 0,
            "hard_errors": hard_errors,
            "captured_at": finished,
            "board_drop": True,
            "result": result,
        },
    )
    _persist_ops_job_run(
        job_kind="scheduled_scan",
        source="scheduler",
        status="completed" if hard_errors == 0 else "completed_with_errors",
        run_id=run_id,
        scan_session_id=run_id,
        surface="board",
        scan_scope="daily_board",
        requested_sport="basketball_nba",
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        events_fetched=None,
        events_with_both_books=None,
        total_sides=(result or {}).get("props_sides") if isinstance(result, dict) else None,
        alerts_scheduled=0,
        hard_errors=hard_errors,
        api_requests_remaining=None,
        meta={
            "board_drop": True,
            "props_events_scanned": (result or {}).get("props_events_scanned") if isinstance(result, dict) else None,
            "featured_games_count": (result or {}).get("featured_games_count") if isinstance(result, dict) else None,
            "result": result,
        },
    )

    # Optional heartbeat so we can confirm the daily board ran.
    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1" and hard_errors == 0:
        from services.discord_alerts import send_discord_webhook

        total_sides = (result or {}).get("props_sides") if isinstance(result, dict) else None
        payload = {
            "embeds": [
                {
                    "title": "Daily board drop complete",
                    "description": "Late-Afternoon / Final-Context Scan ran successfully.",
                    "fields": [
                        {"name": "Started (UTC)", "value": started, "inline": True},
                        {"name": "Finished (UTC)", "value": finished, "inline": True},
                        {"name": "Props sides", "value": str(total_sides), "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))


async def _run_early_look_scan_job():
    """Early-Look board scan: pre-main-drop injury/context pulse."""
    from services.daily_board import run_daily_board_drop

    run_id = _new_run_id("scheduled_scan_early")
    started = _utc_now_iso()
    started_at = time.monotonic()
    _record_scheduler_heartbeat("scheduled_scan", run_id, "started")
    _log_event("scheduler.daily_board.early_look.started", run_id=run_id, started_at=started)

    hard_errors = 0
    result: dict | None = None
    try:
        async with _DAILY_BOARD_RUN_LOCK:
            result = await run_daily_board_drop(
                db=get_db(),
                source="scheduled_board_drop_early_look",
                scan_label="Early-Look / Injury-Watch Scan",
                mst_anchor_time="10:30",
                retry_supabase=_retry_supabase,
                log_event=_log_event,
            )
    except Exception as e:
        _log_event(
            "scheduler.daily_board.early_look.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
        )
        hard_errors = 1

    finished = _utc_now_iso()
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    _log_event(
        "scheduler.daily_board.early_look.completed",
        run_id=run_id,
        finished_at=finished,
        result=result,
        duration_ms=duration_ms,
    )
    if hard_errors:
        _record_scheduler_heartbeat(
            "scheduled_scan",
            run_id,
            "failure",
            duration_ms=duration_ms,
            error=f"{hard_errors} run failed",
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
            "scan_window": {
                "label": "Early-Look / Injury-Watch Scan",
                "anchor_timezone": "America/Phoenix",
                "anchor_time_mst": "10:30",
            },
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "total_sides": (result or {}).get("props_sides") if isinstance(result, dict) else None,
            "props_events_scanned": (result or {}).get("props_events_scanned") if isinstance(result, dict) else None,
            "featured_games_count": (result or {}).get("featured_games_count") if isinstance(result, dict) else None,
            "alerts_scheduled": 0,
            "hard_errors": hard_errors,
            "captured_at": finished,
            "board_drop": True,
            "result": result,
        },
    )
    _persist_ops_job_run(
        job_kind="scheduled_scan",
        source="scheduler",
        status="completed" if hard_errors == 0 else "completed_with_errors",
        run_id=run_id,
        scan_session_id=run_id,
        surface="board",
        scan_scope="daily_board",
        requested_sport="basketball_nba",
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        events_fetched=None,
        events_with_both_books=None,
        total_sides=(result or {}).get("props_sides") if isinstance(result, dict) else None,
        alerts_scheduled=0,
        hard_errors=hard_errors,
        api_requests_remaining=None,
        meta={
            "board_drop": True,
            "scan_window": {
                "label": "Early-Look / Injury-Watch Scan",
                "anchor_timezone": "America/Phoenix",
                "anchor_time_mst": "10:30",
            },
            "result": result,
        },
    )


async def _piggyback_clv(sides: list[dict]):
    """
    Fire-and-forget task: update CLV reference snapshots for pending bets and
    open research opportunities from the just-completed fresh scan. Errors are
    swallowed so they never affect the scan response the user sees.
    """
    from services.clv_tracking import (
        update_bet_reference_snapshots,
        update_scan_opportunity_reference_snapshots,
    )
    try:
        db = get_db()
        update_bet_reference_snapshots(db, sides=sides, allow_close=True)
        update_scan_opportunity_reference_snapshots(db, sides=sides, allow_close=True)
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
        scheduler.add_job(
            _run_early_look_scan_job,
            CronTrigger(hour=10, minute=30, timezone=PHOENIX_TZ),
        )
        scheduler.add_job(
            _run_scheduled_scan_job,
            CronTrigger(hour=15, minute=30, timezone=PHOENIX_TZ),
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
        try:
            from services.http_client import close_async_client

            await close_async_client()
        except Exception:
            pass
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


# Lightweight request timing + memory watermark logs for high-risk endpoints.
_TELEMETRY_PATHS = {
    "/balances",
    "/api/board/latest",
    "/api/ops/status",
    "/ready",
}


@app.middleware("http")
async def _timing_middleware(request, call_next):
    import time as _time

    from utils.telemetry import rss_mb as _rss_mb

    path = request.url.path
    should_log = path in _TELEMETRY_PATHS
    started = _time.monotonic()
    rss_before = _rss_mb() if should_log else None
    try:
        response = await call_next(request)
    except Exception as exc:
        if should_log:
            _log_event(
                "http.request.failed",
                level="warning",
                method=request.method,
                path=path,
                duration_ms=round((_time.monotonic() - started) * 1000, 2),
                rss_mb_before=rss_before,
                rss_mb_after=_rss_mb(),
                error_class=type(exc).__name__,
                error=str(exc),
            )
        raise

    if should_log:
        _log_event(
            "http.request.completed",
            method=request.method,
            path=path,
            status_code=getattr(response, "status_code", None),
            duration_ms=round((_time.monotonic() - started) * 1000, 2),
            rss_mb_before=rss_before,
            rss_mb_after=_rss_mb(),
        )
    return response

# Import database after app setup to avoid circular imports
from database import get_db

# Route modules (APIRouter)
from routes.scan_routes import router as scan_router
from routes.ops_cron import router as ops_router
from routes.settings_routes import router as settings_router
from routes.transactions_routes import router as transactions_router
from routes.parlay_routes import router as parlay_router
from routes.utility_routes import router as utility_router
from routes.admin_routes import router as admin_router
from routes.bet_routes import router as bet_router
from routes.board_routes import router as board_router

app.include_router(scan_router)
app.include_router(ops_router)
app.include_router(settings_router)
app.include_router(transactions_router)
app.include_router(parlay_router)
app.include_router(utility_router)
app.include_router(admin_router)
app.include_router(bet_router)
app.include_router(board_router, prefix="/api")

# ---- Re-export selected route handlers for tests ----
# Some unit/integration tests import these callables from the main module.
from routes.scan_routes import scan_markets, scan_latest  # noqa: E402
from routes.ops_cron import ops_status_impl as _ops_status_impl  # noqa: E402


def ops_status(x_cron_token: str | None = None):
    """Test-friendly wrapper around the ops status implementation."""
    from services.research_opportunities import get_research_opportunities_summary  # noqa: F401

    return _ops_status_impl(
        x_cron_token=x_cron_token,
        require_valid_cron_token=lambda token: _require_ops_token(token, None),
        runtime_state=_runtime_state,
        check_db_ready=_check_db_ready,
        check_scheduler_freshness=_check_scheduler_freshness,
        utc_now_iso=_utc_now_iso,
        get_db=get_db,
        retry_supabase=_retry_supabase,
        log_event=_log_event,
        get_ops_status=lambda: getattr(app.state, "ops_status", {}),
    )

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
        _persist_ops_job_run(
            job_kind="readiness_failure",
            source="readiness",
            status="failed",
            captured_at=_utc_now_iso(),
            checks=checks,
            meta={"db_error": db_error, "runtime": runtime},
        )

    response = {
        "status": "ready" if ready else "not_ready",
        "timestamp": _utc_now_iso(),
        "checks": checks,
        "runtime": runtime,
        "scheduler_freshness": scheduler_freshness,
    }
    if db_error:
        response["db_error"] = db_error

    if ready:
        return response

    raise HTTPException(status_code=503, detail=response)




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
    # k_factor no longer needed for balances (profit uses stored bet fields)
    _k_factor = settings["k_factor"]

    # Get all transactions for this user
    tx_result = _retry_supabase(lambda: (
        db.table("transactions")
        .select("sportsbook,type,amount")
        .eq("user_id", user["id"])
        .execute()
    ))
    transactions = tx_result.data or []

    # Get all bets for profit calculation
    bets_result = _retry_supabase(lambda: (
        db.table("bets")
        .select("sportsbook,result,promo_type,stake,odds_american,boost_percent,winnings_cap,payout_override,win_payout_locked,true_prob_at_entry")
        .eq("user_id", user["id"])
        .execute()
    ))
    bets = bets_result.data or []

    from services.balance_stats import compute_balances_by_sportsbook_fast

    out = compute_balances_by_sportsbook_fast(transactions=transactions, bets=bets)
    return [BalanceResponse(**row) for row in out]


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
    if settings.kelly_multiplier is not None:
        data["kelly_multiplier"] = settings.kelly_multiplier
    if settings.bankroll_override is not None:
        data["bankroll_override"] = settings.bankroll_override
    if settings.use_computed_bankroll is not None:
        data["use_computed_bankroll"] = settings.use_computed_bankroll
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
