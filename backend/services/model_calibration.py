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
)
from services.player_prop_weights import is_missing_scan_opportunity_model_evaluations_error
from services.supabase_paging import fetch_all_rows

BASELINE_MODEL_KEY = "props_v1_live"
SHADOW_MODEL_KEY = "props_v2_shadow"
LIVE_V2_MODEL_KEY = "props_v2_live"


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


def empty_model_calibration_summary() -> ModelCalibrationSummaryResponse:
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
            return empty_model_calibration_summary()
        raise

    if not rows:
        return empty_model_calibration_summary()

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
        eligible=eligible,
        passes=eligible and not reasons,
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
        release_gate=release_gate,
    )
