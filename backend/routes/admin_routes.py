from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from dependencies import require_admin_user
from models import (
    AdminMarketRefreshResponse,
    AdminMarketRefreshSurfaceSummary,
    FullScanResponse,
    ResearchOpportunitySummaryResponse,
)
from routes.scan_routes import SUPPORTED_SURFACES, scan_markets_impl
from services.scan_markets import apply_manual_scan_bundle, scan_exception_to_http_exception


router = APIRouter()


def backfill_ev_locks_impl(
    *,
    user: dict,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict[str, Any]],
    retry_supabase: Callable[[Callable[[], Any]], Any],
    ev_lock_promo_types: list[str] | set[str] | tuple[str, ...],
    lock_ev_for_row: Callable[[Any, str, str, dict[str, Any], dict[str, Any]], None],
    log_warning: Callable[..., None],
) -> dict[str, int]:
    db = get_db()
    settings = get_user_settings(db, user["id"])

    res = retry_supabase(lambda: (
        db.table("bets")
        .select("*")
        .eq("user_id", user["id"])
        .is_("ev_locked_at", "null")
        .in_("promo_type", list(ev_lock_promo_types))
        .execute()
    ))
    rows = res.data or []

    locked = 0
    for row in rows:
        try:
            lock_ev_for_row(db, row["id"], user["id"], row, settings)
            locked += 1
        except Exception as e:
            log_warning("backfill_ev_lock.failed bet_id=%s err=%s", row["id"], e)

    return {"backfilled": locked, "total_eligible": len(rows)}


def summarize_full_scan_for_admin(resp: FullScanResponse) -> AdminMarketRefreshSurfaceSummary:
    return AdminMarketRefreshSurfaceSummary(
        surface=resp.surface,
        sport=resp.sport,
        events_fetched=resp.events_fetched,
        events_with_both_books=resp.events_with_both_books,
        total_sides=len(resp.sides),
        scanned_at=resp.scanned_at,
        api_requests_remaining=resp.api_requests_remaining,
    )


async def admin_refresh_markets_impl(
    *,
    surfaces: list[str],
    user: dict,
    run_scan: Callable[[str], Awaitable[FullScanResponse]],
) -> AdminMarketRefreshResponse:
    results: list[AdminMarketRefreshSurfaceSummary] = []
    for surf in surfaces:
        full = await run_scan(surf)
        results.append(summarize_full_scan_for_admin(full))
    return AdminMarketRefreshResponse(results=results)


def research_opportunities_summary_impl(
    *,
    get_db: Callable[[], Any],
    get_summary: Callable[[Any], ResearchOpportunitySummaryResponse],
) -> ResearchOpportunitySummaryResponse:
    return get_summary(get_db())


@router.post("/admin/backfill-ev-locks")
def backfill_ev_locks(user: dict = Depends(require_admin_user)):
    import main

    return backfill_ev_locks_impl(
        user=user,
        get_db=main.get_db,
        get_user_settings=main.get_user_settings,
        retry_supabase=main._retry_supabase,
        ev_lock_promo_types=main.EV_LOCK_PROMO_TYPES,
        lock_ev_for_row=main._lock_ev_for_row,
        log_warning=main.logger.warning,
    )


_ADMIN_REFRESH_QUERY = Query(
    default=None,
    description="If set, refresh only this surface (straight_bets or player_props). Otherwise both.",
)


async def _admin_refresh_markets_handler(
    surface: str | None,
    user: dict,
) -> AdminMarketRefreshResponse:
    """Run a full manual scan (all sports) without per-user scan rate limits. Admin only."""
    if surface is not None and surface not in SUPPORTED_SURFACES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported surface '{surface}'. Use: {', '.join(sorted(SUPPORTED_SURFACES))}",
        )
    surfaces = [surface] if surface is not None else ["straight_bets", "player_props"]

    import main

    async def _run_scan(surf: str) -> FullScanResponse:
        return await scan_markets_impl(
            surface=surf,
            sport=None,
            user=user,
            get_db=main.get_db,
            supported_sports=main._scanner_supported_sports(surf),
            get_cached_or_scan=lambda sport_key, source="manual_scan": main._get_cached_or_scan_for_surface(
                surf, sport_key, source=source
            ),
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
            map_error=scan_exception_to_http_exception,
            build_full_scan_response=main._build_full_scan_response,
            get_environment=main._get_environment,
        )

    return await admin_refresh_markets_impl(surfaces=surfaces, user=user, run_scan=_run_scan)


@router.post("/admin/refresh-markets", response_model=AdminMarketRefreshResponse)
async def admin_refresh_markets(
    surface: str | None = _ADMIN_REFRESH_QUERY,
    user: dict = Depends(require_admin_user),
):
    return await _admin_refresh_markets_handler(surface, user)


# Alias under /api/* so proxies and clients match scan-markets-style paths.
@router.post("/api/admin/refresh-markets", response_model=AdminMarketRefreshResponse)
async def admin_refresh_markets_api(
    surface: str | None = _ADMIN_REFRESH_QUERY,
    user: dict = Depends(require_admin_user),
):
    return await _admin_refresh_markets_handler(surface, user)


@router.get("/admin/research-opportunities/summary", response_model=ResearchOpportunitySummaryResponse)
def research_opportunities_summary(_user: dict = Depends(require_admin_user)):
    import main
    from services.research_opportunities import get_research_opportunities_summary

    return research_opportunities_summary_impl(
        get_db=main.get_db,
        get_summary=get_research_opportunities_summary,
    )
