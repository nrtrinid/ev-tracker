import os
from datetime import UTC, datetime
from typing import Any

from models import BetResult

from services.paper_autolog_flow import (
    build_eligible_autolog_sides,
    build_pending_autolog_keys,
    build_autolog_insert_payload,
    run_autolog_insert_loop,
)

LONGSHOT_AUTOLOG_SPORTS = {"basketball_nba", "basketball_ncaab"}
LOW_EDGE_COHORT = "low_edge_test"
HIGH_EDGE_COHORT = "high_edge_longshot_test"
LOW_EDGE_EV_MIN = 0.5
LOW_EDGE_EV_MAX = 1.5
LOW_EDGE_ODDS_MIN = -200
LOW_EDGE_ODDS_MAX = 300
HIGH_EDGE_EV_MIN = 10.0
HIGH_EDGE_ODDS_MIN = 700
AUTOLOG_MAX_TOTAL = 5
AUTOLOG_MAX_LOW = 2
AUTOLOG_MAX_HIGH = 3
AUTOLOG_PAPER_STAKE = 10.0


def is_paper_experiment_autolog_enabled() -> bool:
    return (os.getenv("ENABLE_PAPER_EXPERIMENT_AUTOLOG") or "0") == "1"


def paper_experiment_account_user_id() -> str:
    return (os.getenv("PAPER_EXPERIMENT_ACCOUNT_USER_ID") or "").strip()


def execute_longshot_autolog(
    *,
    db,
    run_id: str,
    user_id: str,
    sides: list[dict[str, Any]],
    supported_sports: set[str],
    low_edge_cohort: str,
    high_edge_cohort: str,
    low_edge_ev_min: float,
    low_edge_ev_max: float,
    low_edge_odds_min: float,
    low_edge_odds_max: float,
    high_edge_ev_min: float,
    high_edge_odds_min: float,
    max_total: int,
    max_low: int,
    max_high: int,
    paper_stake: float,
    pending_result_value: str,
    now_iso: str,
    today_iso: str,
) -> dict[str, Any]:
    eligible = build_eligible_autolog_sides(
        sides=sides,
        supported_sports=supported_sports,
        low_edge_cohort=low_edge_cohort,
        high_edge_cohort=high_edge_cohort,
        low_edge_ev_min=low_edge_ev_min,
        low_edge_ev_max=low_edge_ev_max,
        low_edge_odds_min=low_edge_odds_min,
        low_edge_odds_max=low_edge_odds_max,
        high_edge_ev_min=high_edge_ev_min,
        high_edge_odds_min=high_edge_odds_min,
    )

    existing_pending = (
        db.table("bets")
        .select("strategy_cohort,clv_sport_key,commence_time,clv_team,clv_event_id,sportsbook,market")
        .eq("user_id", user_id)
        .eq("result", "pending")
        .eq("market", "ML")
        .in_("strategy_cohort", [low_edge_cohort, high_edge_cohort])
        .execute()
    )
    pending_keys = build_pending_autolog_keys(existing_pending.data or [])

    loop_summary = run_autolog_insert_loop(
        eligible_sides=eligible,
        run_id=run_id,
        pending_keys=pending_keys,
        low_edge_cohort=low_edge_cohort,
        high_edge_cohort=high_edge_cohort,
        max_total=max_total,
        max_low=max_low,
        max_high=max_high,
        build_run_payload=lambda side, cohort, run_key: build_autolog_insert_payload(
            user_id=user_id,
            side=side,
            cohort=cohort,
            run_key=run_key,
            run_at=now_iso,
            paper_stake=paper_stake,
            pending_result_value=pending_result_value,
            fallback_event_date=today_iso,
        ),
        has_existing_run_key=lambda run_key: bool(
            (
                db.table("bets")
                .select("id")
                .eq("user_id", user_id)
                .eq("auto_log_run_key", run_key)
                .limit(1)
                .execute()
            ).data
        ),
        insert_payload=lambda payload: db.table("bets").insert(payload).execute(),
    )

    return {
        "run_id": run_id,
        "candidates_seen": len(sides),
        "eligible_seen": len(eligible),
        **loop_summary,
    }


async def run_longshot_autolog_for_sides(db, *, run_id: str, sides: list[dict]) -> dict[str, Any]:
    """Autolog paper tickets from existing scan sides with deterministic caps and dedupe."""
    if not is_paper_experiment_autolog_enabled():
        return {"enabled": False, "inserted_total": 0}

    user_id = paper_experiment_account_user_id()
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
