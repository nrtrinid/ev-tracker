from fastapi import APIRouter, Depends, HTTPException

from dependencies import require_scan_rate_limit
from models import FullScanResponse, ScanResponse


router = APIRouter()


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
    sport: str | None,
    user: dict,
    get_db,
    supported_sports: list[str],
    get_cached_or_scan,
    run_single_sport_manual_scan,
    run_all_sports_manual_scan,
    apply_manual_scan_bundle,
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

    if sport is not None and sport not in supported_sports:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(supported_sports)}",
        )

    def _finalize_manual_scan_bundle(bundle: dict):
        response_payload = apply_manual_scan_bundle(
            bundle=bundle,
            captured_at=utc_now_iso(),
            set_last_manual_scan_status=lambda status: set_ops_status("last_manual_scan", status),
            schedule_piggyback=lambda sides: piggyback_clv(sides),
            persist_latest_scan=lambda payload: persist_latest_full_scan(
                db=db,
                **payload,
                retry_supabase=retry_supabase,
                log_event=log_event,
            ),
        )
        return build_full_scan_response(response_payload)

    try:
        if sport is not None:
            single_sport = await run_single_sport_manual_scan(
                sport=sport,
                get_cached_or_scan=lambda sport_key: get_cached_or_scan(sport_key, source="manual_scan"),
                annotate_sides=lambda sides: annotate_sides(db, user["id"], sides),
            )
            return _finalize_manual_scan_bundle(single_sport)

        all_sports = await run_all_sports_manual_scan(
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
    user: dict,
    get_db,
    resolve_scan_latest_response,
    retry_supabase,
    annotate_sides,
    map_error,
):
    db = get_db()
    try:
        return resolve_scan_latest_response(
            db=db,
            retry_supabase=retry_supabase,
            enrich_sides=lambda sides: annotate_sides(db, user["id"], sides),
        )
    except Exception as e:
        raise map_error(e)


@router.get("/api/scan-bets", response_model=ScanResponse)
async def scan_bets(
    sport: str = "basketball_nba",
    user: dict = Depends(require_scan_rate_limit),
):
    import main

    return await main.scan_bets(sport=sport, user=user)


@router.get("/api/scan-markets", response_model=FullScanResponse)
async def scan_markets(
    sport: str | None = None,
    user: dict = Depends(require_scan_rate_limit),
):
    import main

    return await main.scan_markets(sport=sport, user=user)


@router.get("/api/scan-latest", response_model=FullScanResponse)
async def scan_latest(user: dict = Depends(require_scan_rate_limit)):
    import main

    return await main.scan_latest(user=user)
