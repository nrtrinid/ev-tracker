from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from calculations import american_to_decimal
from models import (
    ResearchOpportunityBreakdownItem,
    ResearchOpportunityCohortTrendRow,
    ResearchOpportunityRecentRow,
    ResearchOpportunitySummaryResponse,
)
from services.match_keys import scanner_match_key_from_side
from services.clv_tracking import has_valid_close_snapshot

UNKNOWN_BUCKET = "Unknown"
UNKNOWN_SOURCE_LABEL = "Unknown Source"

MIN_VALID_CLOSE_OVERALL = 10
MIN_VALID_CLOSE_BY_BUCKET = 5

EDGE_BUCKET_ORDER = [UNKNOWN_BUCKET, "0-0.5%", "0.5-1%", "1-2%", "2-4%", "4%+"]
ODDS_BUCKET_ORDER = [UNKNOWN_BUCKET, "<= +150", "+151 to +300", "+301 to +500", "+501+"]
SOURCE_LABEL_ORDER = [
    "Daily Drop (Scheduled)",
    "Daily Drop (Ops Trigger)",
    "Daily Drop (Manual QA)",
    "Daily Drop (Cron)",
    UNKNOWN_SOURCE_LABEL,
]
SURFACE_ORDER = ["straight_bets", "player_props"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_source(value: str | None) -> str:
    return (value or "unknown").strip() or "unknown"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_line_value(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _line_token(value: Any) -> str:
    line_value = _normalize_line_value(value)
    if line_value is None:
        return ""
    return f"{line_value:g}"


def is_missing_scan_opportunities_error(error: Exception) -> bool:
    msg = str(error)
    return "PGRST205" in msg or ("scan_opportunities" in msg and "schema cache" in msg)


def is_missing_scan_opportunity_model_evaluations_error(error: Exception) -> bool:
    msg = str(error)
    return "PGRST205" in msg or ("scan_opportunity_model_evaluations" in msg and "schema cache" in msg)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _price_quality(american: Any) -> float | None:
    odds = _coerce_float(american)
    if odds is None:
        return None
    try:
        return american_to_decimal(odds)
    except Exception:
        return None


def _opportunity_key_from_side(side: dict[str, Any]) -> str:
    surface = _normalize_text(side.get("surface")) or "straight_bets"
    if surface == "player_props":
        sport = _normalize_text(side.get("sport"))
        event_id = _normalize_text(side.get("event_id"))
        commence_time = str(side.get("commence_time") or "").strip()
        event_ref = f"id:{event_id}" if event_id else f"time:{commence_time}"
        market_key = _normalize_text(side.get("market_key"))
        player_name = _normalize_text(side.get("player_name"))
        selection_side = _normalize_text(side.get("selection_side"))
        sportsbook = _normalize_text(side.get("sportsbook"))
        return "|".join(
            [
                "player_props",
                sport,
                event_ref,
                market_key,
                player_name,
                selection_side,
                _line_token(side.get("line_value")),
                sportsbook,
            ]
        )

    sport, event_ref, market, team, sportsbook = scanner_match_key_from_side(side)
    return "|".join(["straight_bets", sport, event_ref, market, team, sportsbook])


def _reference_odds_from_side(side: dict[str, Any]) -> float | None:
    surface = _normalize_text(side.get("surface")) or "straight_bets"
    if surface == "player_props":
        return _coerce_float(side.get("reference_odds"))
    return _coerce_float(side.get("pinnacle_odds"))


def _default_model_key_for_side(side: dict[str, Any]) -> str:
    surface = _normalize_text(side.get("surface")) or "straight_bets"
    if surface == "player_props":
        active = str(side.get("active_model_key") or "").strip().lower()
        return active or "props_v1_live"
    return "straight_h2h_live"


def _normalize_sportsbook_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _model_evaluations_from_side(side: dict[str, Any]) -> list[dict[str, Any]]:
    surface = _normalize_text(side.get("surface")) or "straight_bets"
    if surface != "player_props":
        return []

    evaluations = side.get("model_evaluations")
    if isinstance(evaluations, list):
        normalized = [dict(item) for item in evaluations if isinstance(item, dict) and item.get("model_key")]
        if normalized:
            return normalized

    reference_odds = _reference_odds_from_side(side)
    true_prob = _coerce_float(side.get("true_prob"))
    ev_percentage = _coerce_float(side.get("ev_percentage"))
    if reference_odds is None or true_prob is None or ev_percentage is None:
        return []

    return [
        {
            "model_key": _default_model_key_for_side(side),
            "reference_source": side.get("reference_source"),
            "reference_odds": reference_odds,
            "true_prob": true_prob,
            "raw_true_prob": true_prob,
            "reference_bookmakers": list(side.get("reference_bookmakers") or []),
            "reference_bookmaker_count": int(side.get("reference_bookmaker_count") or 0),
            "filtered_reference_count": int(side.get("reference_bookmaker_count") or 0),
            "exact_reference_count": int(side.get("reference_bookmaker_count") or 0),
            "interpolated_reference_count": 0,
            "interpolation_mode": str(side.get("interpolation_mode") or "exact"),
            "reference_inputs_json": side.get("reference_inputs_json"),
            "confidence_label": side.get("confidence_label"),
            "confidence_score": _coerce_float(side.get("confidence_score")),
            "prob_std": _coerce_float(side.get("prob_std")),
            "book_odds": _coerce_float(side.get("book_odds")),
            "book_decimal": _coerce_float(side.get("book_decimal")),
            "ev_percentage": ev_percentage,
            "base_kelly_fraction": _coerce_float(side.get("base_kelly_fraction")) or 0.0,
            "shrink_factor": _coerce_float(side.get("shrink_factor")) or 0.0,
            "sportsbook_key": _normalize_sportsbook_key(side.get("sportsbook")),
            "market_key": side.get("market_key"),
        }
    ]


def _capture_scan_opportunity_model_evaluations(
    db,
    *,
    collapsed_by_key: dict[str, dict[str, Any]],
    source: str,
    captured_at: str,
) -> None:
    opportunity_keys = list(collapsed_by_key.keys())
    if not opportunity_keys:
        return

    try:
        existing = (
            db.table("scan_opportunity_model_evaluations")
            .select("id,opportunity_key,model_key")
            .in_("opportunity_key", opportunity_keys)
            .execute()
        )
    except Exception as exc:
        if is_missing_scan_opportunity_model_evaluations_error(exc):
            return
        raise

    existing_by_key = {
        (str(row.get("opportunity_key") or ""), str(row.get("model_key") or "").strip().lower()): row
        for row in (existing.data or [])
        if row.get("opportunity_key") and row.get("model_key")
    }
    inserts: list[dict[str, Any]] = []

    for opportunity_key, collapsed in collapsed_by_key.items():
        side = collapsed["side"]
        live_model_key = _default_model_key_for_side(side)
        for evaluation in _model_evaluations_from_side(side):
            model_key = str(evaluation.get("model_key") or "").strip().lower()
            if not model_key:
                continue
            payload = {
                "opportunity_key": opportunity_key,
                "model_key": model_key,
                "capture_role": "live" if model_key == live_model_key else "shadow",
                "surface": str(side.get("surface") or "player_props"),
                "sport": str(side.get("sport") or ""),
                "event": str(side.get("event") or ""),
                "team": str(side.get("team") or ""),
                "sportsbook": str(side.get("sportsbook") or ""),
                "sportsbook_key": str(evaluation.get("sportsbook_key") or _normalize_sportsbook_key(side.get("sportsbook"))),
                "market": str(side.get("market") or side.get("market_key") or ""),
                "event_id": str(side.get("event_id") or "").strip() or None,
                "player_name": str(side.get("player_name") or "").strip() or None,
                "selection_side": str(side.get("selection_side") or "").strip().lower() or None,
                "line_value": _normalize_line_value(side.get("line_value")),
                "reference_source": str(evaluation.get("reference_source") or side.get("reference_source") or ""),
                "first_source": source,
                "last_source": source,
                "first_seen_at": captured_at,
                "last_seen_at": captured_at,
                "first_true_prob": float(evaluation.get("true_prob") or 0.0),
                "last_true_prob": float(evaluation.get("true_prob") or 0.0),
                "first_raw_true_prob": _coerce_float(evaluation.get("raw_true_prob")),
                "last_raw_true_prob": _coerce_float(evaluation.get("raw_true_prob")),
                "first_book_odds": _coerce_float(evaluation.get("book_odds")),
                "last_book_odds": _coerce_float(evaluation.get("book_odds")),
                "first_book_decimal": _coerce_float(evaluation.get("book_decimal")),
                "last_book_decimal": _coerce_float(evaluation.get("book_decimal")),
                "first_reference_odds": float(evaluation.get("reference_odds") or 0.0),
                "last_reference_odds": float(evaluation.get("reference_odds") or 0.0),
                "first_ev_percentage": float(evaluation.get("ev_percentage") or 0.0),
                "last_ev_percentage": float(evaluation.get("ev_percentage") or 0.0),
                "first_confidence_score": _coerce_float(evaluation.get("confidence_score")),
                "last_confidence_score": _coerce_float(evaluation.get("confidence_score")),
                "first_confidence_label": str(evaluation.get("confidence_label") or ""),
                "last_confidence_label": str(evaluation.get("confidence_label") or ""),
                "first_reference_bookmaker_count": int(evaluation.get("reference_bookmaker_count") or 0),
                "last_reference_bookmaker_count": int(evaluation.get("reference_bookmaker_count") or 0),
                "first_interpolation_mode": str(evaluation.get("interpolation_mode") or "exact"),
                "last_interpolation_mode": str(evaluation.get("interpolation_mode") or "exact"),
                "first_reference_inputs_json": evaluation.get("reference_inputs_json"),
                "last_reference_inputs_json": evaluation.get("reference_inputs_json"),
                "first_prob_std": _coerce_float(evaluation.get("prob_std")),
                "last_prob_std": _coerce_float(evaluation.get("prob_std")),
                "first_shrink_factor": _coerce_float(evaluation.get("shrink_factor")),
                "last_shrink_factor": _coerce_float(evaluation.get("shrink_factor")),
                "close_reference_odds": None,
                "close_opposing_reference_odds": None,
                "close_true_prob": None,
                "close_quality": None,
                "close_captured_at": None,
                "first_clv_ev_percent": None,
                "last_clv_ev_percent": None,
                "first_beat_close": None,
                "last_beat_close": None,
                "first_brier_score": None,
                "last_brier_score": None,
                "first_log_loss": None,
                "last_log_loss": None,
            }
            existing_row = existing_by_key.get((opportunity_key, model_key))
            if existing_row is None:
                inserts.append(payload)
                continue

            update_payload = {
                "capture_role": payload["capture_role"],
                "surface": payload["surface"],
                "sport": payload["sport"],
                "event": payload["event"],
                "team": payload["team"],
                "sportsbook": payload["sportsbook"],
                "sportsbook_key": payload["sportsbook_key"],
                "market": payload["market"],
                "event_id": payload["event_id"],
                "player_name": payload["player_name"],
                "selection_side": payload["selection_side"],
                "line_value": payload["line_value"],
                "reference_source": payload["reference_source"],
                "last_source": source,
                "last_seen_at": captured_at,
                "last_true_prob": payload["last_true_prob"],
                "last_raw_true_prob": payload["last_raw_true_prob"],
                "last_book_odds": payload["last_book_odds"],
                "last_book_decimal": payload["last_book_decimal"],
                "last_reference_odds": payload["last_reference_odds"],
                "last_ev_percentage": payload["last_ev_percentage"],
                "last_confidence_score": payload["last_confidence_score"],
                "last_confidence_label": payload["last_confidence_label"],
                "last_reference_bookmaker_count": payload["last_reference_bookmaker_count"],
                "last_interpolation_mode": payload["last_interpolation_mode"],
                "last_reference_inputs_json": payload["last_reference_inputs_json"],
                "last_prob_std": payload["last_prob_std"],
                "last_shrink_factor": payload["last_shrink_factor"],
            }
            db.table("scan_opportunity_model_evaluations").update(update_payload).eq("id", existing_row["id"]).execute()

    if inserts:
        db.table("scan_opportunity_model_evaluations").insert(inserts).execute()


def is_research_capture_candidate(side: dict[str, Any]) -> bool:
    surface = str(side.get("surface") or "straight_bets").strip().lower()
    if surface == "straight_bets":
        if str(side.get("market_key") or "h2h").strip().lower() != "h2h":
            return False
    elif surface == "player_props":
        if not _normalize_text(side.get("player_name")):
            return False
        if not _normalize_text(side.get("market_key")):
            return False
        if not _normalize_text(side.get("selection_side")):
            return False
        if _normalize_line_value(side.get("line_value")) is None:
            return False
    else:
        return False

    ev = _coerce_float(side.get("ev_percentage"))
    book_odds = _coerce_float(side.get("book_odds"))
    ref_odds = _reference_odds_from_side(side)
    if ev is None or ev <= 0:
        return False
    if book_odds is None or ref_odds is None:
        return False
    return True


def capture_scan_opportunities(
    db,
    *,
    sides: list[dict[str, Any]],
    source: str,
    captured_at: str,
) -> dict[str, int]:
    eligible = [side for side in sides if is_research_capture_candidate(side)]
    if not eligible:
        return {"eligible_seen": 0, "inserted": 0, "updated": 0}

    collapsed_by_key: dict[str, dict[str, Any]] = {}
    for side in eligible:
        opportunity_key = _opportunity_key_from_side(side)
        book_odds = float(side["book_odds"])
        ref_odds = float(_reference_odds_from_side(side) or 0)
        ev_percentage = float(side["ev_percentage"])
        current_quality = _price_quality(book_odds)
        existing = collapsed_by_key.get(opportunity_key)
        if existing is None:
            collapsed_by_key[opportunity_key] = {
                "side": dict(side),
                "book_odds": book_odds,
                "ref_odds": ref_odds,
                "ev_percentage": ev_percentage,
                "best_book_odds": book_odds,
                "best_reference_odds": ref_odds,
                "best_ev_percentage": ev_percentage,
                "best_quality": current_quality,
            }
            continue

        existing["side"] = dict(side)
        existing["book_odds"] = book_odds
        existing["ref_odds"] = ref_odds
        existing["ev_percentage"] = ev_percentage
        best_quality = existing.get("best_quality")
        if current_quality is not None and (best_quality is None or current_quality > best_quality):
            existing["best_book_odds"] = book_odds
            existing["best_reference_odds"] = ref_odds
            existing["best_ev_percentage"] = ev_percentage
            existing["best_quality"] = current_quality

    normalized_source = _normalize_source(source)
    opportunity_keys = list(collapsed_by_key.keys())
    existing_res = (
        db.table("scan_opportunities")
        .select(
            "id,opportunity_key,seen_count,best_book_odds,event,commence_time,team,sportsbook,event_id,"
            "surface,market,player_name,source_market_key,selection_side,line_value,first_model_key,last_model_key"
        )
        .in_("opportunity_key", opportunity_keys)
        .execute()
    )
    existing_by_key = {
        str(row.get("opportunity_key") or ""): row
        for row in (existing_res.data or [])
        if row.get("opportunity_key")
    }

    insert_payloads: list[dict[str, Any]] = []
    updated = 0

    for opportunity_key, collapsed in collapsed_by_key.items():
        side = collapsed["side"]
        book_odds = float(collapsed["book_odds"])
        ref_odds = float(collapsed["ref_odds"])
        ev_percentage = float(collapsed["ev_percentage"])
        surface = str(side.get("surface") or "straight_bets").strip().lower() or "straight_bets"
        event_id = str(side.get("event_id") or "").strip() or None
        player_name = str(side.get("player_name") or "").strip() or None
        source_market_key = str(side.get("market_key") or "").strip() or None
        selection_side = str(side.get("selection_side") or "").strip().lower() or None
        line_value = _normalize_line_value(side.get("line_value"))
        live_model_key = _default_model_key_for_side(side)
        row = existing_by_key.get(opportunity_key)

        if row is None:
            insert_payloads.append(
                {
                    "opportunity_key": opportunity_key,
                    "surface": surface,
                    "sport": str(side.get("sport") or ""),
                    "event": str(side.get("event") or ""),
                    "commence_time": str(side.get("commence_time") or ""),
                    "team": str(side.get("team") or ""),
                    "sportsbook": str(side.get("sportsbook") or ""),
                    "market": "ML" if surface == "straight_bets" else str(side.get("market") or source_market_key or ""),
                    "event_id": event_id,
                    "player_name": player_name,
                    "source_market_key": source_market_key,
                    "selection_side": selection_side,
                    "line_value": line_value,
                    "first_source": normalized_source,
                    "last_source": normalized_source,
                    "first_model_key": live_model_key,
                    "last_model_key": live_model_key,
                    "seen_count": 1,
                    "first_seen_at": captured_at,
                    "last_seen_at": captured_at,
                    "best_seen_at": captured_at,
                    "first_book_odds": book_odds,
                    "last_book_odds": book_odds,
                    "best_book_odds": float(collapsed["best_book_odds"]),
                    "first_reference_odds": ref_odds,
                    "last_reference_odds": ref_odds,
                    "best_reference_odds": float(collapsed["best_reference_odds"]),
                    "first_ev_percentage": ev_percentage,
                    "last_ev_percentage": ev_percentage,
                    "best_ev_percentage": float(collapsed["best_ev_percentage"]),
                    "latest_reference_odds": ref_odds,
                    "latest_reference_updated_at": captured_at,
                    "reference_odds_at_close": None,
                    "close_captured_at": None,
                    "clv_ev_percent": None,
                    "beat_close": None,
                }
            )
            continue

        best_book_odds = _coerce_float(row.get("best_book_odds"))
        batch_best_quality = collapsed.get("best_quality")
        best_quality = _price_quality(best_book_odds)
        payload = {
            "surface": surface,
            "event": str(side.get("event") or row.get("event") or ""),
            "commence_time": str(side.get("commence_time") or row.get("commence_time") or ""),
            "team": str(side.get("team") or row.get("team") or ""),
            "sportsbook": str(side.get("sportsbook") or row.get("sportsbook") or ""),
            "market": "ML" if surface == "straight_bets" else str(side.get("market") or row.get("market") or source_market_key or ""),
            "event_id": event_id or row.get("event_id"),
            "player_name": player_name or row.get("player_name"),
            "source_market_key": source_market_key or row.get("source_market_key"),
            "selection_side": selection_side or row.get("selection_side"),
            "line_value": line_value if line_value is not None else row.get("line_value"),
            "last_source": normalized_source,
            "first_model_key": row.get("first_model_key") or live_model_key,
            "last_model_key": live_model_key,
            "seen_count": int(row.get("seen_count") or 0) + 1,
            "last_seen_at": captured_at,
            "last_book_odds": book_odds,
            "last_reference_odds": ref_odds,
            "last_ev_percentage": ev_percentage,
            "latest_reference_odds": ref_odds,
            "latest_reference_updated_at": captured_at,
        }
        if batch_best_quality is not None and (best_quality is None or batch_best_quality > best_quality):
            payload.update(
                {
                    "best_seen_at": captured_at,
                    "best_book_odds": float(collapsed["best_book_odds"]),
                    "best_reference_odds": float(collapsed["best_reference_odds"]),
                    "best_ev_percentage": float(collapsed["best_ev_percentage"]),
                }
            )

        db.table("scan_opportunities").update(payload).eq("id", row["id"]).execute()
        updated += 1

    if insert_payloads:
        db.table("scan_opportunities").insert(insert_payloads).execute()

    _capture_scan_opportunity_model_evaluations(
        db,
        collapsed_by_key=collapsed_by_key,
        source=normalized_source,
        captured_at=captured_at,
    )

    return {
        "eligible_seen": len(eligible),
        "inserted": len(insert_payloads),
        "updated": updated,
    }


def empty_research_opportunities_summary() -> ResearchOpportunitySummaryResponse:
    return ResearchOpportunitySummaryResponse(
        captured_count=0,
        open_count=0,
        close_captured_count=0,
        pending_close_count=0,
        valid_close_count=0,
        invalid_close_count=0,
        valid_close_coverage_pct=None,
        invalid_close_rate_pct=None,
        clv_ready_count=0,
        beat_close_pct=None,
        avg_clv_percent=None,
        by_surface=[],
        by_source=[],
        by_sportsbook=[],
        by_edge_bucket=[],
        by_odds_bucket=[],
        recent_opportunities=[],
    )


def _edge_bucket(ev_percentage: float | None) -> str:
    if ev_percentage is None:
        return UNKNOWN_BUCKET
    value = ev_percentage
    if value < 0.5:
        return "0-0.5%"
    if value < 1.0:
        return "0.5-1%"
    if value < 2.0:
        return "1-2%"
    if value < 4.0:
        return "2-4%"
    return "4%+"


def _odds_bucket(book_odds: float | None) -> str:
    if book_odds is None:
        return UNKNOWN_BUCKET
    value = book_odds
    if value <= 150:
        return "<= +150"
    if value <= 300:
        return "+151 to +300"
    if value <= 500:
        return "+301 to +500"
    return "+501+"


def _aggregate_breakdown(
    rows: list[dict[str, Any]],
    *,
    key_fn,
    preferred_order: list[str] | None = None,
) -> list[ResearchOpportunityBreakdownItem]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)

    preferred_position = {key: index for index, key in enumerate(preferred_order or [])}
    items: list[ResearchOpportunityBreakdownItem] = []
    for key, bucket_rows in groups.items():
        valid_close_rows = [row for row in bucket_rows if row.get("_close_status") == "valid"]
        valid_close_count = len(valid_close_rows)

        beat_close_count = sum(1 for row in valid_close_rows if row.get("beat_close") is True)
        avg_clv = None
        if valid_close_count >= MIN_VALID_CLOSE_BY_BUCKET:
            avg_clv = round(
                sum(float(row["clv_ev_percent"]) for row in valid_close_rows)
                / valid_close_count,
                2,
            )

        beat_close_pct = None
        if valid_close_count >= MIN_VALID_CLOSE_BY_BUCKET:
            beat_close_pct = round((beat_close_count / valid_close_count) * 100, 2)
        items.append(
            ResearchOpportunityBreakdownItem(
                key=key,
                captured_count=len(bucket_rows),
                clv_ready_count=valid_close_count,
                valid_close_count=valid_close_count,
                beat_close_pct=beat_close_pct,
                avg_clv_percent=avg_clv,
            )
        )

    items.sort(
        key=lambda item: (
            preferred_position.get(item.key, len(preferred_position)),
            -item.captured_count,
            item.key,
        )
    )
    return items


def get_research_opportunities_summary(
    db,
    *,
    model_version: str | None = None,
    capture_class: str | None = None,
    cohort_mode: str | None = None,
) -> ResearchOpportunitySummaryResponse:
    normalized_model_version = (model_version or "").strip().lower()
    if not normalized_model_version or normalized_model_version == "all":
        normalized_model_version = None

    normalized_capture_class = (capture_class or "").strip().lower()
    if not normalized_capture_class or normalized_capture_class == "all":
        normalized_capture_class = None
    if normalized_capture_class not in {"live", "experiment"}:
        normalized_capture_class = None

    normalized_cohort_mode = (cohort_mode or "").strip().lower()
    selected_cohort_mode: str | None = None
    trailing_n = 7
    if not normalized_cohort_mode or normalized_cohort_mode == "all":
        selected_cohort_mode = None
    elif normalized_cohort_mode == "latest":
        selected_cohort_mode = "latest"
    elif normalized_cohort_mode.startswith("trailing_"):
        maybe_n = normalized_cohort_mode.split("_", 1)[1]
        try:
            parsed_n = int(maybe_n)
            if parsed_n >= 1:
                selected_cohort_mode = "trailing"
                trailing_n = parsed_n
        except Exception:
            selected_cohort_mode = None
    else:
        selected_cohort_mode = None

    def _derive_model_version(source: str | None) -> str:
        s = (source or "").strip().lower()
        # Daily board drops are the "current" pipeline.
        if s in {"scheduled_board_drop", "ops_trigger_board_drop", "cron_board_drop", "scheduled_board_drop_early_look"}:
            return "current"
        if s.startswith("scheduled_board_drop"):
            return "current"

        # Legacy EV scanner captures.
        if s in {"manual_scan", "scheduled_scan", "ops_trigger_scan"}:
            return "legacy"

        return "legacy"

    def _derive_capture_class(source: str | None) -> str:
        s = (source or "").strip().lower()
        # Manual scans are treated as operator-led QA/experiments.
        if s == "manual_scan":
            return "experiment"
        return "live"

    def _derive_live_model_key(row: dict[str, Any]) -> str:
        explicit = (
            str(row.get("first_model_key") or "").strip().lower()
            or str(row.get("last_model_key") or "").strip().lower()
        )
        if explicit:
            return explicit
        surface = str(row.get("surface") or "straight_bets").strip().lower()
        if surface == "player_props":
            return "props_v1_live"
        return "straight_h2h_live"

    def _map_product_source_label(source: str | None) -> str:
        s = (source or "").strip().lower()
        if s in {"scheduled_scan"} or s.startswith("scheduled_board_drop"):
            return "Daily Drop (Scheduled)"
        if s in {"ops_trigger_scan", "ops_trigger_board_drop"}:
            return "Daily Drop (Ops Trigger)"
        if s in {"manual_scan"}:
            return "Daily Drop (Manual QA)"
        if s in {"cron_board_drop"}:
            return "Daily Drop (Cron)"
        return UNKNOWN_SOURCE_LABEL

    def _classify_close_status(row: dict[str, Any]) -> str:
        reference_at_close = _coerce_float(row.get("reference_odds_at_close"))
        if reference_at_close is None:
            return "pending"

        commence_time = row.get("commence_time")
        captured_at = row.get("close_captured_at")
        if not commence_time or not captured_at:
            return "invalid"

        if not has_valid_close_snapshot(commence_time, captured_at):
            return "invalid"

        clv_ev_percent = _coerce_float(row.get("clv_ev_percent"))
        beat_close = row.get("beat_close")
        # A valid close should always have a CLV result; if it doesn't, we treat it as invalid for reporting.
        if clv_ev_percent is None or beat_close is None:
            return "invalid"

        return "valid"

    try:
        res = (
            db.table("scan_opportunities")
            .select(
                "opportunity_key,surface,first_seen_at,last_seen_at,commence_time,sport,event,team,sportsbook,market,event_id,"
                "player_name,source_market_key,selection_side,line_value,"
                "first_source,last_source,first_model_key,last_model_key,seen_count,first_ev_percentage,first_book_odds,best_book_odds,"
                "latest_reference_odds,reference_odds_at_close,close_captured_at,clv_ev_percent,beat_close"
            )
            .execute()
        )
    except Exception as e:
        if is_missing_scan_opportunities_error(e):
            return empty_research_opportunities_summary()
        raise
    rows = list(res.data or [])

    # Derive close semantics once so all summary/breakdown calculations are consistent.
    for row in rows:
        row["_close_status"] = _classify_close_status(row)
        raw_source = row.get("first_source") or row.get("last_source") or "unknown"
        row["_model_version"] = _derive_model_version(raw_source)
        row["_capture_class"] = _derive_capture_class(raw_source)
        row["_live_model_key"] = _derive_live_model_key(row)
        row["_product_source_label"] = _map_product_source_label(raw_source)

    if normalized_model_version is not None:
        if normalized_model_version in {"current", "legacy"}:
            rows = [row for row in rows if row.get("_model_version") == normalized_model_version]
        else:
            rows = [row for row in rows if row.get("_live_model_key") == normalized_model_version]

    if normalized_capture_class is not None:
        rows = [row for row in rows if row.get("_capture_class") == normalized_capture_class]

    cohort_trend: list[ResearchOpportunityCohortTrendRow] = []
    selected_cohort_key: str | None = None

    # Cohorts are derived from the entry timestamp (first_seen_at) date in UTC.
    for row in rows:
        first_seen_dt = _coerce_datetime(row.get("first_seen_at"))
        if first_seen_dt is None:
            row["_cohort_key"] = "unknown"
            row["_cohort_date"] = None
        else:
            row["_cohort_date"] = first_seen_dt.date()
            row["_cohort_key"] = first_seen_dt.date().isoformat()

    known_dates = sorted({row.get("_cohort_date") for row in rows if row.get("_cohort_date") is not None})
    cohort_keys_sorted = [d.isoformat() for d in known_dates]

    if cohort_keys_sorted:
        latest_key = cohort_keys_sorted[-1]
        trend_keys = cohort_keys_sorted[-trailing_n:] if trailing_n > 0 else cohort_keys_sorted

        if selected_cohort_mode == "latest":
            selected_cohort_keys = {latest_key}
            selected_cohort_key = latest_key
        elif selected_cohort_mode == "trailing":
            selected_cohort_keys = set(cohort_keys_sorted[-trailing_n:])
            selected_cohort_key = f"trailing_{trailing_n}"
        else:
            selected_cohort_keys = None

        rows_for_trend = [row for row in rows if row.get("_cohort_key") in set(trend_keys)]
        rows_for_summary = rows if selected_cohort_keys is None else [row for row in rows if row.get("_cohort_key") in selected_cohort_keys]

        for key in trend_keys:
            bucket_rows = [row for row in rows_for_trend if row.get("_cohort_key") == key]
            valid_bucket_rows = [row for row in bucket_rows if row.get("_close_status") == "valid"]
            valid_bucket_count = len(valid_bucket_rows)
            beat_close_count = sum(1 for row in valid_bucket_rows if row.get("beat_close") is True)

            beat_close_pct = None
            avg_clv_percent = None
            if valid_bucket_count >= MIN_VALID_CLOSE_OVERALL:
                beat_close_pct = round((beat_close_count / valid_bucket_count) * 100, 2)
                avg_clv_percent = round(
                    sum(float(row["clv_ev_percent"]) for row in valid_bucket_rows) / valid_bucket_count,
                    2,
                )

            cohort_trend.append(
                ResearchOpportunityCohortTrendRow(
                    cohort_key=key,
                    captured_count=len(bucket_rows),
                    valid_close_count=valid_bucket_count,
                    beat_close_pct=beat_close_pct,
                    avg_clv_percent=avg_clv_percent,
                )
            )

        rows = rows_for_summary
    else:
        rows_for_trend = []

    captured_count = len(rows)
    pending_close_count = sum(1 for row in rows if row.get("_close_status") == "pending")
    valid_close_count = sum(1 for row in rows if row.get("_close_status") == "valid")
    invalid_close_count = sum(1 for row in rows if row.get("_close_status") == "invalid")

    # Beat-close and avg CLV are only meaningful when there are enough valid-close samples.
    valid_rows = [row for row in rows if row.get("_close_status") == "valid"]
    beat_close_count = sum(1 for row in valid_rows if row.get("beat_close") is True)

    beat_close_pct = None
    avg_clv_percent = None
    if valid_close_count >= MIN_VALID_CLOSE_OVERALL:
        beat_close_pct = round((beat_close_count / valid_close_count) * 100, 2)
        avg_clv_percent = round(
            sum(float(row["clv_ev_percent"]) for row in valid_rows) / valid_close_count,
            2,
        )

    valid_close_coverage_pct = None
    invalid_close_rate_pct = None
    close_captured_count = valid_close_count + invalid_close_count
    if captured_count > 0:
        valid_close_coverage_pct = round((valid_close_count / captured_count) * 100, 2)
    if close_captured_count > 0:
        invalid_close_rate_pct = round((invalid_close_count / close_captured_count) * 100, 2)

    recent_rows = sorted(
        rows,
        key=lambda row: _coerce_datetime(row.get("first_seen_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:15]

    recent = [
        ResearchOpportunityRecentRow(
            opportunity_key=str(row.get("opportunity_key") or ""),
            surface=str(row.get("surface") or "straight_bets"),
            first_seen_at=_coerce_datetime(row.get("first_seen_at")) or _utc_now(),
            last_seen_at=_coerce_datetime(row.get("last_seen_at")) or _utc_now(),
            commence_time=str(row.get("commence_time") or ""),
            sport=str(row.get("sport") or ""),
            event=str(row.get("event") or ""),
            team=str(row.get("team") or ""),
            sportsbook=str(row.get("sportsbook") or ""),
            market=str(row.get("market") or "ML"),
            event_id=str(row.get("event_id") or "").strip() or None,
            player_name=str(row.get("player_name") or "").strip() or None,
            source_market_key=str(row.get("source_market_key") or "").strip() or None,
            selection_side=str(row.get("selection_side") or "").strip() or None,
            line_value=_coerce_float(row.get("line_value")),
            first_source=str(row.get("_product_source_label") or row.get("first_source") or "unknown"),
            seen_count=int(row.get("seen_count") or 0),
            first_ev_percentage=float(row.get("first_ev_percentage") or 0),
            first_book_odds=float(row.get("first_book_odds") or 0),
            best_book_odds=float(row.get("best_book_odds") or 0),
            latest_reference_odds=_coerce_float(row.get("latest_reference_odds")),
            reference_odds_at_close=_coerce_float(row.get("reference_odds_at_close")),
            clv_ev_percent=_coerce_float(row.get("clv_ev_percent")),
            beat_close=row.get("beat_close"),
            close_status=str(row.get("_close_status") or "pending"),
        )
        for row in recent_rows
    ]

    return ResearchOpportunitySummaryResponse(
        captured_count=captured_count,
        open_count=pending_close_count,
        close_captured_count=close_captured_count,
        pending_close_count=pending_close_count,
        valid_close_count=valid_close_count,
        invalid_close_count=invalid_close_count,
        valid_close_coverage_pct=valid_close_coverage_pct,
        invalid_close_rate_pct=invalid_close_rate_pct,
        selected_cohort_key=selected_cohort_key,
        cohort_trend=cohort_trend,
        clv_ready_count=valid_close_count,
        beat_close_pct=beat_close_pct,
        avg_clv_percent=avg_clv_percent,
        by_surface=_aggregate_breakdown(
            rows,
            key_fn=lambda row: row.get("surface") or "straight_bets",
            preferred_order=SURFACE_ORDER,
        ),
        by_source=_aggregate_breakdown(
            rows,
            key_fn=lambda row: row.get("_product_source_label") or UNKNOWN_SOURCE_LABEL,
            preferred_order=SOURCE_LABEL_ORDER,
        ),
        by_sportsbook=_aggregate_breakdown(rows, key_fn=lambda row: row.get("sportsbook") or "Unknown"),
        by_edge_bucket=_aggregate_breakdown(
            rows,
            key_fn=lambda row: _edge_bucket(_coerce_float(row.get("first_ev_percentage"))),
            preferred_order=EDGE_BUCKET_ORDER,
        ),
        by_odds_bucket=_aggregate_breakdown(
            rows,
            key_fn=lambda row: _odds_bucket(_coerce_float(row.get("first_book_odds"))),
            preferred_order=ODDS_BUCKET_ORDER,
        ),
        recent_opportunities=recent,
    )
