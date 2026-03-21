from calculations import american_to_decimal
from services.match_keys import (
    scanner_legacy_match_key_from_bet,
    scanner_legacy_match_key_from_side,
    scanner_match_key_from_bet,
    scanner_match_key_from_side,
)


def _price_quality_from_american(american: float | int | None) -> float | None:
    if american is None:
        return None
    try:
        return american_to_decimal(float(american))
    except Exception:
        return None


def annotate_sides_with_duplicate_state(db, user_id: str, sides: list[dict]) -> list[dict]:
    """
    Backend-owned scanner duplicate state.

    Matching scope: pending (unsettled exposure) only.
    State enum: new | already_logged | better_now
    """
    if not sides:
        return sides

    pending_res = (
        db.table("bets")
        .select("id,odds_american,sport,market,sportsbook,commence_time,clv_team,event,clv_sport_key,clv_event_id,result")
        .eq("user_id", user_id)
        .eq("result", "pending")
        .eq("market", "ML")
        .execute()
    )

    matches_by_key: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for row in pending_res.data or []:
        key = scanner_match_key_from_bet(row)
        legacy_key = scanner_legacy_match_key_from_bet(row)
        if not all([key[0], key[1], key[2], key[3], key[4]]):
            continue
        matches_by_key.setdefault(key, []).append(row)
        matches_by_key.setdefault(legacy_key, []).append(row)

    annotated: list[dict] = []
    for side in sides:
        side_out = dict(side)
        key = scanner_match_key_from_side(side)
        legacy_key = scanner_legacy_match_key_from_side(side)
        matched = matches_by_key.get(key, [])
        if not matched:
            matched = matches_by_key.get(legacy_key, [])
        current_odds = side.get("book_odds")
        current_quality = _price_quality_from_american(current_odds)
        side_out["current_odds_american"] = current_odds

        if not matched:
            side_out["scanner_duplicate_state"] = "new"
            side_out["best_logged_odds_american"] = None
            side_out["matched_pending_bet_id"] = None
            annotated.append(side_out)
            continue

        best_row = None
        best_quality = None
        for row in matched:
            q = _price_quality_from_american(row.get("odds_american"))
            if q is None:
                continue
            if best_quality is None or q > best_quality:
                best_quality = q
                best_row = row

        if best_row is None:
            side_out["scanner_duplicate_state"] = "already_logged"
            side_out["best_logged_odds_american"] = None
            side_out["matched_pending_bet_id"] = matched[0].get("id") if matched else None
            annotated.append(side_out)
            continue

        side_out["best_logged_odds_american"] = best_row.get("odds_american")
        side_out["matched_pending_bet_id"] = best_row.get("id")
        if current_quality is not None and best_quality is not None and current_quality > best_quality:
            side_out["scanner_duplicate_state"] = "better_now"
        else:
            side_out["scanner_duplicate_state"] = "already_logged"
        annotated.append(side_out)

    return annotated