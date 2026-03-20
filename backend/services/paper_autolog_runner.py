from typing import Any

from services.paper_autolog_flow import (
    build_eligible_autolog_sides,
    build_pending_autolog_keys,
    build_autolog_insert_payload,
    run_autolog_insert_loop,
)


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
        .select("strategy_cohort,clv_sport_key,commence_time,clv_team,sportsbook,market")
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