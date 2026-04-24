from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from calculations import calculate_clv, calculate_close_calibration_metrics
from models import (
    ModelCalibrationBreakdownItem,
    ModelCalibrationCohortTrendRow,
    ModelCalibrationRecentComparisonRow,
    ModelCalibrationReleaseGate,
    ModelCalibrationSummaryResponse,
    PlayerPropModelWeightStatus,
    PlayerPropShadowCandidateSummary,
)
from services.player_prop_weights import (
    is_missing_player_prop_model_weights_error,
    is_missing_scan_opportunity_model_evaluations_error,
)
from services.player_prop_candidate_observations import (
    DISPLAYED_DEFAULT_COHORT,
    PLAYER_PROP_MODEL_CANDIDATE_TABLE,
    is_missing_player_prop_model_candidate_observations_error,
    update_player_prop_model_candidate_observation_close_snapshot,
)
from services.supabase_paging import fetch_all_rows

BASELINE_MODEL_KEY = "props_v1_live"
SHADOW_MODEL_KEY = "props_v2_shadow"
LIVE_V2_MODEL_KEY = "props_v2_live"
IDENTICAL_MODEL_VALUE_EPSILON = 1e-9
METRIC_TIE_EPSILON = 1e-12
RELEASE_GATE_BRIER_DEADBAND = 0.00001
RELEASE_GATE_LOG_LOSS_DEADBAND = 0.00001
RELEASE_GATE_CLV_DEADBAND_PCT_POINTS = 0.10
RELEASE_GATE_BEAT_CLOSE_DEADBAND_PCT_POINTS = 1.0
PLAYER_PROP_WEIGHT_STALE_AFTER_HOURS = 72


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _comparison_close_status(row: dict[str, Any]) -> str:
    close_prob = _coerce_float(row.get("close_true_prob"))
    close_captured_at = _coerce_datetime(row.get("close_captured_at"))
    close_quality = str(row.get("close_quality") or "").strip().lower()
    if close_prob is None or close_captured_at is None:
        return "pending"
    if close_quality not in {"paired", "single"}:
        return "invalid"
    if _coerce_float(row.get("first_clv_ev_percent")) is None:
        return "invalid"
    if row.get("first_beat_close") is None:
        return "invalid"
    if _coerce_float(row.get("first_brier_score")) is None:
        return "invalid"
    if _coerce_float(row.get("first_log_loss")) is None:
        return "invalid"
    return "valid"


def empty_model_calibration_summary(
    *,
    shadow_candidate_set: PlayerPropShadowCandidateSummary | None = None,
) -> ModelCalibrationSummaryResponse:
    return ModelCalibrationSummaryResponse(
        captured_count=0,
        valid_close_count=0,
        paired_close_count=0,
        fallback_close_count=0,
        paired_close_pct=None,
        by_model=[],
        by_market=[],
        by_sportsbook=[],
        by_interpolation_mode=[],
        cohort_trend=[],
        recent_comparisons=[],
        shadow_candidate_set=shadow_candidate_set or PlayerPropShadowCandidateSummary(),
        release_gate=ModelCalibrationReleaseGate(
            candidate_model_key=SHADOW_MODEL_KEY,
            baseline_model_key=BASELINE_MODEL_KEY,
            candidate_valid_close_count=0,
            baseline_valid_close_count=0,
            candidate_avg_brier_score=None,
            baseline_avg_brier_score=None,
            candidate_avg_log_loss=None,
            baseline_avg_log_loss=None,
            candidate_avg_clv_percent=None,
            baseline_avg_clv_percent=None,
            candidate_beat_close_pct=None,
            baseline_beat_close_pct=None,
            verdict="not_enough_sample",
            eligible=False,
            passes=False,
            reasons=["Not enough valid closes to evaluate the shadow model."],
        ),
    )


def update_scan_opportunity_model_evaluations_close_snapshot(
    db,
    *,
    opportunity_key: str,
    close_reference_odds: float,
    close_opposing_reference_odds: float | None,
    close_captured_at: str,
) -> int:
    try:
        result = (
            db.table("scan_opportunity_model_evaluations")
            .select(
                "id,first_true_prob,last_true_prob,first_book_odds,last_book_odds"
            )
            .eq("opportunity_key", opportunity_key)
            .execute()
        )
    except Exception as exc:
        if is_missing_scan_opportunity_model_evaluations_error(exc):
            return 0
        raise

    updated = 0
    for row in result.data or []:
        first_book_odds = _coerce_float(row.get("first_book_odds"))
        last_book_odds = _coerce_float(row.get("last_book_odds"))
        if first_book_odds is None and last_book_odds is None:
            continue

        base_result = calculate_clv(
            first_book_odds if first_book_odds is not None else last_book_odds,
            close_reference_odds,
            close_opposing_reference_odds,
        )
        close_true_prob = float(base_result["close_true_prob"])

        first_clv = (
            calculate_clv(first_book_odds, close_reference_odds, close_opposing_reference_odds)
            if first_book_odds is not None
            else None
        )
        last_clv = (
            calculate_clv(last_book_odds, close_reference_odds, close_opposing_reference_odds)
            if last_book_odds is not None
            else None
        )
        first_metrics = calculate_close_calibration_metrics(
            _coerce_float(row.get("first_true_prob")) or close_true_prob,
            close_true_prob,
        )
        last_metrics = calculate_close_calibration_metrics(
            _coerce_float(row.get("last_true_prob")) or close_true_prob,
            close_true_prob,
        )

        payload = {
            "close_reference_odds": close_reference_odds,
            "close_opposing_reference_odds": close_opposing_reference_odds,
            "close_true_prob": close_true_prob,
            "close_quality": base_result.get("close_quality"),
            "close_captured_at": close_captured_at,
            "first_clv_ev_percent": first_clv.get("clv_ev_percent") if first_clv else None,
            "last_clv_ev_percent": last_clv.get("clv_ev_percent") if last_clv else None,
            "first_beat_close": first_clv.get("beat_close") if first_clv else None,
            "last_beat_close": last_clv.get("beat_close") if last_clv else None,
            "first_brier_score": first_metrics.get("brier_score") if first_metrics else None,
            "last_brier_score": last_metrics.get("brier_score") if last_metrics else None,
            "first_log_loss": first_metrics.get("log_loss") if first_metrics else None,
            "last_log_loss": last_metrics.get("log_loss") if last_metrics else None,
        }
        db.table("scan_opportunity_model_evaluations").update(payload).eq("id", row["id"]).execute()
        updated += 1

    try:
        update_player_prop_model_candidate_observation_close_snapshot(
            db,
            opportunity_key=opportunity_key,
            close_reference_odds=close_reference_odds,
            close_opposing_reference_odds=close_opposing_reference_odds,
            close_captured_at=close_captured_at,
        )
    except Exception as exc:
        if not is_missing_player_prop_model_candidate_observations_error(exc):
            raise

    return updated


def _build_breakdown(
    rows: list[dict[str, Any]],
    *,
    key_fn,
    paired_opportunity_keys: set[str] | None = None,
) -> list[ModelCalibrationBreakdownItem]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row) or "Unknown")].append(row)

    items: list[ModelCalibrationBreakdownItem] = []
    for key, bucket_rows in groups.items():
        valid_rows = [row for row in bucket_rows if row.get("_close_status") == "valid"]
        paired_count = len(
            {
                str(row.get("opportunity_key") or "")
                for row in valid_rows
                if str(row.get("opportunity_key") or "") in (paired_opportunity_keys or set())
            }
        )
        beat_close_count = sum(1 for row in valid_rows if row.get("first_beat_close") is True)

        avg_brier = None
        avg_log_loss = None
        avg_clv = None
        beat_close_pct = None
        if valid_rows:
            avg_brier = round(
                sum(float(row["first_brier_score"]) for row in valid_rows if row.get("first_brier_score") is not None)
                / max(1, sum(1 for row in valid_rows if row.get("first_brier_score") is not None)),
                6,
            )
            avg_log_loss = round(
                sum(float(row["first_log_loss"]) for row in valid_rows if row.get("first_log_loss") is not None)
                / max(1, sum(1 for row in valid_rows if row.get("first_log_loss") is not None)),
                6,
            )
            avg_clv = round(
                sum(float(row["first_clv_ev_percent"]) for row in valid_rows if row.get("first_clv_ev_percent") is not None)
                / max(1, sum(1 for row in valid_rows if row.get("first_clv_ev_percent") is not None)),
                2,
            )
            beat_close_pct = round((beat_close_count / len(valid_rows)) * 100, 2)

        items.append(
            ModelCalibrationBreakdownItem(
                key=key,
                captured_count=len(bucket_rows),
                valid_close_count=len(valid_rows),
                paired_close_count=paired_count,
                avg_brier_score=avg_brier,
                avg_log_loss=avg_log_loss,
                avg_clv_percent=avg_clv,
                beat_close_pct=beat_close_pct,
            )
        )

    items.sort(key=lambda item: (-item.valid_close_count, -item.captured_count, item.key))
    return items


def _average_metric(rows: list[dict[str, Any]], field: str, digits: int) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _metric_delta(candidate: float | None, baseline: float | None, digits: int) -> float | None:
    if candidate is None or baseline is None:
        return None
    return round(candidate - baseline, digits)


def _delta_within_deadband(delta: float | None, deadband: float, *, lower_is_better: bool) -> bool:
    if delta is None:
        return True
    if lower_is_better:
        return delta <= deadband
    return delta >= -deadband


def _delta_stats(values: list[float], digits: int) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    return (
        round(sum(values) / len(values), digits),
        round(sum(abs(value) for value in values) / len(values), digits),
        round(max(abs(value) for value in values), digits),
    )


def _release_gate_pairwise_diagnostics(
    paired_rows: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    true_prob_deltas: list[float] = []
    ev_deltas: list[float] = []
    identical_true_prob_count = 0
    identical_ev_count = 0
    brier_candidate_better_count = 0
    brier_baseline_better_count = 0
    brier_tie_count = 0
    log_loss_candidate_better_count = 0
    log_loss_baseline_better_count = 0
    log_loss_tie_count = 0

    for baseline, candidate in paired_rows:
        baseline_true_prob = _coerce_float(baseline.get("first_true_prob"))
        candidate_true_prob = _coerce_float(candidate.get("first_true_prob"))
        if baseline_true_prob is not None and candidate_true_prob is not None:
            true_prob_delta = (candidate_true_prob - baseline_true_prob) * 100
            true_prob_deltas.append(true_prob_delta)
            if abs(candidate_true_prob - baseline_true_prob) <= IDENTICAL_MODEL_VALUE_EPSILON:
                identical_true_prob_count += 1

        baseline_ev = _coerce_float(baseline.get("first_ev_percentage"))
        candidate_ev = _coerce_float(candidate.get("first_ev_percentage"))
        if baseline_ev is not None and candidate_ev is not None:
            ev_delta = candidate_ev - baseline_ev
            ev_deltas.append(ev_delta)
            if abs(ev_delta) <= IDENTICAL_MODEL_VALUE_EPSILON:
                identical_ev_count += 1

        baseline_brier = _coerce_float(baseline.get("first_brier_score"))
        candidate_brier = _coerce_float(candidate.get("first_brier_score"))
        if baseline_brier is not None and candidate_brier is not None:
            if candidate_brier < baseline_brier - METRIC_TIE_EPSILON:
                brier_candidate_better_count += 1
            elif candidate_brier > baseline_brier + METRIC_TIE_EPSILON:
                brier_baseline_better_count += 1
            else:
                brier_tie_count += 1

        baseline_log_loss = _coerce_float(baseline.get("first_log_loss"))
        candidate_log_loss = _coerce_float(candidate.get("first_log_loss"))
        if baseline_log_loss is not None and candidate_log_loss is not None:
            if candidate_log_loss < baseline_log_loss - METRIC_TIE_EPSILON:
                log_loss_candidate_better_count += 1
            elif candidate_log_loss > baseline_log_loss + METRIC_TIE_EPSILON:
                log_loss_baseline_better_count += 1
            else:
                log_loss_tie_count += 1

    avg_true_prob_delta, avg_abs_true_prob_delta, max_abs_true_prob_delta = _delta_stats(true_prob_deltas, 4)
    avg_ev_delta, avg_abs_ev_delta, max_abs_ev_delta = _delta_stats(ev_deltas, 4)
    paired_count = len(paired_rows)

    return {
        "avg_true_prob_delta_pct_points": avg_true_prob_delta,
        "avg_abs_true_prob_delta_pct_points": avg_abs_true_prob_delta,
        "max_abs_true_prob_delta_pct_points": max_abs_true_prob_delta,
        "identical_true_prob_count": identical_true_prob_count,
        "identical_true_prob_pct": (
            round((identical_true_prob_count / paired_count) * 100, 2)
            if paired_count
            else None
        ),
        "avg_ev_delta_pct_points": avg_ev_delta,
        "avg_abs_ev_delta_pct_points": avg_abs_ev_delta,
        "max_abs_ev_delta_pct_points": max_abs_ev_delta,
        "identical_ev_count": identical_ev_count,
        "identical_ev_pct": round((identical_ev_count / paired_count) * 100, 2) if paired_count else None,
        "brier_candidate_better_count": brier_candidate_better_count,
        "brier_baseline_better_count": brier_baseline_better_count,
        "brier_tie_count": brier_tie_count,
        "log_loss_candidate_better_count": log_loss_candidate_better_count,
        "log_loss_baseline_better_count": log_loss_baseline_better_count,
        "log_loss_tie_count": log_loss_tie_count,
    }


def _empty_weight_status(*, available: bool = True) -> PlayerPropModelWeightStatus:
    return PlayerPropModelWeightStatus(
        override_count=0,
        markets_covered=0,
        latest_updated_at=None,
        stale_after_hours=PLAYER_PROP_WEIGHT_STALE_AFTER_HOURS,
        default_only=True,
        stale=False,
        available=available,
    )


def _get_player_prop_weight_status(db) -> PlayerPropModelWeightStatus:
    try:
        result = db.table("player_prop_model_weights").select(
            "model_family,market_key,sportsbook_key,updated_at"
        ).execute()
    except Exception as exc:
        if is_missing_player_prop_model_weights_error(exc):
            return _empty_weight_status(available=False)
        raise

    rows = [
        row for row in (result.data or [])
        if str(row.get("model_family") or "").strip().lower() == "props_v2"
    ]
    latest = max((_coerce_datetime(row.get("updated_at")) for row in rows), default=None)
    now = _utc_now()
    stale = bool(
        latest is not None
        and (now - latest).total_seconds() > PLAYER_PROP_WEIGHT_STALE_AFTER_HOURS * 3600
    )
    return PlayerPropModelWeightStatus(
        override_count=len(rows),
        markets_covered=len({str(row.get("market_key") or "").strip() for row in rows if row.get("market_key")}),
        latest_updated_at=latest,
        stale_after_hours=PLAYER_PROP_WEIGHT_STALE_AFTER_HOURS,
        default_only=len(rows) == 0,
        stale=stale,
        available=True,
    )


def _average_values(values: list[float], digits: int) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _top_overlap_pct(
    v1_rows: list[dict[str, Any]],
    v2_rows: list[dict[str, Any]],
    limit: int,
) -> float | None:
    top_v1 = {
        str(row.get("opportunity_key") or "")
        for row in sorted(v1_rows, key=lambda row: int(row.get("rank_overall") or 999999))[:limit]
        if row.get("opportunity_key")
    }
    top_v2 = {
        str(row.get("opportunity_key") or "")
        for row in sorted(v2_rows, key=lambda row: int(row.get("rank_overall") or 999999))[:limit]
        if row.get("opportunity_key")
    }
    denominator = max(len(top_v1), len(top_v2))
    return _pct(len(top_v1 & top_v2), denominator)


def _shadow_candidate_counts_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    v1_rows = [row for row in rows if str(row.get("model_key") or "").strip().lower() == BASELINE_MODEL_KEY]
    v2_rows = [row for row in rows if str(row.get("model_key") or "").strip().lower() == SHADOW_MODEL_KEY]
    v1_by_key = {str(row.get("opportunity_key") or ""): row for row in v1_rows if row.get("opportunity_key")}
    v2_by_key = {str(row.get("opportunity_key") or ""): row for row in v2_rows if row.get("opportunity_key")}
    v1_keys = set(v1_by_key)
    v2_keys = set(v2_by_key)
    both_keys = v1_keys & v2_keys
    v2_only_keys = v2_keys - v1_keys
    v2_only_rows = [v2_by_key[key] for key in v2_only_keys]
    return {
        "v1_rows": v1_rows,
        "v2_rows": v2_rows,
        "v1_by_key": v1_by_key,
        "v2_by_key": v2_by_key,
        "v1_keys": v1_keys,
        "v2_keys": v2_keys,
        "both_keys": both_keys,
        "v2_only_keys": v2_only_keys,
        "v2_only_rows": v2_only_rows,
    }


def _get_shadow_candidate_summary(db) -> PlayerPropShadowCandidateSummary:
    weight_status = _get_player_prop_weight_status(db)
    try:
        rows = fetch_all_rows(
            query_factory=lambda offset, page_size: (
                db.table(PLAYER_PROP_MODEL_CANDIDATE_TABLE)
                .select(
                    "candidate_set_key,source,captured_at,model_key,opportunity_key,rank_overall,rank_displayed,cohort,"
                    "ev_percentage,clv_ev_percent,beat_close,brier_score,log_loss"
                )
                .order("captured_at", desc=True)
                .range(offset, offset + page_size - 1)
            )
        )
    except Exception as exc:
        if is_missing_player_prop_model_candidate_observations_error(exc):
            return PlayerPropShadowCandidateSummary(weight_status=weight_status)
        raise

    if not rows:
        return PlayerPropShadowCandidateSummary(weight_status=weight_status)

    latest_row = max(rows, key=lambda row: _coerce_datetime(row.get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc))
    latest_key = str(latest_row.get("candidate_set_key") or "")
    latest_rows = [row for row in rows if str(row.get("candidate_set_key") or "") == latest_key]
    latest_counts = _shadow_candidate_counts_for_rows(latest_rows)
    v1_rows = latest_counts["v1_rows"]
    v2_rows = latest_counts["v2_rows"]
    v1_by_key = latest_counts["v1_by_key"]
    v2_by_key = latest_counts["v2_by_key"]
    v1_keys = latest_counts["v1_keys"]
    v2_keys = latest_counts["v2_keys"]
    both_keys = latest_counts["both_keys"]
    v2_only_keys = latest_counts["v2_only_keys"]

    rolling_candidate_set_count = 0
    rolling_both_count = 0
    rolling_v1_only_count = 0
    rolling_v2_only_count = 0
    rolling_v2_only_displayed_count = 0
    rolling_union_count = 0
    rows_by_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        set_key = str(row.get("candidate_set_key") or "")
        if set_key:
            rows_by_set[set_key].append(row)
    for set_rows in rows_by_set.values():
        counts = _shadow_candidate_counts_for_rows(set_rows)
        set_v1_keys = counts["v1_keys"]
        set_v2_keys = counts["v2_keys"]
        if not set_v1_keys and not set_v2_keys:
            continue
        rolling_candidate_set_count += 1
        rolling_both_count += len(counts["both_keys"])
        rolling_v1_only_count += len(set_v1_keys - set_v2_keys)
        rolling_v2_only_count += len(counts["v2_only_keys"])
        rolling_union_count += len(set_v1_keys | set_v2_keys)
        rolling_v2_only_displayed_count += sum(
            1 for row in counts["v2_only_rows"]
            if str(row.get("cohort") or "").strip().lower() == DISPLAYED_DEFAULT_COHORT
        )

    ev_deltas = []
    rank_deltas = []
    for key in both_keys:
        v1 = v1_by_key[key]
        v2 = v2_by_key[key]
        v1_ev = _coerce_float(v1.get("ev_percentage"))
        v2_ev = _coerce_float(v2.get("ev_percentage"))
        if v1_ev is not None and v2_ev is not None:
            ev_deltas.append(v2_ev - v1_ev)
        v1_rank = _coerce_float(v1.get("rank_overall"))
        v2_rank = _coerce_float(v2.get("rank_overall"))
        if v1_rank is not None and v2_rank is not None:
            rank_deltas.append(v2_rank - v1_rank)

    v2_only_rows = latest_counts["v2_only_rows"]
    v2_only_valid_rows = [
        row for row in v2_only_rows
        if _coerce_float(row.get("clv_ev_percent")) is not None
        and _coerce_float(row.get("brier_score")) is not None
        and _coerce_float(row.get("log_loss")) is not None
        and row.get("beat_close") is not None
    ]

    return PlayerPropShadowCandidateSummary(
        latest_candidate_set_key=latest_key or None,
        latest_source=str(latest_row.get("source") or "").strip() or None,
        latest_captured_at=_coerce_datetime(latest_row.get("captured_at")),
        rolling_candidate_set_count=rolling_candidate_set_count,
        v1_count=len(v1_keys),
        v2_count=len(v2_keys),
        both_count=len(both_keys),
        v1_only_count=len(v1_keys - v2_keys),
        v2_only_count=len(v2_only_keys),
        overlap_pct=_pct(len(both_keys), len(v1_keys | v2_keys)),
        rolling_both_count=rolling_both_count,
        rolling_v1_only_count=rolling_v1_only_count,
        rolling_v2_only_count=rolling_v2_only_count,
        rolling_overlap_pct=_pct(rolling_both_count, rolling_union_count),
        rolling_v2_only_displayed_count=rolling_v2_only_displayed_count,
        top_25_overlap_pct=_top_overlap_pct(v1_rows, v2_rows, 25),
        top_50_overlap_pct=_top_overlap_pct(v1_rows, v2_rows, 50),
        avg_ev_delta_pct_points=_average_values(ev_deltas, 4),
        avg_rank_delta=_average_values(rank_deltas, 2),
        v2_only_displayed_count=sum(
            1 for row in v2_only_rows
            if str(row.get("cohort") or "").strip().lower() == DISPLAYED_DEFAULT_COHORT
        ),
        v2_only_valid_close_count=len(v2_only_valid_rows),
        v2_only_avg_clv_percent=_average_values(
            [float(row["clv_ev_percent"]) for row in v2_only_valid_rows if row.get("clv_ev_percent") is not None],
            2,
        ),
        v2_only_beat_close_pct=_pct(
            sum(1 for row in v2_only_valid_rows if row.get("beat_close") is True),
            len(v2_only_valid_rows),
        ),
        v2_only_avg_brier_score=_average_values(
            [float(row["brier_score"]) for row in v2_only_valid_rows if row.get("brier_score") is not None],
            6,
        ),
        v2_only_avg_log_loss=_average_values(
            [float(row["log_loss"]) for row in v2_only_valid_rows if row.get("log_loss") is not None],
            6,
        ),
        weight_status=weight_status,
    )


def _paired_release_gate_rows(
    valid_rows: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], set[str]]:
    comparison_groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    comparison_keys: set[str] = set()

    for row in valid_rows:
        model_key = str(row.get("model_key") or "").strip()
        if model_key not in {BASELINE_MODEL_KEY, SHADOW_MODEL_KEY}:
            continue
        opportunity_key = str(row.get("opportunity_key") or "").strip()
        if not opportunity_key:
            continue
        comparison_groups[opportunity_key][model_key] = row
        comparison_keys.add(opportunity_key)

    paired_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for opportunity_key, group in comparison_groups.items():
        baseline = group.get(BASELINE_MODEL_KEY)
        candidate = group.get(SHADOW_MODEL_KEY)
        if baseline is None or candidate is None:
            continue
        paired_rows.append((baseline, candidate))

    return paired_rows, comparison_keys


def get_model_calibration_summary(db) -> ModelCalibrationSummaryResponse:
    try:
        rows = fetch_all_rows(
            query_factory=lambda offset, page_size: (
                db.table("scan_opportunity_model_evaluations")
                .select(
                    "opportunity_key,model_key,capture_role,surface,sport,event,team,sportsbook,sportsbook_key,market,event_id,"
                    "player_name,selection_side,line_value,first_seen_at,last_seen_at,first_true_prob,last_true_prob,"
                    "first_reference_odds,last_reference_odds,first_ev_percentage,last_ev_percentage,"
                    "first_confidence_score,last_confidence_score,first_reference_bookmaker_count,last_reference_bookmaker_count,"
                    "first_interpolation_mode,last_interpolation_mode,close_reference_odds,close_opposing_reference_odds,"
                    "close_true_prob,close_quality,close_captured_at,first_clv_ev_percent,last_clv_ev_percent,"
                    "first_beat_close,last_beat_close,first_brier_score,last_brier_score,first_log_loss,last_log_loss"
                )
                .order("opportunity_key", desc=False)
                .order("model_key", desc=False)
                .range(offset, offset + page_size - 1)
            )
        )
    except Exception as exc:
        if is_missing_scan_opportunity_model_evaluations_error(exc):
            return empty_model_calibration_summary(shadow_candidate_set=_get_shadow_candidate_summary(db))
        raise

    if not rows:
        return empty_model_calibration_summary(shadow_candidate_set=_get_shadow_candidate_summary(db))

    shadow_candidate_set = _get_shadow_candidate_summary(db)

    for row in rows:
        row["_close_status"] = _comparison_close_status(row)
        first_seen_dt = _coerce_datetime(row.get("first_seen_at"))
        row["_cohort_key"] = first_seen_dt.date().isoformat() if first_seen_dt is not None else "unknown"

    valid_rows = [row for row in rows if row.get("_close_status") == "valid"]
    fallback_rows = [row for row in valid_rows if row.get("close_quality") == "single"]
    paired_rows, comparison_opportunity_keys = _paired_release_gate_rows(valid_rows)
    paired_opportunity_keys = {
        str(baseline.get("opportunity_key") or "")
        for baseline, _candidate in paired_rows
        if str(baseline.get("opportunity_key") or "")
    }

    by_model = _build_breakdown(
        rows,
        key_fn=lambda row: row.get("model_key") or "Unknown",
        paired_opportunity_keys=paired_opportunity_keys,
    )
    by_market = _build_breakdown(
        rows,
        key_fn=lambda row: row.get("market") or "Unknown",
        paired_opportunity_keys=paired_opportunity_keys,
    )
    by_sportsbook = _build_breakdown(
        rows,
        key_fn=lambda row: row.get("sportsbook") or "Unknown",
        paired_opportunity_keys=paired_opportunity_keys,
    )
    by_interpolation_mode = _build_breakdown(
        rows,
        key_fn=lambda row: row.get("first_interpolation_mode") or "Unknown",
        paired_opportunity_keys=paired_opportunity_keys,
    )

    cohort_trend: list[ModelCalibrationCohortTrendRow] = []
    for cohort_key in sorted({str(row.get("_cohort_key") or "unknown") for row in rows}):
        bucket_rows = [row for row in rows if row.get("_cohort_key") == cohort_key]
        valid_bucket_rows = [row for row in bucket_rows if row.get("_close_status") == "valid"]
        cohort_trend.append(
            ModelCalibrationCohortTrendRow(
                cohort_key=cohort_key,
                captured_count=len(bucket_rows),
                valid_close_count=len(valid_bucket_rows),
                avg_brier_score=_average_metric(valid_bucket_rows, "first_brier_score", 6),
                avg_log_loss=_average_metric(valid_bucket_rows, "first_log_loss", 6),
                avg_clv_percent=_average_metric(valid_bucket_rows, "first_clv_ev_percent", 2),
                beat_close_pct=(
                    round(
                        (
                            sum(1 for row in valid_bucket_rows if row.get("first_beat_close") is True)
                            / len(valid_bucket_rows)
                        ) * 100,
                        2,
                    )
                    if valid_bucket_rows
                    else None
                ),
            )
        )

    comparison_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        comparison_groups[str(row.get("opportunity_key") or "")].append(row)

    recent_comparisons: list[ModelCalibrationRecentComparisonRow] = []
    ordered_keys = sorted(
        comparison_groups.keys(),
        key=lambda key: _coerce_datetime((comparison_groups[key][0]).get("first_seen_at")) or _utc_now(),
        reverse=True,
    )
    for opportunity_key in ordered_keys[:12]:
        group = comparison_groups[opportunity_key]
        baseline = next((row for row in group if str(row.get("model_key") or "") == BASELINE_MODEL_KEY), None)
        shadow = next((row for row in group if str(row.get("model_key") or "") in {SHADOW_MODEL_KEY, LIVE_V2_MODEL_KEY}), None)
        if baseline is None and shadow is None:
            continue
        source_row = baseline or shadow or group[0]
        recent_comparisons.append(
            ModelCalibrationRecentComparisonRow(
                opportunity_key=opportunity_key,
                surface=str(source_row.get("surface") or "player_props"),
                first_seen_at=_coerce_datetime(source_row.get("first_seen_at")) or _utc_now(),
                sport=str(source_row.get("sport") or ""),
                event=str(source_row.get("event") or ""),
                sportsbook=str(source_row.get("sportsbook") or ""),
                market=str(source_row.get("market") or ""),
                player_name=str(source_row.get("player_name") or "").strip() or None,
                selection_side=str(source_row.get("selection_side") or "").strip() or None,
                line_value=_coerce_float(source_row.get("line_value")),
                close_quality=str(source_row.get("close_quality") or "").strip() or None,
                close_true_prob=_coerce_float(source_row.get("close_true_prob")),
                baseline_model_key=str(baseline.get("model_key") or BASELINE_MODEL_KEY) if baseline else None,
                baseline_true_prob=_coerce_float(baseline.get("first_true_prob")) if baseline else None,
                baseline_ev_percentage=_coerce_float(baseline.get("first_ev_percentage")) if baseline else None,
                baseline_clv_ev_percent=_coerce_float(baseline.get("first_clv_ev_percent")) if baseline else None,
                candidate_model_key=str(shadow.get("model_key") or SHADOW_MODEL_KEY) if shadow else None,
                candidate_true_prob=_coerce_float(shadow.get("first_true_prob")) if shadow else None,
                candidate_ev_percentage=_coerce_float(shadow.get("first_ev_percentage")) if shadow else None,
                candidate_clv_ev_percent=_coerce_float(shadow.get("first_clv_ev_percent")) if shadow else None,
            )
        )

    baseline_rows = [baseline for baseline, _candidate in paired_rows]
    candidate_rows = [candidate for _baseline, candidate in paired_rows]
    baseline_beat_close_pct = (
        round((sum(1 for row in baseline_rows if row.get("first_beat_close") is True) / len(baseline_rows)) * 100, 2)
        if baseline_rows
        else None
    )
    candidate_beat_close_pct = (
        round((sum(1 for row in candidate_rows if row.get("first_beat_close") is True) / len(candidate_rows)) * 100, 2)
        if candidate_rows
        else None
    )
    baseline_avg_brier = _average_metric(baseline_rows, "first_brier_score", 6)
    candidate_avg_brier = _average_metric(candidate_rows, "first_brier_score", 6)
    baseline_avg_log = _average_metric(baseline_rows, "first_log_loss", 6)
    candidate_avg_log = _average_metric(candidate_rows, "first_log_loss", 6)
    baseline_avg_clv = _average_metric(baseline_rows, "first_clv_ev_percent", 2)
    candidate_avg_clv = _average_metric(candidate_rows, "first_clv_ev_percent", 2)
    pairwise_diagnostics = _release_gate_pairwise_diagnostics(paired_rows)

    brier_delta = _metric_delta(candidate_avg_brier, baseline_avg_brier, 6)
    log_loss_delta = _metric_delta(candidate_avg_log, baseline_avg_log, 6)
    avg_clv_delta = _metric_delta(candidate_avg_clv, baseline_avg_clv, 2)
    beat_close_delta = _metric_delta(candidate_beat_close_pct, baseline_beat_close_pct, 2)

    reasons: list[str] = []
    eligible = len(paired_rows) >= 200
    if not eligible:
        reasons.append("Need at least 200 paired valid closes shared by baseline and shadow models.")
    if eligible and candidate_avg_brier is not None and baseline_avg_brier is not None and candidate_avg_brier >= baseline_avg_brier:
        reasons.append("Shadow model Brier score is not better than the live baseline.")
    if eligible and candidate_avg_log is not None and baseline_avg_log is not None and candidate_avg_log >= baseline_avg_log:
        reasons.append("Shadow model log loss is not better than the live baseline.")
    if eligible and candidate_avg_clv is not None and baseline_avg_clv is not None and candidate_avg_clv < (baseline_avg_clv - 0.10):
        reasons.append("Shadow model average CLV regressed by more than 0.10 percentage points.")
    if eligible and candidate_beat_close_pct is not None and baseline_beat_close_pct is not None and candidate_beat_close_pct < (baseline_beat_close_pct - 1.0):
        reasons.append("Shadow model beat-close rate regressed by more than 1.0 percentage point.")

    passes = eligible and not reasons
    neutral_within_deadband = bool(
        eligible
        and not passes
        and _delta_within_deadband(
            brier_delta,
            RELEASE_GATE_BRIER_DEADBAND,
            lower_is_better=True,
        )
        and _delta_within_deadband(
            log_loss_delta,
            RELEASE_GATE_LOG_LOSS_DEADBAND,
            lower_is_better=True,
        )
        and _delta_within_deadband(
            avg_clv_delta,
            RELEASE_GATE_CLV_DEADBAND_PCT_POINTS,
            lower_is_better=False,
        )
        and _delta_within_deadband(
            beat_close_delta,
            RELEASE_GATE_BEAT_CLOSE_DEADBAND_PCT_POINTS,
            lower_is_better=False,
        )
    )
    if not eligible:
        verdict = "not_enough_sample"
    elif passes:
        verdict = "promote"
    elif neutral_within_deadband:
        verdict = "hold_neutral"
    else:
        verdict = "fail"

    release_gate = ModelCalibrationReleaseGate(
        candidate_model_key=SHADOW_MODEL_KEY,
        baseline_model_key=BASELINE_MODEL_KEY,
        candidate_valid_close_count=len(candidate_rows),
        baseline_valid_close_count=len(baseline_rows),
        candidate_avg_brier_score=candidate_avg_brier,
        baseline_avg_brier_score=baseline_avg_brier,
        candidate_avg_log_loss=candidate_avg_log,
        baseline_avg_log_loss=baseline_avg_log,
        candidate_avg_clv_percent=candidate_avg_clv,
        baseline_avg_clv_percent=baseline_avg_clv,
        candidate_beat_close_pct=candidate_beat_close_pct,
        baseline_beat_close_pct=baseline_beat_close_pct,
        brier_delta=brier_delta,
        log_loss_delta=log_loss_delta,
        avg_clv_delta_pct_points=avg_clv_delta,
        beat_close_delta_pct_points=beat_close_delta,
        **pairwise_diagnostics,
        verdict=verdict,
        deadband_brier=RELEASE_GATE_BRIER_DEADBAND,
        deadband_log_loss=RELEASE_GATE_LOG_LOSS_DEADBAND,
        deadband_clv_pct_points=RELEASE_GATE_CLV_DEADBAND_PCT_POINTS,
        deadband_beat_close_pct_points=RELEASE_GATE_BEAT_CLOSE_DEADBAND_PCT_POINTS,
        neutral_within_deadband=neutral_within_deadband,
        eligible=eligible,
        passes=passes,
        reasons=reasons or ["Shadow model passed the default promotion gates."],
    )

    return ModelCalibrationSummaryResponse(
        captured_count=len(rows),
        valid_close_count=len(valid_rows),
        paired_close_count=len(paired_rows),
        fallback_close_count=len(fallback_rows),
        paired_close_pct=(
            round((len(paired_rows) / len(comparison_opportunity_keys)) * 100, 2)
            if comparison_opportunity_keys
            else None
        ),
        by_model=by_model,
        by_market=by_market,
        by_sportsbook=by_sportsbook,
        by_interpolation_mode=by_interpolation_mode,
        cohort_trend=cohort_trend,
        recent_comparisons=recent_comparisons,
        shadow_candidate_set=shadow_candidate_set,
        release_gate=release_gate,
    )
