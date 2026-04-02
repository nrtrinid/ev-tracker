from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from calculations import calculate_clv
from services.clv_tracking import has_valid_close_snapshot
from services.research_opportunities import is_missing_scan_opportunities_error


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


def _build_status_summary(
    rows: list[dict[str, Any]],
    *,
    classify_status: Callable[[dict[str, Any]], str],
    compute_clv_fields: Callable[[dict[str, Any]], tuple[float | None, bool | None]],
    id_field: str,
    timestamp_field: str,
    latest_timestamp_field: str,
    close_timestamp_field: str,
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

    def _captured_at(row: dict[str, Any]) -> Any:
        status = str(row.get("_status") or "")
        if status == "latest_only":
            return row.get(latest_timestamp_field)
        if status in {"outside_window", "valid"}:
            return row.get(close_timestamp_field)
        return None

    def _sample(*statuses: str) -> list[dict[str, Any]]:
        allowed = set(statuses)
        return [
            {
                "id": str(row.get(id_field) or ""),
                "status": str(row.get("_status") or ""),
                "surface": str(row.get("surface") or "straight_bets"),
                "event": str(row.get("event") or ""),
                "sportsbook": str(row.get("sportsbook") or ""),
                "commence_time": str(row.get("commence_time") or ""),
                "captured_at": _captured_at(row),
                "clv_ev_percent": row.get("_clv_ev_percent"),
                "beat_close": row.get("_beat_close"),
            }
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
        "sample": {
            "pending": _sample("missing_close", "latest_only"),
            "valid": _sample("valid"),
            "invalid": _sample("outside_window"),
            "missing_close": _sample("missing_close"),
            "latest_only": _sample("latest_only"),
            "outside_window": _sample("outside_window"),
        },
    }


def build_clv_audit_snapshot(
    db: Any,
    *,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
    load_scheduler_job_snapshot: Callable[..., dict[str, dict[str, Any] | None]] | None = None,
    utc_now_iso: Callable[[], str] | None = None,
) -> dict[str, Any]:
    run_query = retry_supabase or (lambda op, **_: op())

    bets_result = run_query(
        lambda: (
            db.table("bets")
            .select(
                "id,surface,event,sportsbook,commence_time,created_at,odds_american,"
                "latest_pinnacle_odds,latest_pinnacle_updated_at,pinnacle_odds_at_close,clv_updated_at"
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
                    "id,surface,event,sportsbook,commence_time,first_seen_at,first_book_odds,"
                    "latest_reference_odds,latest_reference_updated_at,reference_odds_at_close,"
                    "close_opposing_reference_odds,close_captured_at"
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

    scheduler = (
        load_scheduler_job_snapshot(db=db, retry_supabase=retry_supabase)
        if load_scheduler_job_snapshot is not None
        else {}
    )

    return {
        "generated_at": utc_now_iso() if callable(utc_now_iso) else None,
        "scheduler": scheduler,
        "bets": _build_status_summary(
            list(bets_result.data or []),
            classify_status=_classify_bet_status,
            compute_clv_fields=_compute_bet_clv_fields,
            id_field="id",
            timestamp_field="created_at",
            latest_timestamp_field="latest_pinnacle_updated_at",
            close_timestamp_field="clv_updated_at",
        ),
        "research_opportunities": _build_status_summary(
            research_rows,
            classify_status=_classify_research_status,
            compute_clv_fields=_compute_research_clv_fields,
            id_field="id",
            timestamp_field="first_seen_at",
            latest_timestamp_field="latest_reference_updated_at",
            close_timestamp_field="close_captured_at",
        ),
    }
