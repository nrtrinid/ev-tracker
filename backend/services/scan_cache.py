from typing import Any, Callable
from fastapi import HTTPException

from models import FullScanResponse


def empty_scan_response() -> FullScanResponse:
    return FullScanResponse(
        sport="all",
        sides=[],
        events_fetched=0,
        events_with_both_books=0,
        api_requests_remaining=None,
        scanned_at=None,
    )


def is_missing_scan_cache_error(error: Exception) -> bool:
    msg = str(error)
    return "PGRST205" in msg or ("global_scan_cache" in msg and "schema cache" in msg)


def persist_latest_scan_payload(
    *,
    db,
    payload: dict[str, Any],
    retry_supabase: Callable,
    log_event: Callable[..., None],
) -> None:
    try:
        retry_supabase(lambda: (
            db.table("global_scan_cache").upsert(
                {"key": "latest", "payload": payload},
                on_conflict="key",
            ).execute()
        ))
    except Exception as e:
        log_event(
            "scan_latest_cache.persist_failed",
            level="warning",
            error_class=type(e).__name__,
            error=str(e),
        )


def load_latest_scan_payload(*, db, retry_supabase: Callable) -> dict[str, Any] | None:
    try:
        res = retry_supabase(lambda: (
            db.table("global_scan_cache")
            .select("payload")
            .eq("key", "latest")
            .limit(1)
            .execute()
        ))
    except Exception as e:
        if is_missing_scan_cache_error(e):
            return None
        raise

    rows = getattr(res, "data", None) or []
    if not rows:
        return None

    payload = rows[0].get("payload") if isinstance(rows[0], dict) else None
    if not isinstance(payload, dict):
        raise ValueError("Invalid scan cache payload")
    return payload


def persist_latest_full_scan(
    *,
    db,
    sport: str,
    sides: list[dict[str, Any]],
    events_fetched: int,
    events_with_both_books: int,
    api_requests_remaining: str | None,
    scanned_at: str | None,
    retry_supabase: Callable,
    log_event: Callable[..., None],
) -> None:
    payload = FullScanResponse(
        sport=sport,
        sides=sides,
        events_fetched=events_fetched,
        events_with_both_books=events_with_both_books,
        api_requests_remaining=api_requests_remaining,
        scanned_at=scanned_at,
    ).model_dump()
    persist_latest_scan_payload(
        db=db,
        payload=payload,
        retry_supabase=retry_supabase,
        log_event=log_event,
    )


def with_enriched_scan_sides(
    *,
    payload: dict[str, Any],
    enrich_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    result = dict(payload)
    sides_raw = payload.get("sides")
    if isinstance(sides_raw, list):
        sides = sides_raw
    else:
        sides = []
    result["sides"] = enrich_sides(sides)
    return result


def load_and_enrich_latest_scan_payload(
    *,
    db,
    retry_supabase: Callable,
    enrich_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    payload = load_latest_scan_payload(db=db, retry_supabase=retry_supabase)
    if payload is None:
        return None
    return with_enriched_scan_sides(payload=payload, enrich_sides=enrich_sides)


def resolve_scan_latest_response(
    *,
    db,
    retry_supabase: Callable,
    enrich_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any] | FullScanResponse:
    payload = load_and_enrich_latest_scan_payload(
        db=db,
        retry_supabase=retry_supabase,
        enrich_sides=enrich_sides,
    )
    if payload is None:
        return empty_scan_response()
    return payload


def scan_cache_exception_to_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, ValueError):
        return HTTPException(status_code=500, detail=str(error))
    return HTTPException(status_code=502, detail=f"Failed to load scan cache: {error}")
