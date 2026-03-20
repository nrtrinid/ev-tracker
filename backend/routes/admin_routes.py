from typing import Any, Callable


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