from typing import Any, Callable

from fastapi import HTTPException

from models import FullScanResponse


DEFAULT_SURFACE = "straight_bets"


def build_scan_cache_key(surface: str, scope: str = "latest") -> str:
    return f"{surface}:{scope}"


def empty_scan_response(*, surface: str = DEFAULT_SURFACE) -> FullScanResponse:
    return FullScanResponse(
        surface=surface,
        sport="all",
        sides=[],
        events_fetched=0,
        events_with_both_books=0,
        api_requests_remaining=None,
        scanned_at=None,
        diagnostics=None,
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
    surface: str = DEFAULT_SURFACE,
    scope: str = "latest",
) -> None:
    cache_key = build_scan_cache_key(surface, scope)
    try:
        retry_supabase(
            lambda: (
                db.table("global_scan_cache")
                .upsert({"key": cache_key, "surface": surface, "payload": payload}, on_conflict="key")
                .execute()
            )
        )
    except Exception as e:
        log_event(
            "scan_latest_cache.persist_failed",
            level="warning",
            surface=surface,
            cache_key=cache_key,
            error_class=type(e).__name__,
            error=str(e),
        )


def load_latest_scan_payload(
    *,
    db,
    retry_supabase: Callable,
    surface: str = DEFAULT_SURFACE,
    scope: str = "latest",
) -> dict[str, Any] | None:
    cache_key = build_scan_cache_key(surface, scope)
    try:
        res = retry_supabase(
            lambda: (
                db.table("global_scan_cache")
                .select("payload")
                .eq("key", cache_key)
                .limit(1)
                .execute()
            )
        )
    except Exception as e:
        if is_missing_scan_cache_error(e):
            return None
        raise

    rows = getattr(res, "data", None) or []
    if not rows:
        if surface != DEFAULT_SURFACE:
            return None
        try:
            legacy = retry_supabase(
                lambda: (
                    db.table("global_scan_cache")
                    .select("payload")
                    .eq("key", scope)
                    .limit(1)
                    .execute()
                )
            )
        except Exception as e:
            if is_missing_scan_cache_error(e):
                return None
            raise
        rows = getattr(legacy, "data", None) or []
        if not rows:
            return None

    payload = rows[0].get("payload") if isinstance(rows[0], dict) else None
    if not isinstance(payload, dict):
        raise ValueError("Invalid scan cache payload")
    return payload


def persist_latest_full_scan(
    *,
    db,
    surface: str = DEFAULT_SURFACE,
    sport: str,
    sides: list[dict[str, Any]],
    events_fetched: int,
    events_with_both_books: int,
    api_requests_remaining: str | None,
    scanned_at: str | None,
    diagnostics: dict[str, Any] | None = None,
    retry_supabase: Callable,
    log_event: Callable[..., None],
) -> None:
    normalized_sides = [
        side if isinstance(side, dict) and side.get("surface") else {"surface": surface, **side}
        for side in sides
    ]
    payload = FullScanResponse(
        surface=surface,
        sport=sport,
        sides=normalized_sides,
        events_fetched=events_fetched,
        events_with_both_books=events_with_both_books,
        api_requests_remaining=api_requests_remaining,
        scanned_at=scanned_at,
        diagnostics=diagnostics,
    ).model_dump()
    persist_latest_scan_payload(
        db=db,
        payload=payload,
        retry_supabase=retry_supabase,
        log_event=log_event,
        surface=surface,
    )


def with_enriched_scan_sides(
    *,
    payload: dict[str, Any],
    enrich_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    result = dict(payload)
    sides_raw = payload.get("sides")
    sides = sides_raw if isinstance(sides_raw, list) else []
    result["sides"] = enrich_sides(sides)
    return result


def load_and_enrich_latest_scan_payload(
    *,
    db,
    retry_supabase: Callable,
    enrich_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    surface: str = DEFAULT_SURFACE,
) -> dict[str, Any] | None:
    payload = load_latest_scan_payload(db=db, retry_supabase=retry_supabase, surface=surface)
    if payload is None:
        return None
    return with_enriched_scan_sides(payload=payload, enrich_sides=enrich_sides)


def resolve_scan_latest_response(
    *,
    db,
    retry_supabase: Callable,
    enrich_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    surface: str = DEFAULT_SURFACE,
) -> dict[str, Any] | FullScanResponse:
    payload = load_and_enrich_latest_scan_payload(
        db=db,
        retry_supabase=retry_supabase,
        enrich_sides=enrich_sides,
        surface=surface,
    )
    if payload is None:
        return empty_scan_response(surface=surface)
    return payload


def scan_cache_exception_to_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, ValueError):
        return HTTPException(status_code=500, detail=str(error))
    return HTTPException(status_code=502, detail=f"Failed to load scan cache: {error}")
