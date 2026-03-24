from typing import Any, Callable

from fastapi import APIRouter, Depends

from dependencies import require_admin_user
from models import ResearchOpportunitySummaryResponse


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


@router.get("/admin/research-opportunities/summary", response_model=ResearchOpportunitySummaryResponse)
def research_opportunities_summary(_user: dict = Depends(require_admin_user)):
    import main
    from services.research_opportunities import get_research_opportunities_summary

    return research_opportunities_summary_impl(
        get_db=main.get_db,
        get_summary=get_research_opportunities_summary,
    )
