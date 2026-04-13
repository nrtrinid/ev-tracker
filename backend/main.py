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
from typing import Any
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
DISCORD_SCAN_ALERT_MODE_ENV = "DISCORD_SCAN_ALERT_MODE"
DISCORD_SCAN_ALERT_MODE_TIMED_PING = "timed_ping"
DISCORD_SCAN_ALERT_MODE_EDGE_LIVE = "edge_live"
SCHEDULED_SCAN_WINDOWS_MST: list[tuple[int, int, str]] = [
    (10, 30, "Early-Look / Injury-Watch Scan"),
    (15, 30, "Final Board / Bet Placement Scan"),
]


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


def _scan_alert_mode_raw() -> str:
    return (os.getenv(DISCORD_SCAN_ALERT_MODE_ENV) or DISCORD_SCAN_ALERT_MODE_TIMED_PING).strip().lower()


def _scan_alert_mode() -> str:
    raw = _scan_alert_mode_raw()
    if raw in {DISCORD_SCAN_ALERT_MODE_TIMED_PING, DISCORD_SCAN_ALERT_MODE_EDGE_LIVE}:
        return raw
    return DISCORD_SCAN_ALERT_MODE_TIMED_PING


def _scheduled_scan_window(now: datetime | None = None) -> dict[str, str]:
    current = now or datetime.now(UTC)
    local_now = current.astimezone(PHOENIX_TZ) if PHOENIX_TZ is not None else current
    minute_of_day = (local_now.hour * 60) + local_now.minute

    hour, minute, label = min(
        SCHEDULED_SCAN_WINDOWS_MST,
        key=lambda window: abs(minute_of_day - ((window[0] * 60) + window[1])),
    )
    return {
        "label": label,
        "anchor_timezone": "America/Phoenix",
        "anchor_time_mst": f"{hour:02d}:{minute:02d}",
    }


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
    temp_scan_time_raw = os.getenv(SCHEDULED_SCAN_TEMP_TIME_ENV)
    heartbeat_enabled = os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1"
    scan_alert_mode_raw = _scan_alert_mode_raw()
    scan_alert_mode = _scan_alert_mode()
    discord_alert_target = {
        "webhook_configured": False,
        "route_kind": "alert_unconfigured",
    }
    discord_test_target = {
        "webhook_configured": False,
        "route_kind": "test_unconfigured",
    }

    try:
        from services.discord_alerts import describe_discord_delivery_target

        discord_alert_target = describe_discord_delivery_target("alert")
        discord_test_target = describe_discord_delivery_target("test")
    except Exception:
        pass

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

    if scheduler_enabled and not bool(discord_alert_target.get("webhook_configured")):
        _log_event(
            "startup.env_discord_alert_webhook_missing",
            level="warning",
            route_kind=discord_alert_target.get("route_kind"),
            message="ENABLE_SCHEDULER=1 but no alert Discord webhook is configured; alert delivery is disabled.",
        )

    if (
        scheduler_enabled
        and bool(discord_alert_target.get("webhook_configured"))
        and discord_alert_target.get("route_kind") == "alert_primary_fallback"
    ):
        _log_event(
            "startup.env_discord_alert_webhook_fallback",
            level="warning",
            route_kind=discord_alert_target.get("route_kind"),
            message="DISCORD_ALERT_WEBHOOK_URL not set; alerts will use DISCORD_WEBHOOK_URL fallback.",
        )

    if heartbeat_enabled and not bool(discord_test_target.get("webhook_configured")):
        _log_event(
            "startup.env_discord_debug_webhook_missing",
            level="warning",
            route_kind=discord_test_target.get("route_kind"),
            message="DISCORD_AUTO_SETTLE_HEARTBEAT=1 but no debug/test Discord webhook is configured.",
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

    if scan_alert_mode_raw != scan_alert_mode:
        _log_event(
            "startup.env_scan_alert_mode_invalid",
            level="warning",
            env_var=DISCORD_SCAN_ALERT_MODE_ENV,
            provided_value=scan_alert_mode_raw,
            defaulted_to=scan_alert_mode,
            message="Unsupported scan alert mode; defaulting to timed_ping.",
        )

    _log_event(
        "startup.env_validated",
        environment=environment,
        scheduler_enabled=scheduler_enabled,
        cron_token_configured=cron_token_configured,
        odds_api_key_configured=odds_api_configured,
        discord_alert_webhook_configured=bool(discord_alert_target.get("webhook_configured")),
        discord_alert_route_kind=discord_alert_target.get("route_kind"),
        discord_test_webhook_configured=bool(discord_test_target.get("webhook_configured")),
        discord_test_route_kind=discord_test_target.get("route_kind"),
        discord_heartbeat_enabled=heartbeat_enabled,
        discord_scan_alert_mode=scan_alert_mode,
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


def _sync_pickem_research_from_props_payload(payload: dict | None, *, source: str = "unknown") -> None:
    """Best-effort sync of pick'em research observations from player-prop payloads."""
    if not isinstance(payload, dict):
        return
    try:
        from services.pickem_research import capture_pickem_research_observations

        capture_pickem_research_observations(
            get_db(),
            payload,
            source=source,
            captured_at=_utc_now_iso(),
        )
    except Exception:
        # Pick'em sync should never block scan responses.
        return


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

    app_role = (os.getenv("APP_ROLE") or "").strip().lower()
    if app_role == "api":
        try:
            from services.ops_history import load_scheduler_job_snapshot

            db = get_db()
            snapshot = load_scheduler_job_snapshot(
                db=db,
                retry_supabase=_retry_supabase,
                log_event=_log_event,
            )
            now = datetime.now(UTC)

            def _fresh_from(snapshot_key: str, stale_window: timedelta) -> tuple[bool, str | None, str]:
                entry = snapshot.get(snapshot_key) if isinstance(snapshot, dict) else None
                captured_at = _parse_utc_iso(entry.get("captured_at") if isinstance(entry, dict) else None)
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
                if not fresh:
                    all_fresh = False
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
    heartbeat_enabled = os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1"

    discord_runtime: dict[str, Any] = {
        "heartbeat_enabled": heartbeat_enabled,
        "scan_alert_mode": _scan_alert_mode(),
        "alert_delivery": {
            "message_type": "alert",
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

        discord_runtime["alert_delivery"] = describe_discord_delivery_target("alert")
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
    started = datetime.now(UTC).isoformat() + "Z"
    started_at = time.monotonic()
    _record_scheduler_heartbeat("auto_settler", run_id, "started")
    _log_event("scheduler.auto_settler.started", run_id=run_id)
    db = get_db()
    try:
        settled = await run_auto_settler(db, source="auto_settle_scheduler")
        finished = datetime.now(UTC).isoformat() + "Z"
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
        summary_meta = None
        if isinstance(summary, dict):
            summary_meta = {}
            if isinstance(summary.get("sports"), list):
                summary_meta["sports"] = summary.get("sports")
            for key in ("ml_settled", "props_settled", "parlays_settled", "pickem_research_settled"):
                if summary.get(key) is not None:
                    summary_meta[key] = summary.get(key)
            if not summary_meta:
                summary_meta = None
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
            meta=summary_meta,
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


async def _run_scheduled_board_drop_job():
    """Run the trusted-beta board pipeline for the scheduled 10:30 and 3:30 windows."""
    from services.daily_board import run_daily_board_drop
    from services.discord_alerts import (
        DiscordDeliveryError,
        build_board_drop_alert_payload,
        get_last_schedule_stats,
        schedule_alerts,
        send_discord_webhook,
    )

    run_id = _new_run_id("scheduled_board_drop")
    started = datetime.now(UTC).isoformat()
    started_at = time.monotonic()
    scan_window = _scheduled_scan_window()
    scan_alert_mode = _scan_alert_mode()
    _record_scheduler_heartbeat("scheduled_scan", run_id, "started")
    _log_event(
        "scheduler.board_drop.started",
        run_id=run_id,
        started_at=started + "Z",
        scan_window=scan_window,
        scan_alert_mode=scan_alert_mode,
    )

    alerts_scheduled = 0
    hard_errors = 0
    fresh_straight_sides: list[dict] = []
    fresh_prop_sides: list[dict] = []
    alert_skip_totals = {
        "skipped_memory_dedupe": 0,
        "skipped_shared_dedupe": 0,
        "skipped_threshold": 0,
    }
    board_alert = {
        "attempted": False,
        "delivery_status": "not_attempted",
        "status_code": None,
        "route_kind": None,
        "webhook_source": None,
        "error": None,
    }
    result: dict[str, Any] = {
        "straight_sides": 0,
        "props_sides": 0,
        "featured_games_count": 0,
        "game_line_sports_scanned": [],
        "game_lines_events_fetched": 0,
        "game_lines_events_with_both_books": 0,
        "game_lines_api_requests_remaining": None,
        "props_events_fetched": 0,
        "props_events_with_both_books": 0,
        "props_api_requests_remaining": None,
        "props_events_scanned": 0,
    }

    try:
        result = await run_daily_board_drop(
            db=get_db(),
            source="scheduled_board_drop",
            scan_label=scan_window["label"],
            mst_anchor_time=scan_window["anchor_time_mst"],
            retry_supabase=_retry_supabase,
            log_event=_log_event,
        )
        fresh_straight_sides = [
            side for side in (result.get("fresh_straight_sides") or []) if isinstance(side, dict)
        ]
        fresh_prop_sides = [
            side for side in (result.get("fresh_prop_sides") or []) if isinstance(side, dict)
        ]

        candidates_seen = len(fresh_straight_sides) + len(fresh_prop_sides)
        if scan_alert_mode == DISCORD_SCAN_ALERT_MODE_EDGE_LIVE:
            alerts_scheduled += schedule_alerts([*fresh_straight_sides, *fresh_prop_sides])
            schedule_stats = get_last_schedule_stats()
            alert_skip_totals["skipped_memory_dedupe"] += int(schedule_stats.get("skipped_memory_dedupe") or 0)
            alert_skip_totals["skipped_shared_dedupe"] += int(schedule_stats.get("skipped_shared_dedupe") or 0)
            alert_skip_totals["skipped_threshold"] += int(schedule_stats.get("skipped_threshold") or 0)
        else:
            schedule_stats = {
                "mode": scan_alert_mode,
                "candidates_seen": candidates_seen,
                "scheduled": 0,
                "skipped_memory_dedupe": 0,
                "skipped_shared_dedupe": 0,
                "skipped_threshold": candidates_seen,
                "skipped_total": candidates_seen,
            }

        _log_event(
            "scheduler.board_drop.scan_completed",
            run_id=run_id,
            straight_sides=result.get("straight_sides"),
            props_sides=result.get("props_sides"),
            featured_games_count=result.get("featured_games_count"),
            game_line_sports=result.get("game_line_sports_scanned"),
            props_events_scanned=result.get("props_events_scanned"),
            discord_alert_schedule=schedule_stats,
            scan_alert_mode=scan_alert_mode,
        )
    except Exception as exc:
        hard_errors = 1
        _log_event(
            "scheduler.board_drop.failed",
            level="error",
            run_id=run_id,
            error_class=type(exc).__name__,
            error=str(exc),
        )

    finished = datetime.now(UTC).isoformat()
    autolog_summary = None
    try:
        autolog_summary = await _run_longshot_autolog_for_sides(
            db=get_db(),
            run_id=run_id,
            sides=fresh_straight_sides,
        )
    except Exception as exc:
        autolog_summary = {
            "enabled": _is_paper_experiment_autolog_enabled(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _log_event(
            "scheduler.board_drop.autolog.failed",
            level="error",
            run_id=run_id,
            error_class=type(exc).__name__,
            error=str(exc),
        )

    if scan_alert_mode == DISCORD_SCAN_ALERT_MODE_TIMED_PING:
        if hard_errors == 0:
            board_alert_payload = build_board_drop_alert_payload(
                window_label=scan_window["label"],
                anchor_time_mst=scan_window["anchor_time_mst"],
                result={
                    "props_sides": result.get("props_sides"),
                    "straight_sides": result.get("straight_sides"),
                    "featured_games_count": result.get("featured_games_count"),
                },
            )
            try:
                delivery = await send_discord_webhook(board_alert_payload, message_type="alert")
                board_alert = {
                    "attempted": True,
                    "delivery_status": delivery.get("delivery_status") if isinstance(delivery, dict) else "delivered",
                    "status_code": delivery.get("status_code") if isinstance(delivery, dict) else None,
                    "route_kind": delivery.get("route_kind") if isinstance(delivery, dict) else None,
                    "webhook_source": delivery.get("webhook_source") if isinstance(delivery, dict) else None,
                    "error": None,
                }
            except DiscordDeliveryError as exc:
                board_alert = {
                    "attempted": True,
                    "delivery_status": "failed",
                    "status_code": exc.status_code,
                    "route_kind": exc.route_kind,
                    "webhook_source": exc.webhook_source,
                    "error": str(exc),
                }
            except Exception as exc:
                board_alert = {
                    "attempted": True,
                    "delivery_status": "failed_unexpected",
                    "status_code": None,
                    "route_kind": None,
                    "webhook_source": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        else:
            board_alert = {
                "attempted": False,
                "delivery_status": "skipped_due_to_errors",
                "status_code": None,
                "route_kind": None,
                "webhook_source": None,
                "error": None,
            }
        _log_event(
            "scheduler.board_drop.alert",
            run_id=run_id,
            scan_window=scan_window,
            delivery_status=board_alert.get("delivery_status"),
            status_code=board_alert.get("status_code"),
            route_kind=board_alert.get("route_kind"),
            webhook_source=board_alert.get("webhook_source"),
            error=board_alert.get("error"),
        )

    total_sides = int(result.get("straight_sides") or 0) + int(result.get("props_sides") or 0)
    total_events = int(result.get("game_lines_events_fetched") or 0) + int(result.get("props_events_fetched") or 0)
    total_with_both = int(result.get("game_lines_events_with_both_books") or 0) + int(
        result.get("props_events_with_both_books") or 0
    )
    remaining_candidates: list[int] = []
    remaining_fallback: str | None = None
    for raw in (
        result.get("game_lines_api_requests_remaining"),
        result.get("props_api_requests_remaining"),
    ):
        if raw is None:
            continue
        if remaining_fallback is None:
            remaining_fallback = str(raw)
        try:
            remaining_candidates.append(int(raw))
        except (TypeError, ValueError):
            continue
    min_remaining = str(min(remaining_candidates)) if remaining_candidates else remaining_fallback
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    result_summary = dict(result.get("summary") or {})
    if not result_summary:
        result_summary = {
            "straight_sides": int(result.get("straight_sides") or 0),
            "props_sides": int(result.get("props_sides") or 0),
            "featured_games_count": int(result.get("featured_games_count") or 0),
            "game_line_sports_scanned": result.get("game_line_sports_scanned") or [],
            "props_events_scanned": int(result.get("props_events_scanned") or 0),
        }
    result_summary.setdefault("scan_label", scan_window["label"])
    result_summary.setdefault("anchor_time_mst", scan_window["anchor_time_mst"])
    result_summary["duration_ms"] = duration_ms

    _log_event(
        "scheduler.board_drop.completed",
        run_id=run_id,
        finished_at=finished + "Z",
        straight_sides=result.get("straight_sides"),
        props_sides=result.get("props_sides"),
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        alert_skip_totals=alert_skip_totals,
        autolog_summary=autolog_summary,
        scan_window=scan_window,
        scan_alert_mode=scan_alert_mode,
        board_alert=board_alert,
        duration_ms=duration_ms,
    )
    if hard_errors:
        _record_scheduler_heartbeat(
            "scheduled_scan",
            run_id,
            "failure",
            duration_ms=duration_ms,
            error="scheduled board drop failed",
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
            "board_drop": True,
            "total_sides": total_sides,
            "straight_sides": int(result.get("straight_sides") or 0),
            "props_sides": int(result.get("props_sides") or 0),
            "featured_games_count": int(result.get("featured_games_count") or 0),
            "alerts_scheduled": alerts_scheduled,
            "alert_skip_totals": alert_skip_totals,
            "scan_window": scan_window,
            "scan_alert_mode": scan_alert_mode,
            "board_alert": board_alert,
            "board_alert_attempted": bool(board_alert.get("attempted")),
            "board_alert_delivery_status": board_alert.get("delivery_status"),
            "board_alert_http_status": board_alert.get("status_code"),
            "board_alert_error": board_alert.get("error"),
            "game_line_sports_scanned": result.get("game_line_sports_scanned") or [],
            "props_events_scanned": int(result.get("props_events_scanned") or 0),
            "result": result_summary,
            "hard_errors": hard_errors,
            "captured_at": finished + "Z",
            "autolog_summary": autolog_summary,
        },
    )
    _persist_ops_job_run(
        job_kind="scheduled_board_drop",
        source="scheduler",
        status="completed" if hard_errors == 0 else "completed_with_errors",
        run_id=run_id,
        scan_session_id=run_id,
        surface="board_drop",
        scan_scope="all",
        requested_sport="board",
        captured_at=finished + "Z",
        started_at=started + "Z",
        finished_at=finished + "Z",
        duration_ms=duration_ms,
        events_fetched=total_events,
        events_with_both_books=total_with_both,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        hard_errors=hard_errors,
        api_requests_remaining=min_remaining,
        meta={
            "autolog_summary": autolog_summary,
            "alert_skip_totals": alert_skip_totals,
            "scan_window": scan_window,
            "scan_alert_mode": scan_alert_mode,
            "board_alert": board_alert,
            "board_alert_attempted": bool(board_alert.get("attempted")),
            "board_alert_delivery_status": board_alert.get("delivery_status"),
            "board_alert_http_status": board_alert.get("status_code"),
            "board_alert_error": board_alert.get("error"),
            "result_summary": result_summary,
        },
    )

    if (
        scan_alert_mode == DISCORD_SCAN_ALERT_MODE_EDGE_LIVE
        and os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1"
        and alerts_scheduled == 0
    ):
        payload = {
            "embeds": [
                {
                    "title": "Scheduled board drop complete (no alerts)",
                    "description": "The scheduled board drop ran successfully but found no qualifying lines to alert on.",
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


async def _run_scheduled_scan_job():
    """Legacy compatibility alias for scheduled scan invocations."""
    await _run_scheduled_board_drop_job()


async def _run_early_look_scan_job():
    """Legacy compatibility alias for early-look scan invocations."""
    await _run_scheduled_board_drop_job()


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
    if (os.getenv("APP_ROLE") or "").strip().lower() == "api":
        return  # External scheduler topology: API role should not run in-process jobs.
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    _init_scheduler_heartbeats()
    scheduler = AsyncIOScheduler()
    # Every 5 min: capture closing Pinnacle lines for games starting within 20 min
    scheduler.add_job(_run_jit_clv_snatcher_job, IntervalTrigger(minutes=5))
    # 4:00 AM and 10:00 PM Phoenix daily: auto-grade completed ML bets via /scores.
    # Explicit timezone keeps scheduler behavior consistent across hosts.
    auto_settle_trigger = (
        CronTrigger(hour="4,22", minute=0, timezone=PHOENIX_TZ)
        if PHOENIX_TZ is not None
        else CronTrigger(hour="4,22", minute=0)
    )
    scheduler.add_job(
        _run_auto_settler_job,
        auto_settle_trigger,
        misfire_grace_time=60 * 60,
        coalesce=True,
    )
    if PHOENIX_TZ is not None:
        scheduled_scan_times: list[tuple[int, int]] = [
            (hour, minute) for hour, minute, _label in SCHEDULED_SCAN_WINDOWS_MST
        ]
        temp_scan_time = _parse_hhmm(os.getenv(SCHEDULED_SCAN_TEMP_TIME_ENV))
        if temp_scan_time is not None and temp_scan_time not in scheduled_scan_times:
            scheduled_scan_times.append(temp_scan_time)

        for hour, minute in scheduled_scan_times:
            scheduler.add_job(
                _run_scheduled_board_drop_job,
                CronTrigger(hour=hour, minute=minute, timezone=PHOENIX_TZ),
            )
    else:
        print("[Scheduler] Phoenix timezone unavailable; skipping scheduled board drop jobs.")
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


def _app_role() -> str:
    """Return normalized runtime role used by entrypoint orchestration."""
    role = (os.getenv("APP_ROLE") or "api").strip().lower()
    return "scheduler" if role == "scheduler" else "api"


async def run_scheduler_worker() -> None:
    """
    Standalone scheduler worker entrypoint.

    This path is used by backend/entrypoint.py when APP_ROLE=scheduler, so we
    bootstrap environment validation + scheduler jobs without starting uvicorn.
    """
    _validate_environment()
    _init_ops_status()
    await start_scheduler()

    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await stop_scheduler()


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
from routes.board_routes import router as board_router
from routes.ops_cron import router as ops_router
from routes.settings_routes import router as settings_router
from routes.transactions_routes import router as transactions_router
from routes.parlay_routes import router as parlay_router
from routes.utility_routes import router as utility_router
from routes.admin_routes import router as admin_router
from routes.analytics_routes import router as analytics_router
from routes.beta_access_routes import router as beta_access_router

app.include_router(scan_router)
app.include_router(board_router, prefix="/api")
app.include_router(ops_router)
app.include_router(settings_router)
app.include_router(transactions_router)
app.include_router(parlay_router)
app.include_router(utility_router)
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(beta_access_router)

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
        "kelly_multiplier": 0.25,
        "bankroll_override": 1000.0,
        "use_computed_bankroll": True,
        "k_factor_mode": "baseline",
        "k_factor_min_stake": 300.0,
        "k_factor_smoothing": 700.0,
        "k_factor_clamp_min": 0.50,
        "k_factor_clamp_max": 0.95,
        "beta_access_granted": False,
        "beta_access_granted_at": None,
        "beta_access_method": None,
        "onboarding_state": {
            "version": 2,
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
    created_after = datetime.now(UTC) - timedelta(days=999)
    try:
        res = _retry_supabase(lambda: (
            db.table("bets")
            .select("promo_type,result,created_at,stake,payout_override,win_payout")
            .eq("user_id", user_id)
            .execute()
        ))
        rows = res.data or []
    except Exception:
        return {"k_obs": None, "bonus_stake_settled": 0.0}

    total_stake = 0.0
    total_profit = 0.0
    for row in rows:
        if row.get("promo_type") != "bonus_bet":
            continue
        stake = float(row.get("stake") or 0)
        result = row.get("result")
        if result == "pending":
            continue
        created_at = row.get("created_at")
        if created_at:
            try:
                created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                if created_dt < created_after:
                    continue
            except Exception:
                pass
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
        latest_pinnacle_odds=row.get("latest_pinnacle_odds"),
        latest_pinnacle_updated_at=row.get("latest_pinnacle_updated_at"),
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
def create_bet(
    bet: BetCreate,
    user: dict = Depends(get_current_user),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
):
    """Create a new bet."""
    from services.bet_crud import create_bet_impl

    return create_bet_impl(get_db(), user, bet, session_id=x_session_id)


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
    session_id: str | None = None,
):
    from routes.scan_routes import scan_markets_impl
    from services.scan_markets import apply_manual_scan_bundle, scan_exception_to_http_exception

    return await scan_markets_impl(
        surface=surface,
        sport=sport,
        user=user,
        session_id=session_id,
        get_db=get_db,
        supported_sports=_scanner_supported_sports(surface),
        get_cached_or_scan=lambda sport_key, source="manual_scan": _get_cached_or_scan_for_surface(surface, sport_key, source=source),
        apply_manual_scan_bundle_fn=apply_manual_scan_bundle,
        set_ops_status=_set_ops_status,
        utc_now_iso=_utc_now_iso,
        piggyback_clv=_piggyback_clv,
        capture_research_opportunities=_capture_research_opportunities,
        persist_latest_full_scan=_persist_latest_full_scan,
        retry_supabase=_retry_supabase,
        log_event=_log_event,
        annotate_sides=_annotate_sides_with_duplicate_state,
        append_scan_activity=_append_scan_activity,
        persist_ops_job_run=_persist_ops_job_run,
        new_run_id=_new_run_id,
        sync_pickem_research_from_props_payload=_sync_pickem_research_from_props_payload,
        map_error=scan_exception_to_http_exception,
        build_full_scan_response=_build_full_scan_response,
        get_environment=_get_environment,
    )


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
    alert_skip_totals = {
        "skipped_memory_dedupe": 0,
        "skipped_shared_dedupe": 0,
        "skipped_threshold": 0,
    }
    from services.discord_alerts import get_last_schedule_stats, schedule_alerts

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
            schedule_stats = get_last_schedule_stats()
            alert_skip_totals["skipped_memory_dedupe"] += int(schedule_stats.get("skipped_memory_dedupe") or 0)
            alert_skip_totals["skipped_shared_dedupe"] += int(schedule_stats.get("skipped_shared_dedupe") or 0)
            alert_skip_totals["skipped_threshold"] += int(schedule_stats.get("skipped_threshold") or 0)
            _log_event(
                "ops.trigger.scan.alert_schedule",
                run_id=run_id,
                sport=sport_key,
                discord_alert_schedule=schedule_stats,
            )
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
        alert_skip_totals=alert_skip_totals,
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
            "alert_skip_totals": alert_skip_totals,
            "error_count": len(errors),
            "errors": errors,
            "captured_at": finished,
        },
    )
    _persist_ops_job_run(
        job_kind="ops_trigger_scan",
        source="ops_trigger",
        status="completed" if not errors else "completed_with_errors",
        run_id=run_id,
        scan_session_id=run_id,
        surface="straight_bets",
        scan_scope="all",
        requested_sport="all",
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        error_count=len(errors),
        errors=errors,
        meta={"alert_skip_totals": alert_skip_totals},
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
        "alert_skip_totals": alert_skip_totals,
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
            "captured_at": finished,
        },
    )
    summary = get_last_auto_settler_summary()
    if summary:
        _set_ops_status("last_auto_settle_summary", summary)
    summary_meta = None
    if isinstance(summary, dict):
        summary_meta = {}
        if isinstance(summary.get("sports"), list):
            summary_meta["sports"] = summary.get("sports")
        for key in ("ml_settled", "props_settled", "parlays_settled", "pickem_research_settled"):
            if summary.get(key) is not None:
                summary_meta[key] = summary.get(key)
        if not summary_meta:
            summary_meta = None
    _persist_ops_job_run(
        job_kind="auto_settle",
        source="ops_trigger",
        status="completed",
        run_id=run_id,
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        settled=settled,
        skipped_totals=summary.get("skipped_totals") if isinstance(summary, dict) else None,
        meta=summary_meta,
    )

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
    from services.odds_api import get_odds_api_activity_snapshot
    from services.ops_history import load_ops_status_snapshot

    try:
        db = get_db()
    except Exception:
        db = None
    ops = load_ops_status_snapshot(
        db=db,
        retry_supabase=_retry_supabase,
        log_event=_log_event,
        fallback_ops_status=getattr(app.state, "ops_status", {}),
        fallback_odds_api_activity=get_odds_api_activity_snapshot(),
    )

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
