from typing import Any, Callable

from services.paper_autolog_utils import (
    autolog_key_for_side,
    autolog_legacy_key_for_side,
    cohort_for_side,
    sport_display,
)


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def build_eligible_autolog_sides(
    *,
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
) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for side in sides:
        cohort = cohort_for_side(
            side,
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
        if not cohort:
            continue
        side_copy = dict(side)
        side_copy["strategy_cohort"] = cohort
        eligible.append(side_copy)

    eligible.sort(
        key=lambda s: (
            -float(s.get("ev_percentage") or 0),
            str(s.get("commence_time") or ""),
            autolog_key_for_side(s, s["strategy_cohort"]),
        )
    )
    return eligible


def build_pending_autolog_keys(pending_rows: list[dict[str, Any]]) -> set[str]:
    pending_keys: set[str] = set()
    for row in pending_rows:
        key = "|".join([
            "v1",
            str(row.get("strategy_cohort") or ""),
            _normalize_text(row.get("clv_sport_key") or row.get("sport")),
            (
                f"id:{_normalize_text(row.get('clv_event_id'))}"
                if _normalize_text(row.get("clv_event_id"))
                else str(row.get("commence_time") or "").strip()
            ),
            _normalize_text(row.get("clv_team")),
            _normalize_text(row.get("sportsbook")),
            _normalize_text(row.get("market")),
        ])
        pending_keys.add(key)
        pending_keys.add("|".join([
            "v1",
            str(row.get("strategy_cohort") or ""),
            _normalize_text(row.get("clv_sport_key") or row.get("sport")),
            str(row.get("commence_time") or "").strip(),
            _normalize_text(row.get("clv_team")),
            _normalize_text(row.get("sportsbook")),
            _normalize_text(row.get("market")),
        ]))
    return pending_keys


def build_autolog_insert_payload(
    *,
    user_id: str,
    side: dict[str, Any],
    cohort: str,
    run_key: str,
    run_at: str,
    paper_stake: float,
    pending_result_value: str,
    fallback_event_date: str,
) -> dict[str, Any]:
    commence_time = str(side.get("commence_time") or "")
    event_date = commence_time[:10] if len(commence_time) >= 10 else fallback_event_date

    return {
        "user_id": user_id,
        "sport": sport_display(str(side.get("sport") or "")),
        "event": f"{side.get('team')} ML",
        "market": "ML",
        "sportsbook": side.get("sportsbook"),
        "promo_type": "standard",
        "odds_american": side.get("book_odds"),
        "stake": paper_stake,
        "result": pending_result_value,
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


def run_autolog_insert_loop(
    *,
    eligible_sides: list[dict[str, Any]],
    run_id: str,
    pending_keys: set[str],
    low_edge_cohort: str,
    high_edge_cohort: str,
    max_total: int,
    max_low: int,
    max_high: int,
    build_run_payload: Callable[[dict[str, Any], str, str], dict[str, Any]],
    has_existing_run_key: Callable[[str], bool],
    insert_payload: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    inserted_total = 0
    selected_by_cohort = {low_edge_cohort: 0, high_edge_cohort: 0}
    inserted_by_cohort = {low_edge_cohort: 0, high_edge_cohort: 0}
    skipped_duplicate = 0
    skipped_rule = 0
    in_run_keys: set[str] = set()

    for side in eligible_sides:
        cohort = side["strategy_cohort"]
        key = autolog_key_for_side(side, cohort)
        legacy_key = autolog_legacy_key_for_side(side, cohort)

        if key in pending_keys or key in in_run_keys or legacy_key in pending_keys or legacy_key in in_run_keys:
            skipped_duplicate += 1
            continue

        if inserted_total >= max_total:
            skipped_rule += 1
            continue

        if cohort == low_edge_cohort and inserted_by_cohort[low_edge_cohort] >= max_low:
            skipped_rule += 1
            continue
        if cohort == high_edge_cohort and inserted_by_cohort[high_edge_cohort] >= max_high:
            skipped_rule += 1
            continue

        selected_by_cohort[cohort] += 1
        run_key = f"{run_id}|{key}"

        if has_existing_run_key(run_key):
            skipped_duplicate += 1
            continue

        payload = build_run_payload(side, cohort, run_key)
        insert_payload(payload)

        inserted_total += 1
        inserted_by_cohort[cohort] += 1
        in_run_keys.add(key)
        in_run_keys.add(legacy_key)
        pending_keys.add(key)
        pending_keys.add(legacy_key)

    return {
        "selected_by_cohort": selected_by_cohort,
        "inserted_total": inserted_total,
        "inserted_by_cohort": inserted_by_cohort,
        "skipped_duplicate": skipped_duplicate,
        "skipped_rule": skipped_rule,
    }