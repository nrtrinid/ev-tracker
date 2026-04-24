import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException

from database import get_db
from dependencies import require_scan_rate_limit
from models import FullScanResponse, ScanResponse
from services.analytics_events import capture_backend_event
from services.ops_runtime import persist_ops_job_run, set_ops_status
from services.runtime_support import log_event, new_run_id, retry_supabase, utc_now_iso
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
from services.scan_runtime import (
    annotate_sides_with_duplicate_state,
    append_scan_activity,
    build_full_scan_response,
    build_scan_response,
    capture_model_candidate_observations,
    capture_research_opportunities,
    get_cached_or_scan_for_surface,
    get_environment,
    persist_latest_full_scan,
    piggyback_clv,
    scan_for_ev_surface,
    scanner_supported_sports,
    sync_pickem_research_from_props_payload,
)
from utils.request_context import get_request_id


router = APIRouter()


SUPPORTED_SURFACES = {"straight_bets", "player_props"}


def _invoke_scan_followup(fn, sides: list[dict[str, object]]) -> object:
    """Call follow-up hooks with optional source kwarg for backward compatibility."""
    try:
        return fn(sides, source="manual_scan")
    except TypeError as exc:
        if "source" not in str(exc):
            raise
        return fn(sides)


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
    capture_model_candidate_observations=None,
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
        captured_at = utc_now_iso()
        response_payload = apply_manual_scan_bundle_fn(
            bundle=bundle,
            captured_at=captured_at,
            set_last_manual_scan_status=lambda status: set_ops_status(
                "last_manual_scan",
                {**status, "scan_session_id": scan_session_id},
            ),
            schedule_piggyback=lambda sides: _invoke_scan_followup(piggyback_clv, sides),
            schedule_research_capture=lambda sides: _invoke_scan_followup(capture_research_opportunities, sides),
            schedule_candidate_observation_capture=(
                (
                    lambda candidate_sets: capture_model_candidate_observations(
                        candidate_sets,
                        source="manual_scan",
                        captured_at=captured_at,
                    )
                )
                if capture_model_candidate_observations is not None
                else None
            ),
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
            captured_at=captured_at,
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
            user_email=str(user.get("email") or ""),
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
    return await scan_impl(
        sport=sport,
        supported_sports=scanner_supported_sports(DEFAULT_SURFACE),
        scan_for_ev=scan_for_ev_surface,
        map_error=scan_exception_to_http_exception,
        build_scan_response=lambda result: build_scan_response(sport=sport, result=result),
    )


@router.get("/api/scan-markets", response_model=FullScanResponse)
async def scan_markets(
    sport: str | None = None,
    surface: str = DEFAULT_SURFACE,
    user: dict = Depends(require_scan_rate_limit),
    session_id: str | None = Header(default=None, alias="X-Session-ID"),
):
    return await scan_markets_impl(
        surface=surface,
        sport=sport,
        user=user,
        session_id=session_id,
        get_db=get_db,
        supported_sports=scanner_supported_sports(surface),
        get_cached_or_scan=lambda sport_key, source="manual_scan": get_cached_or_scan_for_surface(surface, sport_key, source=source),
        apply_manual_scan_bundle_fn=apply_manual_scan_bundle,
        set_ops_status=set_ops_status,
        utc_now_iso=utc_now_iso,
        piggyback_clv=piggyback_clv,
        capture_research_opportunities=capture_research_opportunities,
        persist_latest_full_scan=persist_latest_full_scan,
        retry_supabase=retry_supabase,
        log_event=log_event,
        annotate_sides=annotate_sides_with_duplicate_state,
        append_scan_activity=append_scan_activity,
        persist_ops_job_run=persist_ops_job_run,
        new_run_id=new_run_id,
        sync_pickem_research_from_props_payload=sync_pickem_research_from_props_payload,
        capture_model_candidate_observations=capture_model_candidate_observations,
        map_error=scan_exception_to_http_exception,
        build_full_scan_response=build_full_scan_response,
        get_environment=get_environment,
    )


@router.get("/api/scan-latest", response_model=FullScanResponse)
async def scan_latest(
    surface: str = DEFAULT_SURFACE,
    user: dict = Depends(require_scan_rate_limit),
):
    return scan_latest_impl(
        surface=surface,
        user=user,
        get_db=get_db,
        retry_supabase=retry_supabase,
        annotate_sides=annotate_sides_with_duplicate_state,
    )
