"""Bet CRUD business logic and shared helpers.

Extracted from main.py to reduce monolith size.
"""

import json
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException

from services.analytics_events import capture_backend_event
from calculations import (
    american_to_decimal,
    calculate_clv,
    calculate_ev,
    calculate_real_profit,
    compute_blend_weight,
)
from models import BetCreate, BetResult, BetResponse, BetUpdate
from utils.request_context import (
    get_correlation_id,
    get_request_id,
    record_db_roundtrip,
)

logger = logging.getLogger("ev_tracker")

# ── Shared utilities ─────────────────────────────────────────────────────────

DEFAULT_SPORTSBOOKS = [
    "DraftKings", "FanDuel", "BetMGM", "Caesars",
    "ESPN Bet", "Fanatics", "Hard Rock", "bet365"
]


def _log_structured_event(event: str, *, level: str = "info", **fields) -> None:
    payload = {
        "event": event,
        "request_id": get_request_id(),
        "correlation_id": get_correlation_id(),
        **fields,
    }
    getattr(logger, level.lower(), logger.info)(json.dumps(payload, default=str))


def _retry_supabase(f, retries: int = 2, *, label: str = "supabase.request", slow_ms: float = 250.0):
    """Retry a Supabase/PostgREST request on transient transport errors."""
    last_err = None
    for attempt in range(retries):
        started_at = time.monotonic()
        try:
            result = f()
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            record_db_roundtrip(duration_ms)
            if attempt > 0 or duration_ms >= slow_ms:
                _log_structured_event(
                    "supabase.request.completed",
                    label=label,
                    duration_ms=duration_ms,
                    attempt=attempt + 1,
                    retries=retries,
                )
            return result
        except (
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.ConnectError,
            httpx.PoolTimeout,
            httpx.TimeoutException,
        ) as e:
            last_err = e
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            record_db_roundtrip(duration_ms)
            if attempt == retries - 1:
                _log_structured_event(
                    "supabase.request.failed",
                    level="warning",
                    label=label,
                    duration_ms=duration_ms,
                    attempt=attempt + 1,
                    retries=retries,
                    error_class=type(e).__name__,
                    error=str(e),
                )
                raise
            delay_seconds = min(0.35, 0.1 * (2**attempt))
            _log_structured_event(
                "supabase.request.retrying",
                level="warning",
                label=label,
                duration_ms=duration_ms,
                attempt=attempt + 1,
                retries=retries,
                retry_delay_ms=round(delay_seconds * 1000, 2),
                error_class=type(e).__name__,
                error=str(e),
            )
            time.sleep(delay_seconds)
    if last_err:
        raise last_err


def get_user_settings(db, user_id: str) -> dict:
    """Get settings from DB, creating defaults for new users."""
    result = _retry_supabase(
        lambda: db.table("settings").select("*").eq("user_id", user_id).execute(),
        label="settings.select",
    )
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
    _retry_supabase(
        lambda: db.table("settings").upsert(defaults).execute(),
        label="settings.upsert_defaults",
    )
    result = _retry_supabase(
        lambda: db.table("settings").select("*").eq("user_id", user_id).execute(),
        label="settings.select_after_upsert",
    )
    return result.data[0]


def compute_k_user(db, user_id: str) -> dict:
    """
    Compute observed bonus retention from settled bonus bets.
    Returns k_obs (None if no data), bonus_stake_settled.
    """
    created_after = datetime.now(UTC) - timedelta(days=999)
    try:
        res = _retry_supabase(
            lambda: (
                db.table("bets")
                .select("promo_type,result,created_at,stake,payout_override,win_payout")
                .eq("user_id", user_id)
                .execute()
            ),
            label="bets.select_bonus_history",
        )
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
            total_profit += win_payout

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


# ── EV lock ──────────────────────────────────────────────────────────────────

EV_LOCK_PROMO_TYPES: frozenset[str] = frozenset({
    "bonus_bet", "no_sweat", "promo_qualifier",
    "boost_30", "boost_50", "boost_100", "boost_custom",
})


def _lock_ev_for_row(db, bet_id: str, user_id: str, row: dict, settings: dict) -> dict:
    """
    Compute EV once using the current effective k and write locked fields to DB.
    Only runs for promo types where k has a meaningful effect.
    Does NOT update bets that already have a valid lock (ev_locked_at is set).
    """
    if row.get("ev_locked_at") is not None:
        return row
    if row.get("promo_type") not in EV_LOCK_PROMO_TYPES:
        return row

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
    locked_updates = {
        "ev_per_dollar_locked": ev_result["ev_per_dollar"],
        "ev_total_locked": ev_result["ev_total"],
        "win_payout_locked": win_payout,
        "ev_locked_at": datetime.now(UTC).isoformat(),
    }

    try:
        _retry_supabase(
            lambda: (
                db.table("bets")
                .update(locked_updates)
                .eq("id", bet_id)
                .eq("user_id", user_id)
                .execute()
            ),
            label="bets.update_ev_lock",
        )
    except Exception as e:
        logger.warning("ev_lock.write_failed bet_id=%s err=%s", bet_id, e)
        return row

    row.update(locked_updates)
    return row


# ── Bet response builder ──────────────────────────────────────────────────────

def build_bet_response(row: dict, k_factor: float) -> BetResponse:
    """Convert database row to BetResponse with calculated fields."""
    from calculations import calculate_hold_from_odds

    decimal_odds = american_to_decimal(row["odds_american"])
    decimal_odds_for_ev = decimal_odds

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

    win_payout = payout_override or ev_result["win_payout"]

    real_profit = calculate_real_profit(
        stake=row["stake"],
        win_payout=win_payout,
        result=row["result"],
        promo_type=row["promo_type"],
    )

    clv_ev_percent = None
    beat_close = None
    if row.get("pinnacle_odds_at_entry") and row.get("pinnacle_odds_at_close"):
        clv_result = calculate_clv(row["odds_american"], row["pinnacle_odds_at_close"])
        clv_ev_percent = clv_result["clv_ev_percent"]
        beat_close = clv_result["beat_close"]

    ev_per_dollar_out = (
        row.get("ev_per_dollar_locked")
        if row.get("ev_per_dollar_locked") is not None
        else ev_result["ev_per_dollar"]
    )
    ev_total_out = (
        row.get("ev_total_locked")
        if row.get("ev_total_locked") is not None
        else ev_result["ev_total"]
    )
    win_payout_out = (
        row.get("win_payout_locked")
        if row.get("win_payout_locked") is not None
        else win_payout
    )

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
        payout_override=row.get("payout_override"),
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


# ── Bet CRUD implementations ──────────────────────────────────────────────────

def create_bet_impl(db, user: dict, bet: BetCreate, session_id: str | None = None) -> BetResponse:
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

    if bet.event_date:
        data["event_date"] = bet.event_date.isoformat()

    started_at = time.monotonic()
    result = _retry_supabase(
        lambda: db.table("bets").insert(data).execute(),
        label="bets.insert",
    )

    if not result.data:
        capture_backend_event(
            db,
            event_name="bet_log_failed",
            user_id=str(user.get("id") or ""),
            session_id=session_id,
            properties={
                "route": "/bets",
                "app_area": "tracker",
                "failure_stage": "insert_empty",
            },
            dedupe_key=f"bet-log-failed:{user.get('id')}:{get_request_id()}",
        )
        raise HTTPException(status_code=500, detail="Failed to create bet")

    row = result.data[0]
    row = _lock_ev_for_row(db, row["id"], user["id"], row, settings)
    _log_structured_event(
        "bets.create.completed",
        user_id=str(user.get("id") or ""),
        bet_id=row.get("id"),
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        sportsbook=row.get("sportsbook"),
        sport=row.get("sport"),
    )
    capture_backend_event(
        db,
        event_name="bet_logged",
        user_id=str(user.get("id") or ""),
        session_id=session_id,
        properties={
            "route": "/bets",
            "app_area": "tracker",
            "sport": row.get("sport"),
            "market": row.get("market"),
            "sportsbook": row.get("sportsbook"),
        },
        dedupe_key=f"bet-logged:{row.get('id')}",
    )
    return build_bet_response(row, settings["k_factor"])


def get_bets_impl(
    db,
    user: dict,
    sport: str | None,
    sportsbook: str | None,
    result: BetResult | None,
    limit: int,
    offset: int,
) -> list[BetResponse]:
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
    response = _retry_supabase(lambda: query.execute(), label="bets.select_list")
    return [build_bet_response(row, settings["k_factor"]) for row in response.data]


def get_bet_impl(db, user: dict, bet_id: str) -> BetResponse:
    settings = get_user_settings(db, user["id"])

    result = _retry_supabase(
        lambda: (
            db.table("bets")
            .select("*")
            .eq("id", bet_id)
            .eq("user_id", user["id"])
            .execute()
        ),
        label="bets.select_one",
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return build_bet_response(result.data[0], settings["k_factor"])


def update_bet_impl(db, user: dict, bet_id: str, bet: BetUpdate) -> BetResponse:
    settings = get_user_settings(db, user["id"])

    payload = bet.model_dump(exclude_unset=True)
    data: dict = {}
    if payload.get("sport") is not None:
        data["sport"] = payload["sport"]
    if payload.get("event") is not None:
        data["event"] = payload["event"]
    if payload.get("market") is not None:
        data["market"] = payload["market"]
    if payload.get("surface") is not None:
        data["surface"] = payload["surface"]
    if payload.get("sportsbook") is not None:
        data["sportsbook"] = payload["sportsbook"]
    if payload.get("promo_type") is not None:
        data["promo_type"] = payload["promo_type"].value
    if payload.get("odds_american") is not None:
        data["odds_american"] = payload["odds_american"]
    if payload.get("stake") is not None:
        data["stake"] = payload["stake"]
    if "boost_percent" in payload:
        data["boost_percent"] = payload["boost_percent"]
    if "winnings_cap" in payload:
        data["winnings_cap"] = payload["winnings_cap"]
    if "notes" in payload:
        data["notes"] = payload["notes"]
    if payload.get("result") is not None:
        data["result"] = payload["result"].value
        current = _retry_supabase(
            lambda: (
                db.table("bets")
                .select("result")
                .eq("id", bet_id)
                .eq("user_id", user["id"])
                .execute()
            ),
            label="bets.select_result_before_update",
        )
        if current.data and current.data[0]["result"] == "pending" and payload["result"].value != "pending":
            data["settled_at"] = datetime.now(UTC).isoformat()
    if "payout_override" in payload:
        data["payout_override"] = payload["payout_override"]
    if "opposing_odds" in payload:
        data["opposing_odds"] = payload["opposing_odds"]
    if payload.get("event_date") is not None:
        data["event_date"] = payload["event_date"].isoformat()

    EV_RELEVANT = {"odds_american", "stake", "promo_type", "boost_percent",
                   "winnings_cap", "payout_override", "opposing_odds"}
    if data.keys() & EV_RELEVANT:
        data["ev_per_dollar_locked"] = None
        data["ev_total_locked"] = None
        data["win_payout_locked"] = None
        data["ev_locked_at"] = None

    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    started_at = time.monotonic()
    result = _retry_supabase(
        lambda: (
            db.table("bets")
            .update(data)
            .eq("id", bet_id)
            .eq("user_id", user["id"])
            .execute()
        ),
        label="bets.update",
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    row = result.data[0]
    row = _lock_ev_for_row(db, bet_id, user["id"], row, settings)
    _log_structured_event(
        "bets.update.completed",
        user_id=str(user.get("id") or ""),
        bet_id=bet_id,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        updated_fields=sorted(data.keys()),
    )
    return build_bet_response(row, settings["k_factor"])


def update_bet_result_impl(db, user: dict, bet_id: str, result: BetResult) -> BetResponse:
    settings = get_user_settings(db, user["id"])

    update_data: dict = {"result": result.value}

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


def delete_bet_impl(db, user: dict, bet_id: str) -> dict:
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
