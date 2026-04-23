from calculations import american_to_decimal
from services.match_keys import (
    normalize_text,
    scanner_legacy_match_key_from_bet,
    scanner_legacy_match_key_from_side,
    scanner_match_key_from_bet,
    scanner_match_key_from_side,
    team_from_bet_row,
)


def _canonical_market_key(value: object | None) -> str:
    raw = normalize_text(str(value or ""))
    if raw in {"ml", "moneyline", "h2h"}:
        return "h2h"
    if raw in {"spread", "spreads"}:
        return "spreads"
    if raw in {"total", "totals"}:
        return "totals"
    return raw


def _event_ref(event_id: object | None, commence_time: object | None) -> str:
    normalized_id = normalize_text(str(event_id or ""))
    if normalized_id:
        return f"id:{normalized_id}"
    commence = str(commence_time or "").strip()
    if commence:
        return f"time:{commence}"
    return ""


def _line_token(value: object | None) -> str:
    if value is None or str(value).strip() == "":
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return normalize_text(str(value))
    if abs(numeric) < 1e-9:
        numeric = 0.0
    return f"{numeric:.4f}".rstrip("0").rstrip(".")


def _selection_tokens(*values: object | None) -> list[str]:
    tokens: list[str] = []
    for value in values:
        normalized = normalize_text(str(value or ""))
        if normalized and normalized not in tokens:
            tokens.append(normalized)
    return tokens


def _append_unique(mapping: dict, key: tuple, row: dict) -> None:
    rows = mapping.setdefault(key, [])
    row_id = row.get("id")
    if row_id is not None and any(existing.get("id") == row_id for existing in rows):
        return
    rows.append(row)


def _merge_unique(rows: list[dict], additions: list[dict]) -> list[dict]:
    seen = {row.get("id") for row in rows if row.get("id") is not None}
    merged = [*rows]
    for row in additions:
        row_id = row.get("id")
        if row_id is not None and row_id in seen:
            continue
        merged.append(row)
        if row_id is not None:
            seen.add(row_id)
    return merged


def _price_quality_from_american(american: float | int | None) -> float | None:
    if american is None:
        return None
    try:
        return american_to_decimal(float(american))
    except Exception:
        return None


def _straight_source_key_from_side(side: dict, *, include_book: bool) -> tuple[str, ...] | None:
    sport = normalize_text(str(side.get("sport") or ""))
    selection_key = normalize_text(str(side.get("selection_key") or side.get("source_selection_key") or ""))
    sportsbook = normalize_text(str(side.get("sportsbook") or ""))
    if not sport or not selection_key:
        return None
    if include_book:
        if not sportsbook:
            return None
        return (sport, selection_key, sportsbook)
    return (sport, selection_key)


def _straight_source_key_from_bet(row: dict, *, include_book: bool) -> tuple[str, ...] | None:
    sport = normalize_text(str(row.get("clv_sport_key") or row.get("sport") or ""))
    selection_key = normalize_text(str(row.get("source_selection_key") or ""))
    sportsbook = normalize_text(str(row.get("sportsbook") or ""))
    if not sport or not selection_key:
        return None
    if include_book:
        if not sportsbook:
            return None
        return (sport, selection_key, sportsbook)
    return (sport, selection_key)


def _straight_field_keys_from_side(side: dict, *, include_book: bool) -> list[tuple[str, ...]]:
    sport = normalize_text(str(side.get("sport") or ""))
    event_ref = _event_ref(side.get("event_id"), side.get("commence_time"))
    market_key = _canonical_market_key(side.get("market_key") or side.get("market") or "h2h")
    sportsbook = normalize_text(str(side.get("sportsbook") or ""))
    if not sport or not event_ref or not market_key:
        return []
    if include_book and not sportsbook:
        return []

    line = _line_token(side.get("line_value")) if market_key in {"spreads", "totals"} else ""
    if market_key in {"spreads", "totals"} and not line:
        return []

    tokens = _selection_tokens(side.get("selection_side"), side.get("team"))
    keys: list[tuple[str, ...]] = []
    for token in tokens:
        base = (sport, event_ref, market_key, token, line)
        keys.append((*base, sportsbook) if include_book else base)
    return keys


def _straight_field_keys_from_bet(row: dict, *, include_book: bool) -> list[tuple[str, ...]]:
    sport = normalize_text(str(row.get("clv_sport_key") or row.get("sport") or ""))
    event_ref = _event_ref(row.get("source_event_id") or row.get("clv_event_id"), row.get("commence_time"))
    market_key = _canonical_market_key(row.get("source_market_key") or row.get("market") or "h2h")
    sportsbook = normalize_text(str(row.get("sportsbook") or ""))
    if not sport or not event_ref or not market_key:
        return []
    if include_book and not sportsbook:
        return []

    line = _line_token(row.get("line_value")) if market_key in {"spreads", "totals"} else ""
    if market_key in {"spreads", "totals"} and not line:
        return []

    tokens = _selection_tokens(row.get("selection_side"), team_from_bet_row(row))
    keys: list[tuple[str, ...]] = []
    for token in tokens:
        base = (sport, event_ref, market_key, token, line)
        keys.append((*base, sportsbook) if include_book else base)
    return keys


def _collect_straight_matches(
    side: dict,
    matches_by_source_key: dict[tuple[str, ...], list[dict]],
    cross_book_matches_by_source_key: dict[tuple[str, ...], list[dict]],
    matches_by_field_key: dict[tuple[str, ...], list[dict]],
    cross_book_matches_by_field_key: dict[tuple[str, ...], list[dict]],
    legacy_matches_by_key: dict[tuple[str, str, str, str, str], list[dict]],
    legacy_cross_book_matches_by_key: dict[tuple[str, str, str, str], list[dict]],
) -> tuple[list[dict], list[dict]]:
    matched: list[dict] = []
    cross_book_matched: list[dict] = []

    exact_source_key = _straight_source_key_from_side(side, include_book=True)
    if exact_source_key is not None:
        matched = _merge_unique(matched, matches_by_source_key.get(exact_source_key, []))

    cross_source_key = _straight_source_key_from_side(side, include_book=False)
    if cross_source_key is not None:
        cross_book_matched = _merge_unique(
            cross_book_matched,
            cross_book_matches_by_source_key.get(cross_source_key, []),
        )

    for key in _straight_field_keys_from_side(side, include_book=True):
        matched = _merge_unique(matched, matches_by_field_key.get(key, []))
    for key in _straight_field_keys_from_side(side, include_book=False):
        cross_book_matched = _merge_unique(cross_book_matched, cross_book_matches_by_field_key.get(key, []))

    legacy_key = scanner_match_key_from_side(side)
    legacy_time_key = scanner_legacy_match_key_from_side(side)
    matched = _merge_unique(matched, legacy_matches_by_key.get(legacy_key, []))
    matched = _merge_unique(matched, legacy_matches_by_key.get(legacy_time_key, []))
    cross_book_matched = _merge_unique(
        cross_book_matched,
        legacy_cross_book_matches_by_key.get(legacy_key[:4], []),
    )
    cross_book_matched = _merge_unique(
        cross_book_matched,
        legacy_cross_book_matches_by_key.get(legacy_time_key[:4], []),
    )

    side_book = normalize_text(str(side.get("sportsbook") or ""))
    if side_book:
        cross_book_matched = [
            row
            for row in cross_book_matched
            if normalize_text(str(row.get("sportsbook") or "")) != side_book
        ]

    return matched, cross_book_matched


def _best_priced_pending_row(rows: list[dict]) -> tuple[dict | None, float | None]:
    best_row = None
    best_quality = None
    for row in rows:
        q = _price_quality_from_american(row.get("odds_american"))
        if q is None:
            continue
        if best_quality is None or q > best_quality:
            best_quality = q
            best_row = row
    return best_row, best_quality


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

    matches_by_source_key: dict[tuple[str, ...], list[dict]] = {}
    cross_book_matches_by_source_key: dict[tuple[str, ...], list[dict]] = {}
    matches_by_field_key: dict[tuple[str, ...], list[dict]] = {}
    cross_book_matches_by_field_key: dict[tuple[str, ...], list[dict]] = {}
    legacy_matches_by_key: dict[tuple[str, str, str, str, str], list[dict]] = {}
    legacy_cross_book_matches_by_key: dict[tuple[str, str, str, str], list[dict]] = {}
    prop_matches_by_selection_key: dict[tuple[str, str, str], list[dict]] = {}
    prop_cross_book_matches_by_selection_key: dict[tuple[str, str], list[dict]] = {}
    for row in pending_res.data or []:
        if row.get("surface") == "player_props":
            selection_key = str(row.get("source_selection_key") or "").strip().lower()
            market_key = str(row.get("source_market_key") or "").strip().lower()
            sportsbook = str(row.get("sportsbook") or "").strip().lower()
            if selection_key and market_key:
                _append_unique(prop_cross_book_matches_by_selection_key, (market_key, selection_key), row)
            if selection_key and market_key and sportsbook:
                _append_unique(prop_matches_by_selection_key, (market_key, selection_key, sportsbook), row)
            continue
        if surfaces == ["player_props"]:
            continue

        source_key = _straight_source_key_from_bet(row, include_book=True)
        if source_key is not None:
            _append_unique(matches_by_source_key, source_key, row)
        cross_source_key = _straight_source_key_from_bet(row, include_book=False)
        if cross_source_key is not None:
            _append_unique(cross_book_matches_by_source_key, cross_source_key, row)

        for key in _straight_field_keys_from_bet(row, include_book=True):
            _append_unique(matches_by_field_key, key, row)
        for key in _straight_field_keys_from_bet(row, include_book=False):
            _append_unique(cross_book_matches_by_field_key, key, row)

        if str(row.get("market") or "").strip().upper() == "ML":
            key = scanner_match_key_from_bet(row)
            legacy_key = scanner_legacy_match_key_from_bet(row)
            if all([key[0], key[1], key[2], key[3], key[4]]):
                _append_unique(legacy_matches_by_key, key, row)
                _append_unique(legacy_matches_by_key, legacy_key, row)
                _append_unique(legacy_cross_book_matches_by_key, key[:4], row)
                _append_unique(legacy_cross_book_matches_by_key, legacy_key[:4], row)

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
            side_book = normalize_text(str(side.get("sportsbook") or ""))
            cross_book_matched = [
                row
                for row in prop_cross_book_matches_by_selection_key.get(cross_book_prop_key, [])
                if not side_book or normalize_text(str(row.get("sportsbook") or "")) != side_book
            ]
        else:
            matched, cross_book_matched = _collect_straight_matches(
                side,
                matches_by_source_key,
                cross_book_matches_by_source_key,
                matches_by_field_key,
                cross_book_matches_by_field_key,
                legacy_matches_by_key,
                legacy_cross_book_matches_by_key,
            )
        current_odds = side.get("book_odds")
        current_quality = _price_quality_from_american(current_odds)
        side_out["current_odds_american"] = current_odds

        if not matched:
            if cross_book_matched:
                best_row, _best_quality = _best_priced_pending_row(cross_book_matched)

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

        best_row, best_quality = _best_priced_pending_row(matched)

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
