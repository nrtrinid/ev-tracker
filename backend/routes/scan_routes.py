import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException

from dependencies import require_scan_rate_limit
from models import FullScanResponse, ScanResponse
from services.analytics_events import capture_backend_event
from services.scan_cache import (
    DEFAULT_SURFACE,
    resolve_scan_latest_response,
    scan_cache_exception_to_http_exception,
)
from services.scan_markets import (
    apply_manual_scan_bundle,
    run_all_sports_manual_scan,
    run_single_sport_manual_scan,
    scan_exception_to_http_exception,
)
from utils.request_context import get_request_id


router = APIRouter()


SUPPORTED_SURFACES = {"straight_bets", "player_props"}


async def scan_impl(
    *,
    sport: str,
    supported_sports: list[str],
    scan_for_ev,
    map_error,
    build_scan_response,
):
    if sport not in supported_sports:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(supported_sports)}",
        )

    try:
        result = await scan_for_ev(sport)
    except Exception as e:
        raise map_error(e)

    return build_scan_response(result)


async def scan_markets_impl(
    *,
    surface: str,
    sport: str | None,
    user: dict,
    session_id: str | None = None,
    get_db,
    supported_sports: list[str],
    get_cached_or_scan,
    apply_manual_scan_bundle_fn,
    set_ops_status,
    utc_now_iso,
    piggyback_clv,
    capture_research_opportunities,
    persist_latest_full_scan,
    retry_supabase,
    log_event,
    annotate_sides,
    append_scan_activity,
    persist_ops_job_run,
    new_run_id,
    sync_pickem_research_from_props_payload,
    map_error,
    build_full_scan_response,
    get_environment,
):
    if surface not in SUPPORTED_SURFACES:
        raise HTTPException(status_code=400, detail=f"Unsupported surface '{surface}'")

    db = get_db()
    scan_session_id = new_run_id("manual_scan")
    actor_label = str(user.get("email") or user.get("id") or "").strip() or None
    scan_scope = "all" if sport is None else "single_sport"

    async def _get_cached_or_scan_with_activity(sport_key: str) -> dict:
        started_at = time.monotonic()
        try:
            result = await get_cached_or_scan(sport_key, source="manual_scan")
            append_scan_activity(
                scan_session_id=scan_session_id,
                source="manual_scan",
                surface=surface,
                scan_scope=scan_scope,
                requested_sport=sport,
                sport=sport_key,
                actor_label=actor_label,
                run_id=None,
                cache_hit=bool(result.get("cache_hit")),
                outbound_call_made=not bool(result.get("cache_hit")),
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                events_fetched=int(result.get("events_fetched") or 0),
                events_with_both_books=int(result.get("events_with_both_books") or 0),
                sides_count=len(result.get("sides") or []),
                api_requests_remaining=result.get("api_requests_remaining"),
                status_code=200,
                error_type=None,
                error_message=None,
            )
            return result
        except httpx.HTTPStatusError as e:
            remaining = None
            status_code = e.response.status_code if e.response is not None else None
            if e.response is not None:
                remaining = e.response.headers.get("x-requests-remaining") or e.response.headers.get("x-request-remaining")
            append_scan_activity(
                scan_session_id=scan_session_id,
                source="manual_scan",
                surface=surface,
                scan_scope=scan_scope,
                requested_sport=sport,
                sport=sport_key,
                actor_label=actor_label,
                run_id=None,
                cache_hit=False,
                outbound_call_made=True,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                events_fetched=0,
                events_with_both_books=0,
                sides_count=0,
                api_requests_remaining=remaining,
                status_code=status_code,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            raise
        except Exception as e:
            append_scan_activity(
                scan_session_id=scan_session_id,
                source="manual_scan",
                surface=surface,
                scan_scope=scan_scope,
                requested_sport=sport,
                sport=sport_key,
                actor_label=actor_label,
                run_id=None,
                cache_hit=False,
                outbound_call_made=False,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                events_fetched=0,
                events_with_both_books=0,
                sides_count=0,
                api_requests_remaining=None,
                status_code=None,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            raise

    if sport is not None and sport not in supported_sports:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(supported_sports)}",
        )

    def _finalize_manual_scan_bundle(bundle: dict):
        response_payload = apply_manual_scan_bundle_fn(
            bundle=bundle,
            captured_at=utc_now_iso(),
            set_last_manual_scan_status=lambda status: set_ops_status(
                "last_manual_scan",
                {**status, "scan_session_id": scan_session_id},
            ),
            schedule_piggyback=lambda sides: piggyback_clv(sides, source="manual_scan"),
            schedule_research_capture=lambda sides: capture_research_opportunities(sides, source="manual_scan"),
            persist_latest_scan=lambda payload: persist_latest_full_scan(
                db=db,
                retry_supabase=retry_supabase,
                log_event=log_event,
                **payload,
            ),
        )
        persist_ops_job_run(
            job_kind="manual_scan",
            source="manual_scan",
            status="completed",
            scan_session_id=scan_session_id,
            surface=bundle["ops_status_payload"].get("surface"),
            scan_scope=scan_scope,
            requested_sport=bundle["ops_status_payload"].get("sport"),
            captured_at=utc_now_iso(),
            events_fetched=bundle["ops_status_payload"].get("events_fetched"),
            events_with_both_books=bundle["ops_status_payload"].get("events_with_both_books"),
            total_sides=bundle["ops_status_payload"].get("total_sides"),
            api_requests_remaining=bundle["ops_status_payload"].get("api_requests_remaining"),
        )
        if surface == "player_props" and bundle.get("fresh_sides"):
            sync_pickem_research_from_props_payload(
                bundle.get("persist_payload"),
                source="manual_scan",
            )
        return build_full_scan_response(response_payload)

    try:
        if sport is not None:
            single_sport = await run_single_sport_manual_scan(
                surface=surface,
                sport=sport,
                get_cached_or_scan=_get_cached_or_scan_with_activity,
                annotate_sides=lambda sides: annotate_sides(db, user["id"], sides),
            )
            return _finalize_manual_scan_bundle(single_sport)

        all_sports = await run_all_sports_manual_scan(
            surface=surface,
            environment=get_environment(),
            supported_sports=supported_sports,
            get_cached_or_scan=_get_cached_or_scan_with_activity,
            annotate_sides=lambda sides: annotate_sides(db, user["id"], sides),
        )
        return _finalize_manual_scan_bundle(all_sports)
    except Exception as e:
        capture_backend_event(
            db,
            event_name="scanner_failed",
            user_id=str(user.get("id") or ""),
            session_id=session_id,
            properties={
                "route": "/api/scan-markets",
                "app_area": "scanner",
                "surface": surface,
                "requested_sport": sport,
                "error_type": type(e).__name__,
            },
            dedupe_key=f"scanner-failed:{scan_session_id}:{get_request_id()}",
        )
        raise map_error(e)


def scan_latest_impl(
    *,
    surface: str,
    user: dict,
    get_db,
    retry_supabase,
    annotate_sides,
):
    if surface not in SUPPORTED_SURFACES:
        raise HTTPException(status_code=400, detail=f"Unsupported surface '{surface}'")

    db = get_db()
    try:
        payload = resolve_scan_latest_response(
            db=db,
            retry_supabase=retry_supabase,
            enrich_sides=lambda sides: annotate_sides(db, user["id"], sides),
            surface=surface,
        )
        if isinstance(payload, dict):
            payload["surface"] = payload.get("surface") or surface
            raw_sides = payload.get("sides")
            if isinstance(raw_sides, list):
                payload["sides"] = [
                    side if isinstance(side, dict) and side.get("surface") else {"surface": surface, **side}
                    for side in raw_sides
                ]
        return payload
    except Exception as e:
        raise scan_cache_exception_to_http_exception(e)


@router.get("/api/scan-bets", response_model=ScanResponse)
async def scan_bets(
    sport: str = "basketball_nba",
    user: dict = Depends(require_scan_rate_limit),
):
    import main

    return await scan_impl(
        sport=sport,
        supported_sports=main._scanner_supported_sports(DEFAULT_SURFACE),
        scan_for_ev=main._scan_for_ev_surface,
        map_error=scan_exception_to_http_exception,
        build_scan_response=lambda result: main._build_scan_response(sport=sport, result=result),
    )


@router.get("/api/scan-markets", response_model=FullScanResponse)
async def scan_markets(
    sport: str | None = None,
    surface: str = DEFAULT_SURFACE,
    user: dict = Depends(require_scan_rate_limit),
    session_id: str | None = Header(default=None, alias="X-Session-ID"),
):
    import main

    return await scan_markets_impl(
        surface=surface,
        sport=sport,
        user=user,
        session_id=session_id,
        get_db=main.get_db,
        supported_sports=main._scanner_supported_sports(surface),
        get_cached_or_scan=lambda sport_key, source="manual_scan": main._get_cached_or_scan_for_surface(surface, sport_key, source=source),
        apply_manual_scan_bundle_fn=apply_manual_scan_bundle,
        set_ops_status=main._set_ops_status,
        utc_now_iso=main._utc_now_iso,
        piggyback_clv=main._piggyback_clv,
        capture_research_opportunities=main._capture_research_opportunities,
        persist_latest_full_scan=main._persist_latest_full_scan,
        retry_supabase=main._retry_supabase,
        log_event=main._log_event,
        annotate_sides=main._annotate_sides_with_duplicate_state,
        append_scan_activity=main._append_scan_activity,
        persist_ops_job_run=main._persist_ops_job_run,
        new_run_id=main._new_run_id,
        sync_pickem_research_from_props_payload=main._sync_pickem_research_from_props_payload,
        map_error=scan_exception_to_http_exception,
        build_full_scan_response=main._build_full_scan_response,
        get_environment=main._get_environment,
    )


@router.get("/api/scan-latest", response_model=FullScanResponse)
async def scan_latest(
    surface: str = DEFAULT_SURFACE,
    user: dict = Depends(require_scan_rate_limit),
):
    import main

    return scan_latest_impl(
        surface=surface,
        user=user,
        get_db=main.get_db,
        retry_supabase=main._retry_supabase,
        annotate_sides=main._annotate_sides_with_duplicate_state,
    )
