from fastapi import APIRouter, Depends, HTTPException

from dependencies import require_scan_rate_limit
from models import FullScanResponse, ScanResponse
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


router = APIRouter()


SUPPORTED_SURFACES = {"straight_bets"}


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
    get_db,
    supported_sports: list[str],
    get_cached_or_scan,
    apply_manual_scan_bundle_fn,
    set_ops_status,
    utc_now_iso,
    piggyback_clv,
    persist_latest_full_scan,
    retry_supabase,
    log_event,
    annotate_sides,
    map_error,
    build_full_scan_response,
    get_environment,
):
    db = get_db()

    if surface not in SUPPORTED_SURFACES:
        raise HTTPException(status_code=400, detail=f"Unsupported surface '{surface}'")

    if sport is not None and sport not in supported_sports:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(supported_sports)}",
        )

    def _finalize_manual_scan_bundle(bundle: dict):
        response_payload = apply_manual_scan_bundle_fn(
            bundle=bundle,
            captured_at=utc_now_iso(),
            set_last_manual_scan_status=lambda status: set_ops_status("last_manual_scan", status),
            schedule_piggyback=lambda sides: piggyback_clv(sides) if surface == DEFAULT_SURFACE else None,
            persist_latest_scan=lambda payload: persist_latest_full_scan(
                db=db,
                retry_supabase=retry_supabase,
                log_event=log_event,
                **payload,
            ),
        )
        return build_full_scan_response(response_payload)

    try:
        if sport is not None:
            single_sport = await run_single_sport_manual_scan(
                surface=surface,
                sport=sport,
                get_cached_or_scan=lambda sport_key: get_cached_or_scan(sport_key, source="manual_scan"),
                annotate_sides=lambda sides: annotate_sides(db, user["id"], sides),
            )
            return _finalize_manual_scan_bundle(single_sport)

        all_sports = await run_all_sports_manual_scan(
            surface=surface,
            environment=get_environment(),
            supported_sports=supported_sports,
            get_cached_or_scan=lambda sport_key: get_cached_or_scan(sport_key, source="manual_scan"),
            annotate_sides=lambda sides: annotate_sides(db, user["id"], sides),
        )
        return _finalize_manual_scan_bundle(all_sports)
    except Exception as e:
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
):
    import main

    return await scan_markets_impl(
        surface=surface,
        sport=sport,
        user=user,
        get_db=main.get_db,
        supported_sports=main._scanner_supported_sports(surface),
        get_cached_or_scan=lambda sport_key, source="manual_scan": main._get_cached_or_scan_for_surface(surface, sport_key, source=source),
        apply_manual_scan_bundle_fn=apply_manual_scan_bundle,
        set_ops_status=main._set_ops_status,
        utc_now_iso=main._utc_now_iso,
        piggyback_clv=main._piggyback_clv,
        persist_latest_full_scan=main._persist_latest_full_scan,
        retry_supabase=main._retry_supabase,
        log_event=main._log_event,
        annotate_sides=main._annotate_sides_with_duplicate_state,
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
