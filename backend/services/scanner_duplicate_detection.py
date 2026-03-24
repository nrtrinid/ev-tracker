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
    State enum: new | logged_elsewhere | already_logged | better_now
    """
    if not sides:
        return sides

    surfaces = sorted({str(side.get("surface") or "straight_bets") for side in sides})
    pending_res = (
        db.table("bets")
        .select("id,odds_american,sport,market,surface,sportsbook,commence_time,clv_team,event,clv_sport_key,clv_event_id,source_event_id,source_market_key,source_selection_key,result")
        .eq("user_id", user_id)
        .eq("result", "pending")
        .execute()
    )

    matches_by_key: dict[tuple[str, str, str, str, str], list[dict]] = {}
    cross_book_matches_by_key: dict[tuple[str, str, str, str], list[dict]] = {}
    prop_matches_by_selection_key: dict[tuple[str, str, str], list[dict]] = {}
    prop_cross_book_matches_by_selection_key: dict[tuple[str, str], list[dict]] = {}
    for row in pending_res.data or []:
        if row.get("surface") == "player_props":
            selection_key = str(row.get("source_selection_key") or "").strip().lower()
            market_key = str(row.get("source_market_key") or "").strip().lower()
            sportsbook = str(row.get("sportsbook") or "").strip().lower()
            if selection_key and market_key:
                prop_cross_book_matches_by_selection_key.setdefault((market_key, selection_key), []).append(row)
            if selection_key and market_key and sportsbook:
                prop_matches_by_selection_key.setdefault((market_key, selection_key, sportsbook), []).append(row)
            continue
        if surfaces == ["player_props"]:
            continue
        if str(row.get("market") or "").strip().upper() != "ML":
            continue
        key = scanner_match_key_from_bet(row)
        legacy_key = scanner_legacy_match_key_from_bet(row)
        if not all([key[0], key[1], key[2], key[3], key[4]]):
            continue
        matches_by_key.setdefault(key, []).append(row)
        matches_by_key.setdefault(legacy_key, []).append(row)
        cross_book_matches_by_key.setdefault(key[:4], []).append(row)
        cross_book_matches_by_key.setdefault(legacy_key[:4], []).append(row)

    annotated: list[dict] = []
    for side in sides:
        side_out = dict(side)
        if side.get("surface") == "player_props":
            prop_key = (
                str(side.get("market_key") or "").strip().lower(),
                str(side.get("selection_key") or "").strip().lower(),
                str(side.get("sportsbook") or "").strip().lower(),
            )
            cross_book_prop_key = prop_key[:2]
            matched = prop_matches_by_selection_key.get(prop_key, [])
            cross_book_matched = prop_cross_book_matches_by_selection_key.get(cross_book_prop_key, [])
        else:
            key = scanner_match_key_from_side(side)
            legacy_key = scanner_legacy_match_key_from_side(side)
            matched = matches_by_key.get(key, [])
            if not matched:
                matched = matches_by_key.get(legacy_key, [])
            cross_book_matched = cross_book_matches_by_key.get(key[:4], [])
            if not cross_book_matched:
                cross_book_matched = cross_book_matches_by_key.get(legacy_key[:4], [])
        current_odds = side.get("book_odds")
        current_quality = _price_quality_from_american(current_odds)
        side_out["current_odds_american"] = current_odds

        if not matched:
            if cross_book_matched:
                best_row = None
                best_quality = None
                for row in cross_book_matched:
                    q = _price_quality_from_american(row.get("odds_american"))
                    if q is None:
                        continue
                    if best_quality is None or q > best_quality:
                        best_quality = q
                        best_row = row

                side_out["scanner_duplicate_state"] = "logged_elsewhere"
                side_out["best_logged_odds_american"] = best_row.get("odds_american") if best_row else None
                side_out["matched_pending_bet_id"] = (
                    best_row.get("id") if best_row is not None else cross_book_matched[0].get("id")
                )
                annotated.append(side_out)
                continue
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
