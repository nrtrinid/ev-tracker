from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

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


def _classify_bet_status(row: dict[str, Any]) -> str:
    if row.get("pinnacle_odds_at_close") is None:
        return "pending"
    if not has_valid_close_snapshot(row.get("commence_time"), row.get("clv_updated_at")):
        return "invalid"
    if row.get("clv_ev_percent") is None or row.get("beat_close") is None:
        return "invalid"
    return "valid"


def _classify_research_status(row: dict[str, Any]) -> str:
    if row.get("reference_odds_at_close") is None:
        return "pending"
    if not has_valid_close_snapshot(row.get("commence_time"), row.get("close_captured_at")):
        return "invalid"
    if row.get("clv_ev_percent") is None or row.get("beat_close") is None:
        return "invalid"
    return "valid"


def _build_status_summary(
    rows: list[dict[str, Any]],
    *,
    classify_status: Callable[[dict[str, Any]], str],
    id_field: str,
    timestamp_field: str,
) -> dict[str, Any]:
    annotated = []
    for row in rows:
        copied = dict(row)
        copied["_status"] = classify_status(copied)
        annotated.append(copied)

    annotated.sort(
        key=lambda row: _coerce_datetime(row.get(timestamp_field)) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    def _sample(status: str) -> list[dict[str, Any]]:
        return [
            {
                "id": str(row.get(id_field) or ""),
                "status": status,
                "surface": str(row.get("surface") or "straight_bets"),
                "event": str(row.get("event") or ""),
                "sportsbook": str(row.get("sportsbook") or ""),
                "commence_time": str(row.get("commence_time") or ""),
                "captured_at": row.get(timestamp_field),
                "clv_ev_percent": _coerce_float(row.get("clv_ev_percent")),
                "beat_close": row.get("beat_close"),
            }
            for row in annotated
            if row.get("_status") == status
        ][:3]

    return {
        "tracked_count": len(annotated),
        "pending_count": sum(1 for row in annotated if row.get("_status") == "pending"),
        "valid_count": sum(1 for row in annotated if row.get("_status") == "valid"),
        "invalid_count": sum(1 for row in annotated if row.get("_status") == "invalid"),
        "sample": {
            "pending": _sample("pending"),
            "valid": _sample("valid"),
            "invalid": _sample("invalid"),
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
            .select("id,surface,event,sportsbook,commence_time,created_at,pinnacle_odds_at_close,clv_updated_at,clv_ev_percent,beat_close")
            .not_.is_("commence_time", "null")
            .execute()
        )
    )
    try:
        research_result = run_query(
            lambda: (
                db.table("scan_opportunities")
                .select("id,surface,event,sportsbook,commence_time,first_seen_at,reference_odds_at_close,close_captured_at,clv_ev_percent,beat_close")
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
            id_field="id",
            timestamp_field="created_at",
        ),
        "research_opportunities": _build_status_summary(
            research_rows,
            classify_status=_classify_research_status,
            id_field="id",
            timestamp_field="first_seen_at",
        ),
    }
