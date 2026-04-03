from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from calculations import calculate_clv
from services.clv_tracking import CLV_AUDIT_REASON_CODES, CLOSE_WINDOW_MINUTES, has_valid_close_snapshot
from services.pickem_research import is_missing_pickem_research_observations_error
from services.research_opportunities import is_missing_scan_opportunities_error

_SCHEDULED_CLV_STALE_MINUTES = {"jit_clv": 45}


def _coerce_datetime(value: Any) -> datetime | None:
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


def _compute_bet_clv_fields(row: dict[str, Any]) -> tuple[float | None, bool | None]:
    book_odds = _coerce_float(row.get("odds_american"))
    close_odds = _coerce_float(row.get("pinnacle_odds_at_close"))
    if book_odds is None or close_odds is None:
        return (None, None)
    clv = calculate_clv(book_odds, close_odds)
    return (
        _coerce_float(clv.get("clv_ev_percent")) if isinstance(clv, dict) else None,
        clv.get("beat_close") if isinstance(clv, dict) else None,
    )


def _compute_research_clv_fields(row: dict[str, Any]) -> tuple[float | None, bool | None]:
    book_odds = _coerce_float(row.get("first_book_odds"))
    close_odds = _coerce_float(row.get("reference_odds_at_close"))
    close_opposing = _coerce_float(row.get("close_opposing_reference_odds"))
    if book_odds is None or close_odds is None:
        return (None, None)
    clv = calculate_clv(book_odds, close_odds, close_opposing)
    return (
        _coerce_float(clv.get("clv_ev_percent")) if isinstance(clv, dict) else None,
        clv.get("beat_close") if isinstance(clv, dict) else None,
    )


def _compute_pickem_clv_fields(row: dict[str, Any]) -> tuple[float | None, bool | None]:
    fair_odds = _coerce_float(row.get("first_fair_odds_american"))
    close_odds = _coerce_float(row.get("close_reference_odds"))
    close_opposing = _coerce_float(row.get("close_opposing_reference_odds"))
    if fair_odds is None or close_odds is None:
        return (None, None)
    clv = calculate_clv(fair_odds, close_odds, close_opposing)
    return (
        _coerce_float(clv.get("clv_ev_percent")) if isinstance(clv, dict) else None,
        clv.get("beat_close") if isinstance(clv, dict) else None,
    )


def _classify_bet_status(row: dict[str, Any]) -> str:
    if row.get("pinnacle_odds_at_close") is None:
        return "latest_only" if row.get("latest_pinnacle_odds") is not None else "missing_close"
    if not has_valid_close_snapshot(row.get("commence_time"), row.get("clv_updated_at")):
        return "outside_window"
    return "valid"


def _classify_research_status(row: dict[str, Any]) -> str:
    if row.get("reference_odds_at_close") is None:
        return "latest_only" if row.get("latest_reference_odds") is not None else "missing_close"
    if not has_valid_close_snapshot(row.get("commence_time"), row.get("close_captured_at")):
        return "outside_window"
    return "valid"


def _classify_pickem_status(row: dict[str, Any]) -> str:
    if row.get("close_reference_odds") is None:
        return "latest_only" if row.get("latest_reference_odds") is not None else "missing_close"
    if not has_valid_close_snapshot(row.get("commence_time"), row.get("close_captured_at")):
        return "outside_window"
    return "valid"


def _market_label(row: dict[str, Any]) -> str:
    surface = _normalize_text(row.get("surface")) or "straight_bets"
    if surface == "player_props":
        return str(row.get("source_market_key") or row.get("market_key") or "player_props")
    return str(row.get("source_market_key") or row.get("market_key") or "h2h")


def _build_breakdown(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    grouped: dict[str, int] = defaultdict(int)
    for row in rows:
        grouped[str(key_fn(row) or "Unknown")] += 1
    return [
        {"key": key, "count": count}
        for key, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
    ]


def _build_identity_completeness(rows: list[dict[str, Any]], *, row_kind: str) -> dict[str, int]:
    summary = {
        "complete_count": 0,
        "missing_event_id_count": 0,
        "missing_market_key_count": 0,
        "missing_selection_side_count": 0,
        "missing_line_value_count": 0,
        "legacy_identity_count": 0,
    }
    for row in rows:
        surface = _normalize_text(row.get("surface")) or "straight_bets"
        has_event_id = bool(str(row.get("source_event_id") or row.get("event_id") or row.get("clv_event_id") or "").strip())
        has_market_key = bool(str(row.get("source_market_key") or row.get("market_key") or "").strip())
        has_selection_side = bool(str(row.get("selection_side") or "").strip())
        has_line_value = row.get("line_value") is not None and str(row.get("line_value")).strip() != ""
        if not has_event_id:
            summary["missing_event_id_count"] += 1
        if not has_market_key:
            summary["missing_market_key_count"] += 1
        if not has_selection_side:
            summary["missing_selection_side_count"] += 1
        if not has_line_value:
            summary["missing_line_value_count"] += 1

        if row_kind == "bets" and surface != "player_props" and not has_market_key and not has_selection_side and not has_line_value:
            summary["legacy_identity_count"] += 1

        if has_event_id and (surface != "player_props" or (has_market_key and has_selection_side and has_line_value)):
            summary["complete_count"] += 1
    return summary


def _sample_row(
    row: dict[str, Any],
    *,
    id_field: str,
    latest_timestamp_field: str,
    close_timestamp_field: str,
) -> dict[str, Any]:
    status = str(row.get("_status") or "")
    captured_at = None
    if status == "latest_only":
        captured_at = row.get(latest_timestamp_field)
    elif status in {"outside_window", "valid"}:
        captured_at = row.get(close_timestamp_field)
    return {
        "id": str(row.get(id_field) or ""),
        "status": status,
        "surface": str(row.get("surface") or "straight_bets"),
        "sport": str(row.get("sport") or row.get("clv_sport_key") or ""),
        "market_key": str(row.get("source_market_key") or row.get("market_key") or "h2h"),
        "event": str(row.get("event") or ""),
        "sportsbook": str(row.get("sportsbook") or ""),
        "commence_time": str(row.get("commence_time") or ""),
        "captured_at": captured_at,
        "clv_ev_percent": row.get("_clv_ev_percent"),
        "beat_close": row.get("_beat_close"),
    }


def _build_status_summary(
    rows: list[dict[str, Any]],
    *,
    classify_status: Callable[[dict[str, Any]], str],
    compute_clv_fields: Callable[[dict[str, Any]], tuple[float | None, bool | None]],
    id_field: str,
    timestamp_field: str,
    latest_timestamp_field: str,
    close_timestamp_field: str,
    row_kind: str,
) -> dict[str, Any]:
    annotated = []
    for row in rows:
        copied = dict(row)
        copied["_status"] = classify_status(copied)
        copied["_clv_ev_percent"], copied["_beat_close"] = compute_clv_fields(copied)
        annotated.append(copied)

    annotated.sort(
        key=lambda row: _coerce_datetime(row.get(timestamp_field)) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    def _sample(*statuses: str) -> list[dict[str, Any]]:
        allowed = set(statuses)
        return [
            _sample_row(
                row,
                id_field=id_field,
                latest_timestamp_field=latest_timestamp_field,
                close_timestamp_field=close_timestamp_field,
            )
            for row in annotated
            if row.get("_status") in allowed
        ][:3]

    missing_close_count = sum(1 for row in annotated if row.get("_status") == "missing_close")
    latest_only_count = sum(1 for row in annotated if row.get("_status") == "latest_only")
    outside_window_count = sum(1 for row in annotated if row.get("_status") == "outside_window")
    valid_count = sum(1 for row in annotated if row.get("_status") == "valid")

    return {
        "tracked_count": len(annotated),
        "pending_count": missing_close_count + latest_only_count,
        "valid_count": valid_count,
        "invalid_count": outside_window_count,
        "missing_close_count": missing_close_count,
        "latest_only_count": latest_only_count,
        "outside_window_count": outside_window_count,
        "by_surface": _build_breakdown(annotated, lambda row: str(row.get("surface") or "straight_bets")),
        "by_market": _build_breakdown(annotated, _market_label),
        "by_sport": _build_breakdown(annotated, lambda row: str(row.get("sport") or row.get("clv_sport_key") or "Unknown")),
        "by_sportsbook": _build_breakdown(annotated, lambda row: str(row.get("sportsbook") or "Unknown")),
        "identity_completeness": _build_identity_completeness(annotated, row_kind=row_kind),
        "sample": {
            "pending": _sample("missing_close", "latest_only"),
            "valid": _sample("valid"),
            "invalid": _sample("outside_window"),
            "missing_close": _sample("missing_close"),
            "latest_only": _sample("latest_only"),
            "outside_window": _sample("outside_window"),
        },
    }


def _build_job_staleness(
    scheduler: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    stale: dict[str, Any] = {}
    for job_kind, threshold_minutes in _SCHEDULED_CLV_STALE_MINUTES.items():
        row = scheduler.get(job_kind) if isinstance(scheduler, dict) else None
        captured_at = _coerce_datetime((row or {}).get("captured_at"))
        minutes_since_last_run = None
        is_stale = captured_at is None
        if captured_at is not None:
            minutes_since_last_run = round((now - captured_at).total_seconds() / 60, 2)
            is_stale = minutes_since_last_run > threshold_minutes
        stale[job_kind] = {
            "scheduled": True,
            "last_run_at": (row or {}).get("captured_at"),
            "minutes_since_last_run": minutes_since_last_run,
            "stale_after_minutes": threshold_minutes,
            "is_stale": is_stale,
        }
    stale["clv_daily"] = {"scheduled": False, "is_stale": None}
    stale["clv_replay"] = {"scheduled": False, "is_stale": None}
    stale["clv_piggyback"] = {"scheduled": False, "is_stale": None}
    return stale


def _build_job_run_summary(recent_job_runs: list[dict[str, Any]], scheduler: dict[str, Any], now: datetime) -> dict[str, Any]:
    by_source: dict[str, int] = defaultdict(int)
    by_job_kind: dict[str, int] = defaultdict(int)
    for row in recent_job_runs:
        by_source[str(row.get("source") or "unknown")] += 1
        by_job_kind[str(row.get("job_kind") or "unknown")] += 1
    return {
        "recent": recent_job_runs,
        "by_source": [{"source": key, "count": value} for key, value in sorted(by_source.items(), key=lambda item: (-item[1], item[0]))],
        "by_job_kind": [{"job_kind": key, "count": value} for key, value in sorted(by_job_kind.items(), key=lambda item: (-item[1], item[0]))],
        "stale_jobs": _build_job_staleness(scheduler, now),
    }


def _build_inventory() -> dict[str, Any]:
    return {
        "writers": [
            {
                "job_kind": "jit_clv",
                "trigger": "scheduler interval 15m or ops trigger",
                "candidate_scope": "pending bets + scan opportunities + pickem rows within close window",
                "persistence_targets": ["bets", "scan_opportunities", "pickem_research_observations"],
            },
            {
                "job_kind": "clv_piggyback",
                "trigger": "fresh manual scan or board drop follow-up",
                "candidate_scope": "fresh fetched sides only",
                "persistence_targets": ["bets", "scan_opportunities", "pickem_research_observations"],
            },
            {
                "job_kind": "clv_daily",
                "trigger": "manual ops trigger only during audit",
                "candidate_scope": "all pending tracked bets",
                "persistence_targets": ["bets"],
            },
            {
                "job_kind": "clv_replay",
                "trigger": "manual ops trigger only",
                "candidate_scope": "recent pending bets inside lookback window",
                "persistence_targets": ["bets"],
            },
        ],
        "readers": [
            "bets badge rendering",
            "ops clv debug snapshot",
            "research tracker close metrics",
            "pickem research close metrics",
            "model calibration close readiness",
        ],
        "reason_codes": list(CLV_AUDIT_REASON_CODES),
        "close_window_minutes": CLOSE_WINDOW_MINUTES,
    }


def build_clv_audit_snapshot(
    db: Any,
    *,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
    load_scheduler_job_snapshot: Callable[..., dict[str, dict[str, Any] | None]] | None = None,
    load_recent_clv_job_runs: Callable[..., list[dict[str, Any]]] | None = None,
    utc_now_iso: Callable[[], str] | None = None,
) -> dict[str, Any]:
    run_query = retry_supabase or (lambda op, **_: op())

    bets_result = run_query(
        lambda: (
            db.table("bets")
            .select(
                "id,surface,event,sportsbook,commence_time,created_at,odds_american,"
                "latest_pinnacle_odds,latest_pinnacle_updated_at,pinnacle_odds_at_close,clv_updated_at,"
                "clv_sport_key,source_event_id,clv_event_id,source_market_key,selection_side,line_value,participant_name,clv_team"
            )
            .not_.is_("commence_time", "null")
            .execute()
        )
    )
    try:
        research_result = run_query(
            lambda: (
                db.table("scan_opportunities")
                .select(
                    "id,surface,sport,event,sportsbook,commence_time,first_seen_at,first_book_odds,"
                    "latest_reference_odds,latest_reference_updated_at,reference_odds_at_close,"
                    "close_opposing_reference_odds,close_captured_at,event_id,source_market_key,selection_side,line_value"
                )
                .execute()
            )
        )
        research_rows = list(research_result.data or [])
    except Exception as exc:
        if is_missing_scan_opportunities_error(exc):
            research_rows = []
        else:
            raise

    try:
        pickem_result = run_query(
            lambda: (
                db.table("pickem_research_observations")
                .select(
                    "id,surface,sport,event,commence_time,created_at,player_name,market_key,selection_side,line_value,"
                    "first_fair_odds_american,latest_reference_odds,latest_reference_updated_at,close_reference_odds,"
                    "close_opposing_reference_odds,close_captured_at"
                )
                .execute()
            )
        )
        pickem_rows = list(pickem_result.data or [])
    except Exception as exc:
        if is_missing_pickem_research_observations_error(exc):
            pickem_rows = []
        else:
            raise

    scheduler = (
        load_scheduler_job_snapshot(db=db, retry_supabase=retry_supabase)
        if load_scheduler_job_snapshot is not None
        else {}
    )
    recent_job_runs = (
        load_recent_clv_job_runs(db=db, retry_supabase=retry_supabase)
        if load_recent_clv_job_runs is not None
        else []
    )
    now_dt = _coerce_datetime(utc_now_iso()) if callable(utc_now_iso) else datetime.now(timezone.utc)
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    return {
        "generated_at": utc_now_iso() if callable(utc_now_iso) else None,
        "inventory": _build_inventory(),
        "scheduler": scheduler,
        "job_runs": _build_job_run_summary(recent_job_runs, scheduler, now_dt),
        "bets": _build_status_summary(
            list(bets_result.data or []),
            classify_status=_classify_bet_status,
            compute_clv_fields=_compute_bet_clv_fields,
            id_field="id",
            timestamp_field="created_at",
            latest_timestamp_field="latest_pinnacle_updated_at",
            close_timestamp_field="clv_updated_at",
            row_kind="bets",
        ),
        "research_opportunities": _build_status_summary(
            research_rows,
            classify_status=_classify_research_status,
            compute_clv_fields=_compute_research_clv_fields,
            id_field="id",
            timestamp_field="first_seen_at",
            latest_timestamp_field="latest_reference_updated_at",
            close_timestamp_field="close_captured_at",
            row_kind="research",
        ),
        "pickem_research": _build_status_summary(
            pickem_rows,
            classify_status=_classify_pickem_status,
            compute_clv_fields=_compute_pickem_clv_fields,
            id_field="id",
            timestamp_field="created_at",
            latest_timestamp_field="latest_reference_updated_at",
            close_timestamp_field="close_captured_at",
            row_kind="pickem",
        ),
    }
