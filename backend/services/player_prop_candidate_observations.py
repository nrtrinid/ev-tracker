from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from calculations import calculate_clv, calculate_close_calibration_metrics

PLAYER_PROP_MODEL_CANDIDATE_SETS_KEY = "_model_candidate_sets"
PLAYER_PROP_MODEL_CANDIDATE_TABLE = "player_prop_model_candidate_observations"
DISPLAYED_DEFAULT_COHORT = "displayed_default"
QUALITY_GATED_COHORT = "quality_gated"


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
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except Exception:
        return None


def _normalize_source(value: str | None) -> str:
    return (value or "unknown").strip() or "unknown"


def _normalize_sportsbook_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _normalize_key_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _line_token(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return ""
    return f"{numeric:g}"


def _opportunity_key_from_player_prop_side(side: dict[str, Any]) -> str:
    event_id = _normalize_key_text(side.get("event_id"))
    commence_time = str(side.get("commence_time") or "").strip()
    event_ref = f"id:{event_id}" if event_id else f"time:{commence_time}"
    return "|".join(
        [
            "player_props",
            _normalize_key_text(side.get("sport")),
            event_ref,
            _normalize_key_text(side.get("market_key") or side.get("market")),
            _normalize_key_text(side.get("player_name")),
            _normalize_key_text(side.get("selection_side")),
            _line_token(side.get("line_value")),
            _normalize_key_text(side.get("sportsbook")),
        ]
    )


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def is_missing_player_prop_model_candidate_observations_error(error: Exception) -> bool:
    msg = str(error)
    message = str(getattr(error, "message", "") or "")
    combined = f"{msg} {message}".lower()
    code = str(getattr(error, "code", "") or "").strip().upper()
    return code == "PGRST205" or (
        PLAYER_PROP_MODEL_CANDIDATE_TABLE in combined and "schema cache" in combined
    )


def candidate_set_key_for_capture(*, source: str, captured_at: str) -> str:
    return f"{_normalize_source(source)}:{captured_at}"


def _candidate_payload(
    *,
    candidate_set_key: str,
    source: str,
    captured_at: str,
    model_key: str,
    side: dict[str, Any],
    rank_overall: int,
    rank_displayed: int | None,
    cohort: str,
) -> dict[str, Any]:
    opportunity_key = _opportunity_key_from_player_prop_side(side)
    market_key = str(side.get("market_key") or side.get("market") or "").strip()
    sportsbook_key = str(side.get("sportsbook_key") or "").strip() or _normalize_sportsbook_key(side.get("sportsbook"))
    return {
        "candidate_set_key": candidate_set_key,
        "source": _normalize_source(source),
        "captured_at": captured_at,
        "model_key": str(model_key or "").strip().lower(),
        "opportunity_key": opportunity_key,
        "rank_overall": rank_overall,
        "rank_displayed": rank_displayed,
        "cohort": cohort,
        "surface": "player_props",
        "sport": str(side.get("sport") or ""),
        "event": str(side.get("event") or ""),
        "event_id": str(side.get("event_id") or "").strip() or None,
        "commence_time": str(side.get("commence_time") or "").strip() or None,
        "sportsbook": str(side.get("sportsbook") or ""),
        "sportsbook_key": sportsbook_key,
        "market": str(side.get("market") or market_key),
        "market_key": market_key,
        "player_name": str(side.get("player_name") or "").strip() or None,
        "participant_id": str(side.get("participant_id") or "").strip() or None,
        "selection_side": str(side.get("selection_side") or "").strip().lower() or None,
        "line_value": _coerce_float(side.get("line_value")),
        "book_odds": _coerce_float(side.get("book_odds")),
        "book_decimal": _coerce_float(side.get("book_decimal")),
        "reference_source": str(side.get("reference_source") or "").strip() or None,
        "reference_odds": _coerce_float(side.get("reference_odds")),
        "true_prob": _coerce_float(side.get("true_prob")),
        "raw_true_prob": _coerce_float(side.get("raw_true_prob")),
        "ev_percentage": _coerce_float(side.get("ev_percentage")),
        "base_kelly_fraction": _coerce_float(side.get("base_kelly_fraction")),
        "confidence_label": str(side.get("confidence_label") or "").strip() or None,
        "confidence_score": _coerce_float(side.get("confidence_score")),
        "prob_std": _coerce_float(side.get("prob_std")),
        "reference_bookmaker_count": _coerce_int(side.get("reference_bookmaker_count")),
        "filtered_reference_count": _coerce_int(side.get("filtered_reference_count")),
        "exact_reference_count": _coerce_int(side.get("exact_reference_count")),
        "interpolated_reference_count": _coerce_int(side.get("interpolated_reference_count")),
        "interpolation_mode": str(side.get("interpolation_mode") or "").strip() or None,
        "reference_bookmakers": list(side.get("reference_bookmakers") or []),
        "reference_inputs_json": _json_value(side.get("reference_inputs_json")),
        "shrink_factor": _coerce_float(side.get("shrink_factor")),
    }


def capture_player_prop_model_candidate_observations(
    db,
    *,
    candidate_sets: dict[str, list[dict[str, Any]]] | None,
    source: str,
    captured_at: str,
) -> dict[str, int]:
    if not isinstance(candidate_sets, dict) or not candidate_sets:
        return {"eligible_seen": 0, "inserted": 0, "updated": 0}

    candidate_set_key = candidate_set_key_for_capture(source=source, captured_at=captured_at)
    payloads: list[dict[str, Any]] = []
    for model_key, sides in candidate_sets.items():
        if not isinstance(sides, list):
            continue
        displayed_rank = 0
        for index, side in enumerate([item for item in sides if isinstance(item, dict)], start=1):
            ev = _coerce_float(side.get("ev_percentage"))
            is_displayed = ev is not None and ev > 1.0
            if is_displayed:
                displayed_rank += 1
            payloads.append(
                _candidate_payload(
                    candidate_set_key=candidate_set_key,
                    source=source,
                    captured_at=captured_at,
                    model_key=model_key,
                    side=side,
                    rank_overall=index,
                    rank_displayed=displayed_rank if is_displayed else None,
                    cohort=DISPLAYED_DEFAULT_COHORT if is_displayed else QUALITY_GATED_COHORT,
                )
            )

    if not payloads:
        return {"eligible_seen": 0, "inserted": 0, "updated": 0}

    try:
        existing = (
            db.table(PLAYER_PROP_MODEL_CANDIDATE_TABLE)
            .select("id,candidate_set_key,model_key,opportunity_key")
            .eq("candidate_set_key", candidate_set_key)
            .execute()
        )
    except Exception as exc:
        if is_missing_player_prop_model_candidate_observations_error(exc):
            return {"eligible_seen": len(payloads), "inserted": 0, "updated": 0}
        raise

    existing_by_key = {
        (
            str(row.get("candidate_set_key") or ""),
            str(row.get("model_key") or "").strip().lower(),
            str(row.get("opportunity_key") or ""),
        ): row
        for row in (existing.data or [])
    }

    inserts: list[dict[str, Any]] = []
    updated = 0
    for payload in payloads:
        key = (
            str(payload["candidate_set_key"]),
            str(payload["model_key"]).strip().lower(),
            str(payload["opportunity_key"]),
        )
        row = existing_by_key.get(key)
        if row is None:
            inserts.append(payload)
            continue
        db.table(PLAYER_PROP_MODEL_CANDIDATE_TABLE).update(payload).eq("id", row["id"]).execute()
        updated += 1

    if inserts:
        db.table(PLAYER_PROP_MODEL_CANDIDATE_TABLE).insert(inserts).execute()

    return {"eligible_seen": len(payloads), "inserted": len(inserts), "updated": updated}


def update_player_prop_model_candidate_observation_close_snapshot(
    db,
    *,
    opportunity_key: str,
    close_reference_odds: float,
    close_opposing_reference_odds: float | None,
    close_captured_at: str,
) -> int:
    try:
        result = (
            db.table(PLAYER_PROP_MODEL_CANDIDATE_TABLE)
            .select("id,true_prob,book_odds")
            .eq("opportunity_key", opportunity_key)
            .execute()
        )
    except Exception as exc:
        if is_missing_player_prop_model_candidate_observations_error(exc):
            return 0
        raise

    clv_base = calculate_clv(close_reference_odds, close_reference_odds, close_opposing_reference_odds)
    close_true_prob = float(clv_base["close_true_prob"])
    updated = 0
    for row in result.data or []:
        book_odds = _coerce_float(row.get("book_odds"))
        if book_odds is None:
            continue
        clv_result = calculate_clv(book_odds, close_reference_odds, close_opposing_reference_odds)
        metrics = calculate_close_calibration_metrics(
            _coerce_float(row.get("true_prob")) or close_true_prob,
            close_true_prob,
        )
        payload = {
            "close_reference_odds": close_reference_odds,
            "close_opposing_reference_odds": close_opposing_reference_odds,
            "close_true_prob": close_true_prob,
            "close_quality": clv_result.get("close_quality"),
            "close_captured_at": close_captured_at,
            "clv_ev_percent": clv_result.get("clv_ev_percent"),
            "beat_close": clv_result.get("beat_close"),
            "brier_score": metrics.get("brier_score"),
            "log_loss": metrics.get("log_loss"),
        }
        db.table(PLAYER_PROP_MODEL_CANDIDATE_TABLE).update(payload).eq("id", row["id"]).execute()
        updated += 1

    return updated
