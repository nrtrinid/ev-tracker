from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from calculations import american_to_decimal, calculate_clv, decimal_to_american
from models import (
    PickEmResearchBreakdownItem,
    PickEmResearchRecentRow,
    PickEmResearchSummaryResponse,
)

OBSERVATION_KIND = "board_pickem_consensus"
EV_BASIS_BEST_MARKET = "best_market_price"
EV_BASIS_UNPRICED = "unpriced"
OBSERVATION_QUERY_CHUNK_SIZE = 200

PROBABILITY_BUCKET_ORDER = ["50-55%", "55-60%", "60-65%", "65-70%", "70%+", "Unknown"]
BOOKS_MATCHED_BUCKET_ORDER = ["1 book", "2 books", "3 books", "4+ books", "Unknown"]
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


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _pickem_auto_settle_supported(sport: Any, market_key: Any) -> bool:
    from services.prop_settler import is_auto_settle_supported_prop_market

    return is_auto_settle_supported_prop_market(
        _normalize_text(sport),
        str(market_key or "").strip(),
    )


def _pickem_manual_result_required(sport: Any, market_key: Any) -> bool:
    normalized = _normalize_text(sport)
    return bool(normalized) and not _pickem_auto_settle_supported(normalized, market_key)


def _parse_actual_result(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized in {"win", "loss", "push"}:
        return normalized
    return None


def _fair_odds_american(probability: float | None) -> float | None:
    if probability is None or not (0 < probability < 1):
        return None
    try:
        return float(decimal_to_american(1 / probability))
    except Exception:
        return None


def _projected_edge_pct(probability: float | None, market_odds: float | None) -> float | None:
    if probability is None or market_odds is None or not (0 < probability < 1):
        return None
    try:
        market_decimal = american_to_decimal(float(market_odds))
    except Exception:
        return None
    return round(((probability * market_decimal) - 1.0) * 100, 2)


def _chunked(values: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        return [values]
    return [values[index:index + size] for index in range(0, len(values), size)]


def _probability_bucket(probability: float | None) -> str:
    if probability is None:
        return "Unknown"
    pct = probability * 100
    if pct < 55:
        return "50-55%"
    if pct < 60:
        return "55-60%"
    if pct < 65:
        return "60-65%"
    if pct < 70:
        return "65-70%"
    return "70%+"


def _books_matched_bucket(count: int | None) -> str:
    if count is None or count <= 0:
        return "Unknown"
    if count >= 4:
        return "4+ books"
    return f"{count} book" if count == 1 else f"{count} books"


def _observation_key_from_card(card: dict[str, Any], *, captured_at: str) -> str | None:
    comparison_key = str(card.get("comparison_key") or "").strip()
    consensus_side = _normalize_text(card.get("consensus_side"))
    captured_dt = _coerce_datetime(captured_at) or _utc_now()
    if not comparison_key or consensus_side not in {"over", "under"}:
        return None
    return "|".join([OBSERVATION_KIND, captured_dt.date().isoformat(), comparison_key, consensus_side])


def _selected_market_from_card(card: dict[str, Any]) -> tuple[str | None, float | None]:
    side = _normalize_text(card.get("consensus_side"))
    if side == "over":
        return (
            str(card.get("best_over_sportsbook") or "").strip() or None,
            _coerce_float(card.get("best_over_odds")),
        )
    if side == "under":
        return (
            str(card.get("best_under_sportsbook") or "").strip() or None,
            _coerce_float(card.get("best_under_odds")),
        )
    return (None, None)


def is_missing_pickem_research_observations_error(error: Exception) -> bool:
    msg = str(error)
    message = str(getattr(error, "message", "") or "")
    combined = f"{msg} {message}".lower()
    code = str(getattr(error, "code", "") or "").strip().upper()
    return (
        code == "PGRST205"
        or ("pickem_research_observations" in combined and "schema cache" in combined)
        or "unexpected table: pickem_research_observations" in combined
    )


def _binary_calibration_metrics(predicted_prob: float | None, actual_result: str | None) -> tuple[float | None, float | None]:
    if predicted_prob is None or actual_result not in {"win", "loss"}:
        return (None, None)
    if not (0 < predicted_prob < 1):
        return (None, None)
    target = 1.0 if actual_result == "win" else 0.0
    clipped = min(max(predicted_prob, 1e-6), 1 - 1e-6)
    brier = (clipped - target) ** 2
    log_loss = -(target * math.log(clipped) + (1 - target) * math.log(1 - clipped))
    return (round(brier, 6), round(log_loss, 6))


def empty_pickem_research_summary() -> PickEmResearchSummaryResponse:
    return PickEmResearchSummaryResponse(
        captured_count=0,
        close_ready_count=0,
        settled_count=0,
        decisive_count=0,
        push_count=0,
        pending_result_count=0,
        auto_settle_pending_count=0,
        manual_result_count=0,
        manual_only_sports=[],
        avg_display_probability_pct=None,
        expected_hit_rate_pct=None,
        actual_hit_rate_pct=None,
        hit_rate_delta_pct_points=None,
        avg_close_probability_pct=None,
        avg_close_drift_pct_points=None,
        avg_close_edge_pct=None,
        avg_brier_score=None,
        avg_log_loss=None,
        by_probability_bucket=[],
        by_market=[],
        by_books_matched=[],
        by_ev_basis=[],
        recent_observations=[],
    )


def capture_pickem_research_observations(
    db,
    *,
    cards: list[dict[str, Any]],
    source: str,
    captured_at: str,
) -> dict[str, int]:
    if not cards:
        return {"eligible_seen": 0, "inserted": 0, "updated": 0}

    normalized_source = str(source or "").strip() or "unknown"
    prepared: list[tuple[str, dict[str, Any]]] = []

    for card in cards:
        if not isinstance(card, dict):
            continue
        observation_key = _observation_key_from_card(card, captured_at=captured_at)
        if not observation_key:
            continue
        consensus_side = _normalize_text(card.get("consensus_side"))
        probability = _coerce_float(
            card.get("consensus_over_prob") if consensus_side == "over" else card.get("consensus_under_prob")
        )
        line_value = _coerce_float(card.get("line_value"))
        if probability is None or line_value is None:
            continue
        selected_sportsbook, selected_market_odds = _selected_market_from_card(card)
        fair_odds = _fair_odds_american(probability)
        projected_edge_pct = _projected_edge_pct(probability, selected_market_odds)
        prepared.append(
            (
                observation_key,
                {
                    "comparison_key": str(card.get("comparison_key") or "").strip(),
                    "observation_kind": OBSERVATION_KIND,
                    "surface": "player_props",
                    "sport": str(card.get("sport") or ""),
                    "event": str(card.get("event") or ""),
                    "commence_time": str(card.get("commence_time") or ""),
                    "market": str(card.get("market") or card.get("market_key") or ""),
                    "market_key": str(card.get("market_key") or ""),
                    "event_id": str(card.get("event_id") or "").strip() or None,
                    "player_name": str(card.get("player_name") or "").strip(),
                    "team": str(card.get("team") or "").strip() or None,
                    "opponent": str(card.get("opponent") or "").strip() or None,
                    "selection_side": consensus_side,
                    "line_value": line_value,
                    "calibration_bucket": _probability_bucket(probability),
                    "first_source": normalized_source,
                    "last_source": normalized_source,
                    "first_seen_at": captured_at,
                    "last_seen_at": captured_at,
                    "first_display_probability": probability,
                    "last_display_probability": probability,
                    "first_fair_odds_american": fair_odds,
                    "last_fair_odds_american": fair_odds,
                    "first_books_matched_count": int(card.get("exact_line_bookmaker_count") or 0),
                    "last_books_matched_count": int(card.get("exact_line_bookmaker_count") or 0),
                    "first_confidence_label": str(card.get("confidence_label") or "").strip() or None,
                    "last_confidence_label": str(card.get("confidence_label") or "").strip() or None,
                    "ev_basis": EV_BASIS_BEST_MARKET if selected_market_odds is not None else EV_BASIS_UNPRICED,
                    "first_selected_sportsbook": selected_sportsbook,
                    "last_selected_sportsbook": selected_sportsbook,
                    "first_selected_market_odds": selected_market_odds,
                    "last_selected_market_odds": selected_market_odds,
                    "first_projected_edge_pct": projected_edge_pct,
                    "last_projected_edge_pct": projected_edge_pct,
                },
            )
        )

    if not prepared:
        return {"eligible_seen": 0, "inserted": 0, "updated": 0}

    observation_keys = [observation_key for observation_key, _payload in prepared]
    existing_rows: list[dict[str, Any]] = []
    try:
        for key_chunk in _chunked(observation_keys, OBSERVATION_QUERY_CHUNK_SIZE):
            existing = (
                db.table("pickem_research_observations")
                .select("id,observation_key,surfaced_count")
                .in_("observation_key", key_chunk)
                .execute()
            )
            existing_rows.extend(existing.data or [])
    except Exception as exc:
        if is_missing_pickem_research_observations_error(exc):
            return {"eligible_seen": len(prepared), "inserted": 0, "updated": 0}
        raise

    existing_by_key = {
        str(row.get("observation_key") or ""): row
        for row in existing_rows
        if row.get("observation_key")
    }

    inserts: list[dict[str, Any]] = []
    updated = 0

    for observation_key, payload in prepared:
        existing_row = existing_by_key.get(observation_key)
        if existing_row is None:
            inserts.append(
                {
                    "observation_key": observation_key,
                    "surfaced_count": 1,
                    "latest_reference_odds": None,
                    "latest_reference_updated_at": None,
                    "close_reference_odds": None,
                    "close_opposing_reference_odds": None,
                    "close_true_prob": None,
                    "close_quality": None,
                    "close_captured_at": None,
                    "close_edge_pct": None,
                    "actual_result": None,
                    "settled_at": None,
                    **payload,
                }
            )
            continue

        updated += 1
        db.table("pickem_research_observations").update(
            {
                "last_source": payload["last_source"],
                "last_seen_at": payload["last_seen_at"],
                "last_display_probability": payload["last_display_probability"],
                "last_fair_odds_american": payload["last_fair_odds_american"],
                "last_books_matched_count": payload["last_books_matched_count"],
                "last_confidence_label": payload["last_confidence_label"],
                "last_selected_sportsbook": payload["last_selected_sportsbook"],
                "last_selected_market_odds": payload["last_selected_market_odds"],
                "last_projected_edge_pct": payload["last_projected_edge_pct"],
                "ev_basis": payload["ev_basis"],
                "surfaced_count": int(existing_row.get("surfaced_count") or 0) + 1,
            }
        ).eq("id", existing_row["id"]).execute()

    if inserts:
        for insert_chunk in _chunked(inserts, OBSERVATION_QUERY_CHUNK_SIZE):
            db.table("pickem_research_observations").insert(insert_chunk).execute()

    return {"eligible_seen": len(prepared), "inserted": len(inserts), "updated": updated}


def update_pickem_research_close_snapshots(
    db,
    *,
    sides: list[dict[str, Any]],
    allow_close: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not sides:
        from services.clv_tracking import _new_snapshot_update_summary, _normalize_snapshot_summary

        return _normalize_snapshot_summary(_new_snapshot_update_summary())

    from services.clv_tracking import (
        _bump_counter,
        _build_reference_coverage,
        _diagnose_prop_reference_miss,
        _mark_snapshot_reason,
        _mark_identity_backfill,
        _new_snapshot_update_summary,
        _normalize_snapshot_summary,
        _repair_pickem_identity_row,
        build_prop_reference_pair_snapshots,
        build_prop_reference_snapshots,
        has_valid_close_snapshot,
        lookup_prop_opposing_reference_odds,
        lookup_prop_reference_odds,
        should_capture_close_snapshot,
    )

    prop_snapshot_by_event, prop_snapshot_by_time = build_prop_reference_snapshots(sides)
    prop_pair_by_event, prop_pair_by_time = build_prop_reference_pair_snapshots(sides)
    coverage = _build_reference_coverage(sides)
    if not prop_snapshot_by_event and not prop_snapshot_by_time:
        return _normalize_snapshot_summary(_new_snapshot_update_summary())

    sports = sorted({str(side.get("sport") or "").strip() for side in sides if side.get("sport")})
    try:
        query = (
            db.table("pickem_research_observations")
            .select(
                "id,sport,commence_time,event_id,player_name,market_key,selection_side,line_value,"
                "first_fair_odds_american,last_fair_odds_american,close_reference_odds,close_captured_at"
            )
        )
        if sports:
            query = query.in_("sport", sports)
        result = query.execute()
    except Exception as exc:
        if is_missing_pickem_research_observations_error(exc):
            return _normalize_snapshot_summary(_new_snapshot_update_summary())
        raise

    current = now or _utc_now()
    updated_at = current.isoformat()
    summary = _new_snapshot_update_summary()

    for row in result.data or []:
        repaired_row, repair_payload = _repair_pickem_identity_row(row)
        summary["row_count"] += 1
        _bump_counter(summary["candidate_surface_counts"], "player_props")
        _bump_counter(summary["candidate_market_counts"], _normalize_text(repaired_row.get("market_key")) or "player_props")
        _mark_identity_backfill(summary, repair_payload)
        reference_odds = lookup_prop_reference_odds(
            player_name=repaired_row.get("player_name"),
            source_market_key=repaired_row.get("market_key"),
            selection_side=repaired_row.get("selection_side"),
            line_value=_coerce_float(repaired_row.get("line_value")),
            commence_time=repaired_row.get("commence_time"),
            event_id=repaired_row.get("event_id"),
            snapshot_by_event=prop_snapshot_by_event,
            snapshot_by_time=prop_snapshot_by_time,
        )
        if reference_odds is None:
            summary["unmatched_count"] += 1
            _mark_snapshot_reason(summary, _diagnose_prop_reference_miss(repaired_row, coverage, market_field="market_key"))
            continue

        opposing_reference_odds = lookup_prop_opposing_reference_odds(
            player_name=repaired_row.get("player_name"),
            source_market_key=repaired_row.get("market_key"),
            selection_side=repaired_row.get("selection_side"),
            line_value=_coerce_float(repaired_row.get("line_value")),
            commence_time=repaired_row.get("commence_time"),
            event_id=repaired_row.get("event_id"),
            pair_snapshot_by_event=prop_pair_by_event,
            pair_snapshot_by_time=prop_pair_by_time,
        )

        payload: dict[str, Any] = {
            "latest_reference_odds": reference_odds,
            "latest_reference_updated_at": updated_at,
        }
        if repair_payload:
            payload.update(repair_payload)
        summary["matched_count"] += 1
        summary["latest_updated"] += 1
        _bump_counter(summary["matched_surface_counts"], "player_props")
        _bump_counter(summary["matched_market_counts"], _normalize_text(repaired_row.get("market_key")) or "player_props")

        can_capture_close = allow_close and should_capture_close_snapshot(
            repaired_row.get("commence_time"),
            existing_close=repaired_row.get("close_reference_odds"),
            captured_at=repaired_row.get("close_captured_at"),
            now=current,
        )
        if can_capture_close:
            fair_odds = _coerce_float(repaired_row.get("first_fair_odds_american")) or _coerce_float(repaired_row.get("last_fair_odds_american"))
            close_eval = calculate_clv(
                float(fair_odds if fair_odds is not None else reference_odds),
                float(reference_odds),
                opposing_reference_odds,
            )
            payload.update(
                {
                    "close_reference_odds": reference_odds,
                    "close_opposing_reference_odds": opposing_reference_odds,
                    "close_true_prob": close_eval.get("close_true_prob"),
                    "close_quality": close_eval.get("close_quality"),
                    "close_captured_at": updated_at,
                    "close_edge_pct": close_eval.get("clv_ev_percent"),
                }
            )
            summary["close_updated"] += 1
        elif allow_close and (
            repaired_row.get("close_reference_odds") is None
            or not has_valid_close_snapshot(repaired_row.get("commence_time"), repaired_row.get("close_captured_at"))
        ):
            summary["close_rejected_count"] += 1
            _mark_snapshot_reason(summary, "outside_close_window")

        try:
            db.table("pickem_research_observations").update(payload).eq("id", row["id"]).execute()
        except Exception:
            _mark_snapshot_reason(summary, "write_failed")
            raise

    return _normalize_snapshot_summary(summary)


async def settle_pickem_research_observations(
    db: Any,
    completed_events_by_sport: dict[str, list[dict[str, Any]]],
    settled_at: str,
    *,
    source: str,
    now: datetime | None = None,
    telemetry: dict[str, Any] | None = None,
) -> tuple[int, dict[str, int]]:
    from services.odds_api import _select_completed_event_for_bet
    from services.prop_settler import (
        build_player_stat_map,
        fetch_boxscore_provider_events_for_rows,
        fetch_boxscore_summary,
        grade_prop,
        resolve_boxscore_event_id,
    )

    skipped: dict[str, int] = {
        "manual_settlement_required": 0,
        "unsupported_sport": 0,
        "missing_clv_team": 0,
        "missing_commence_time": 0,
        "no_match": 0,
        "ambiguous_match": 0,
        "boxscore_resolve_failed": 0,
        "boxscore_fetch_failed": 0,
        "ungraded_pickem": 0,
        "db_update_failed": 0,
    }

    try:
        result = (
            db.table("pickem_research_observations")
            .select("id,sport,event_id,commence_time,team,player_name,market_key,line_value,selection_side,actual_result")
            .execute()
        )
    except Exception as exc:
        if is_missing_pickem_research_observations_error(exc):
            return (0, skipped)
        raise

    current = now or _utc_now()
    pending_rows = [
        row
        for row in (result.data or [])
        if _parse_actual_result(row.get("actual_result")) is None
        and (_coerce_datetime(row.get("commence_time")) or current) < current
    ]
    if not pending_rows:
        return (0, skipped)

    boxscore_summary_cache: dict[tuple[str, str], dict[str, Any]] = {}
    boxscore_resolve_cache_by_sport: dict[str, dict[tuple[str, str, str], Any]] = {}
    provider_events_by_sport = await fetch_boxscore_provider_events_for_rows(
        pending_rows,
        sport_field="sport",
        commence_time_field="commence_time",
        now=current,
    )

    settled = 0
    for row in pending_rows:
        sport = str(row.get("sport") or "").strip().lower()
        if not sport:
            skipped["unsupported_sport"] += 1
            continue
        if not _pickem_auto_settle_supported(sport, row.get("market_key")):
            skipped["manual_settlement_required"] += 1
            continue

        events = completed_events_by_sport.get(sport) or []
        synthetic = {
            "clv_event_id": str(row.get("event_id") or "").strip() or None,
            "clv_team": row.get("team"),
            "commence_time": row.get("commence_time"),
            "clv_sport_key": sport,
        }
        event, reason = _select_completed_event_for_bet(synthetic, events)
        if event is None:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue

        home = str(event.get("home_team", ""))
        away = str(event.get("away_team", ""))
        res = await resolve_boxscore_event_id(
            sport,
            home,
            away,
            row.get("commence_time"),
            odds_completed_event=event,
            cache_by_sport=boxscore_resolve_cache_by_sport,
            now=current,
            provider_events_by_sport=provider_events_by_sport,
            telemetry=telemetry,
            context="pickem_research",
            ref_id=str(row.get("id")) if row.get("id") is not None else None,
        )
        provider_event_id = res.provider_event_id
        if not provider_event_id:
            skipped["boxscore_resolve_failed"] += 1
            continue

        summary_cache_key = (sport, provider_event_id)
        if summary_cache_key not in boxscore_summary_cache:
            try:
                boxscore_summary_cache[summary_cache_key] = await fetch_boxscore_summary(
                    sport,
                    provider_event_id,
                )
            except Exception:
                skipped["boxscore_fetch_failed"] += 1
                continue

        stat_map = build_player_stat_map(
            boxscore_summary_cache[summary_cache_key],
            sport=sport,
        )
        grade, _detail = grade_prop(
            row.get("player_name"),
            row.get("market_key"),
            row.get("line_value"),
            row.get("selection_side"),
            stat_map,
            sport=sport,
        )
        if grade is None:
            skipped["ungraded_pickem"] += 1
            continue

        try:
            db.table("pickem_research_observations").update(
                {"actual_result": grade, "settled_at": settled_at}
            ).eq("id", row["id"]).execute()
            settled += 1
        except Exception:
            skipped["db_update_failed"] += 1

    if any(value > 0 for value in skipped.values()):
        print(f"[Auto-Settler:pickem] summary settled={settled} skipped={skipped} source={source}")

    return (settled, skipped)


def _build_breakdown(
    rows: list[dict[str, Any]],
    *,
    key_fn,
    preferred_order: list[str] | None = None,
) -> list[PickEmResearchBreakdownItem]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row) or "Unknown")].append(row)

    preferred_position = {key: index for index, key in enumerate(preferred_order or [])}
    items: list[PickEmResearchBreakdownItem] = []

    for key, bucket_rows in groups.items():
        settled_rows = [row for row in bucket_rows if row.get("_actual_result") in {"win", "loss", "push"}]
        decisive_rows = [row for row in bucket_rows if row.get("_actual_result") in {"win", "loss"}]
        close_rows = [row for row in bucket_rows if row.get("_close_ready")]
        win_count = sum(1 for row in decisive_rows if row.get("_actual_result") == "win")
        push_count = sum(1 for row in settled_rows if row.get("_actual_result") == "push")
        expected_values = [float(row["_display_probability"]) for row in decisive_rows if row.get("_display_probability") is not None]
        close_drift_values = [float(row["_close_drift_pct_points"]) for row in close_rows if row.get("_close_drift_pct_points") is not None]
        close_edge_values = [float(row["close_edge_pct"]) for row in close_rows if row.get("close_edge_pct") is not None]
        brier_values = [float(row["_brier_score"]) for row in decisive_rows if row.get("_brier_score") is not None]
        log_values = [float(row["_log_loss"]) for row in decisive_rows if row.get("_log_loss") is not None]

        expected_hit_rate_pct = round((sum(expected_values) / len(expected_values)) * 100, 2) if expected_values else None
        actual_hit_rate_pct = round((win_count / len(decisive_rows)) * 100, 2) if decisive_rows else None
        hit_delta = (
            round(actual_hit_rate_pct - expected_hit_rate_pct, 2)
            if actual_hit_rate_pct is not None and expected_hit_rate_pct is not None
            else None
        )

        items.append(
            PickEmResearchBreakdownItem(
                key=key,
                captured_count=len(bucket_rows),
                close_ready_count=len(close_rows),
                settled_count=len(settled_rows),
                decisive_count=len(decisive_rows),
                push_count=push_count,
                expected_hit_rate_pct=expected_hit_rate_pct,
                actual_hit_rate_pct=actual_hit_rate_pct,
                hit_rate_delta_pct_points=hit_delta,
                avg_close_drift_pct_points=round(sum(close_drift_values) / len(close_drift_values), 2) if close_drift_values else None,
                avg_close_edge_pct=round(sum(close_edge_values) / len(close_edge_values), 2) if close_edge_values else None,
                avg_brier_score=round(sum(brier_values) / len(brier_values), 6) if brier_values else None,
                avg_log_loss=round(sum(log_values) / len(log_values), 6) if log_values else None,
            )
        )

    items.sort(
        key=lambda item: (
            preferred_position.get(item.key, len(preferred_position)),
            -item.decisive_count,
            -item.captured_count,
            item.key,
        )
    )
    return items


def get_pickem_research_summary(db) -> PickEmResearchSummaryResponse:
    try:
        result = (
            db.table("pickem_research_observations")
            .select(
                "observation_key,comparison_key,sport,event,commence_time,market,market_key,event_id,player_name,team,opponent,"
                "selection_side,line_value,calibration_bucket,first_source,last_source,surfaced_count,first_seen_at,last_seen_at,"
                "first_display_probability,last_display_probability,first_fair_odds_american,last_fair_odds_american,"
                "first_books_matched_count,last_books_matched_count,first_confidence_label,last_confidence_label,"
                "ev_basis,first_selected_sportsbook,last_selected_sportsbook,first_selected_market_odds,last_selected_market_odds,"
                "first_projected_edge_pct,last_projected_edge_pct,close_true_prob,close_quality,close_captured_at,close_edge_pct,"
                "actual_result,settled_at"
            )
            .execute()
        )
    except Exception as exc:
        if is_missing_pickem_research_observations_error(exc):
            return empty_pickem_research_summary()
        raise

    rows = list(result.data or [])
    if not rows:
        return empty_pickem_research_summary()

    for row in rows:
        display_probability = _coerce_float(row.get("first_display_probability"))
        close_probability = _coerce_float(row.get("close_true_prob"))
        actual_result = _parse_actual_result(row.get("actual_result"))
        brier_score, log_loss = _binary_calibration_metrics(display_probability, actual_result)
        row["_display_probability"] = display_probability
        row["_close_ready"] = close_probability is not None and _coerce_datetime(row.get("close_captured_at")) is not None
        row["_actual_result"] = actual_result
        row["_brier_score"] = brier_score
        row["_log_loss"] = log_loss
        row["_close_drift_pct_points"] = (
            round((close_probability - display_probability) * 100, 2)
            if close_probability is not None and display_probability is not None
            else None
        )
        row["_calibration_bucket"] = str(row.get("calibration_bucket") or _probability_bucket(display_probability))
        row["_books_bucket"] = _books_matched_bucket(_coerce_int(row.get("first_books_matched_count")))

    settled_rows = [row for row in rows if row.get("_actual_result") in {"win", "loss", "push"}]
    decisive_rows = [row for row in rows if row.get("_actual_result") in {"win", "loss"}]
    close_rows = [row for row in rows if row.get("_close_ready")]
    pending_rows = [row for row in rows if row.get("_actual_result") is None]
    manual_result_rows = [
        row
        for row in pending_rows
        if _pickem_manual_result_required(row.get("sport"), row.get("market_key"))
    ]
    auto_settle_pending_rows = [
        row
        for row in pending_rows
        if not _pickem_manual_result_required(row.get("sport"), row.get("market_key"))
    ]
    pending_result_count = len(pending_rows)
    manual_only_sports = sorted(
        {
            _normalize_text(row.get("sport"))
            for row in manual_result_rows
            if _normalize_text(row.get("sport"))
        }
    )
    push_count = sum(1 for row in settled_rows if row.get("_actual_result") == "push")
    win_count = sum(1 for row in decisive_rows if row.get("_actual_result") == "win")

    expected_values = [float(row["_display_probability"]) for row in decisive_rows if row.get("_display_probability") is not None]
    close_prob_values = [float(row["close_true_prob"]) for row in close_rows if row.get("close_true_prob") is not None]
    close_drift_values = [float(row["_close_drift_pct_points"]) for row in close_rows if row.get("_close_drift_pct_points") is not None]
    close_edge_values = [float(row["close_edge_pct"]) for row in close_rows if row.get("close_edge_pct") is not None]
    brier_values = [float(row["_brier_score"]) for row in decisive_rows if row.get("_brier_score") is not None]
    log_values = [float(row["_log_loss"]) for row in decisive_rows if row.get("_log_loss") is not None]

    expected_hit_rate_pct = round((sum(expected_values) / len(expected_values)) * 100, 2) if expected_values else None
    actual_hit_rate_pct = round((win_count / len(decisive_rows)) * 100, 2) if decisive_rows else None
    hit_rate_delta_pct_points = (
        round(actual_hit_rate_pct - expected_hit_rate_pct, 2)
        if actual_hit_rate_pct is not None and expected_hit_rate_pct is not None
        else None
    )

    by_probability_bucket = _build_breakdown(
        rows,
        key_fn=lambda row: row.get("_calibration_bucket") or "Unknown",
        preferred_order=PROBABILITY_BUCKET_ORDER,
    )
    by_market = _build_breakdown(rows, key_fn=lambda row: row.get("market") or row.get("market_key") or "Unknown")
    by_books_matched = _build_breakdown(
        rows,
        key_fn=lambda row: row.get("_books_bucket") or "Unknown",
        preferred_order=BOOKS_MATCHED_BUCKET_ORDER,
    )
    by_ev_basis = _build_breakdown(rows, key_fn=lambda row: row.get("ev_basis") or EV_BASIS_UNPRICED)

    recent_rows = sorted(
        rows,
        key=lambda row: _coerce_datetime(row.get("first_seen_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:15]

    recent_observations = [
        PickEmResearchRecentRow(
            observation_key=str(row.get("observation_key") or ""),
            comparison_key=str(row.get("comparison_key") or ""),
            first_seen_at=_coerce_datetime(row.get("first_seen_at")) or _utc_now(),
            last_seen_at=_coerce_datetime(row.get("last_seen_at")) or _utc_now(),
            sport=str(row.get("sport") or ""),
            event=str(row.get("event") or ""),
            commence_time=str(row.get("commence_time") or ""),
            market=str(row.get("market") or row.get("market_key") or ""),
            player_name=str(row.get("player_name") or ""),
            selection_side=str(row.get("selection_side") or ""),
            line_value=float(row.get("line_value") or 0),
            displayed_probability=float(row.get("first_display_probability") or 0),
            fair_odds_american=_coerce_float(row.get("first_fair_odds_american")),
            books_matched_count=int(row.get("first_books_matched_count") or 0),
            confidence_label=str(row.get("first_confidence_label") or "").strip() or None,
            ev_basis=str(row.get("ev_basis") or EV_BASIS_UNPRICED),
            selected_sportsbook=str(row.get("first_selected_sportsbook") or "").strip() or None,
            selected_market_odds=_coerce_float(row.get("first_selected_market_odds")),
            projected_edge_pct=_coerce_float(row.get("first_projected_edge_pct")),
            close_true_prob=_coerce_float(row.get("close_true_prob")),
            close_quality=str(row.get("close_quality") or "").strip() or None,
            close_edge_pct=_coerce_float(row.get("close_edge_pct")),
            close_drift_pct_points=_coerce_float(row.get("_close_drift_pct_points")),
            actual_result=row.get("_actual_result"),
            settled_at=_coerce_datetime(row.get("settled_at")),
            calibration_bucket=str(row.get("_calibration_bucket") or "Unknown"),
            first_source=str(row.get("first_source") or "unknown"),
            surfaced_count=int(row.get("surfaced_count") or 1),
        )
        for row in recent_rows
    ]

    return PickEmResearchSummaryResponse(
        captured_count=len(rows),
        close_ready_count=len(close_rows),
        settled_count=len(settled_rows),
        decisive_count=len(decisive_rows),
        push_count=push_count,
        pending_result_count=pending_result_count,
        auto_settle_pending_count=len(auto_settle_pending_rows),
        manual_result_count=len(manual_result_rows),
        manual_only_sports=manual_only_sports,
        avg_display_probability_pct=expected_hit_rate_pct,
        expected_hit_rate_pct=expected_hit_rate_pct,
        actual_hit_rate_pct=actual_hit_rate_pct,
        hit_rate_delta_pct_points=hit_rate_delta_pct_points,
        avg_close_probability_pct=round((sum(close_prob_values) / len(close_prob_values)) * 100, 2) if close_prob_values else None,
        avg_close_drift_pct_points=round(sum(close_drift_values) / len(close_drift_values), 2) if close_drift_values else None,
        avg_close_edge_pct=round(sum(close_edge_values) / len(close_edge_values), 2) if close_edge_values else None,
        avg_brier_score=round(sum(brier_values) / len(brier_values), 6) if brier_values else None,
        avg_log_loss=round(sum(log_values) / len(log_values), 6) if log_values else None,
        by_probability_bucket=by_probability_bucket,
        by_market=by_market,
        by_books_matched=by_books_matched,
        by_ev_basis=by_ev_basis,
        recent_observations=recent_observations,
    )
