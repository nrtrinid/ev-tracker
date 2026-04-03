from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from calculations import american_to_decimal
from services.scan_cache import load_latest_scan_payload


BOARD_VIEW_OPPORTUNITIES = "opportunities"
BOARD_VIEW_BROWSE = "browse"
BOARD_VIEW_PICKEM = "pickem"
BOARD_VIEWS = (BOARD_VIEW_OPPORTUNITIES, BOARD_VIEW_BROWSE, BOARD_VIEW_PICKEM)


def _artifact_meta_scope(view: str) -> str:
    return f"board_{view}_meta"


def _artifact_chunk_scope(view: str, index: int) -> str:
    return f"board_{view}_chunk_{index}"


def _legacy_surface_scope() -> str:
    return "board_legacy_surface"


def _detail_scope(selection_key: str, sportsbook: str) -> str:
    return f"board_detail_{build_player_prop_board_detail_key(selection_key, sportsbook)}"


def build_player_prop_board_detail_key(selection_key: str, sportsbook: str) -> str:
    return f"{str(selection_key or '').strip().lower()}::{str(sportsbook or '').strip().lower()}"


def _upsert_cache_rows(
    *,
    db,
    rows: list[dict[str, Any]],
    retry_supabase,
    log_event,
) -> None:
    if not rows:
        return
    try:
        retry_supabase(
            lambda: (
                db.table("global_scan_cache")
                .upsert(rows, on_conflict="key")
                .execute()
            )
        )
    except Exception as exc:
        log_event(
            "scan_latest_cache.persist_failed",
            level="warning",
            surface="player_props",
            cache_key="board_artifacts_batch",
            error_class=type(exc).__name__,
            error=str(exc),
        )


def _iter_chunk_items(items: list[dict[str, Any]], *, chunk_size: int):
    safe_chunk_size = max(1, chunk_size)
    if not items:
        yield []
        return
    for idx in range(0, len(items), safe_chunk_size):
        yield items[idx: idx + safe_chunk_size]


def _persist_cache_row(
    *,
    db,
    row: dict[str, Any],
    retry_supabase,
    log_event,
) -> None:
    _upsert_cache_rows(
        db=db,
        rows=[row],
        retry_supabase=retry_supabase,
        log_event=log_event,
    )


def _persist_chunked_rows(
    *,
    db,
    rows: list[dict[str, Any]],
    retry_supabase,
    log_event,
    batch_size: int,
) -> None:
    if not rows:
        return
    if batch_size <= 0:
        _upsert_cache_rows(
            db=db,
            rows=rows,
            retry_supabase=retry_supabase,
            log_event=log_event,
        )
        return
    for index in range(0, len(rows), batch_size):
        _upsert_cache_rows(
            db=db,
            rows=rows[index:index + batch_size],
            retry_supabase=retry_supabase,
            log_event=log_event,
        )


def _canonicalize(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 0:
        return (ordered[middle - 1] + ordered[middle]) / 2
    return ordered[middle]


def _confidence_label(book_count: int) -> str:
    if book_count >= 4:
        return "elite"
    if book_count >= 3:
        return "high"
    if book_count >= 2:
        return "solid"
    return "thin"


def _odds_quality(american_odds: float | int | None) -> float:
    if american_odds is None:
        return float("-inf")
    try:
        return american_to_decimal(float(american_odds))
    except Exception:
        return float("-inf")


def _ev_value(item: dict[str, Any]) -> float:
    try:
        return float(item.get("ev_percentage") or 0)
    except Exception:
        return 0.0


def is_player_prop_board_opportunity(item: dict[str, Any], *, min_ev: float = 1.0) -> bool:
    return _ev_value(item) > float(min_ev)


def matches_player_prop_board_item(
    item: dict[str, Any],
    *,
    books: list[str] | None = None,
    time_filter: str = "today",
    market: str | None = None,
    search: str | None = None,
    tz_offset_minutes: int | None = None,
    now_utc: datetime | None = None,
) -> bool:
    selected_books = {book.strip() for book in (books or []) if book.strip()}
    normalized_search = str(search or "").strip().lower()
    normalized_market = str(market or "").strip().lower()
    current_now = now_utc or datetime.now(UTC)

    if selected_books and str(item.get("sportsbook") or "") not in selected_books:
        return False
    if normalized_market and normalized_market != "all":
        if str(item.get("market_key") or "").strip().lower() != normalized_market:
            return False
    if not matches_board_time_filter(
        str(item.get("commence_time") or ""),
        time_filter,
        now_utc=current_now,
        tz_offset_minutes=tz_offset_minutes,
    ):
        return False
    if normalized_search:
        haystack = " ".join(
            [
                str(item.get("event") or ""),
                str(item.get("event_short") or ""),
                str(item.get("sport") or ""),
                str(item.get("sportsbook") or ""),
                str(item.get("player_name") or ""),
                str(item.get("team") or ""),
                str(item.get("team_short") or ""),
                str(item.get("opponent") or ""),
                str(item.get("opponent_short") or ""),
            ]
        ).lower()
        if normalized_search not in haystack:
            return False
    return True


def matches_player_prop_board_pickem_item(
    item: dict[str, Any],
    *,
    books: list[str] | None = None,
    time_filter: str = "today",
    market: str | None = None,
    search: str | None = None,
    tz_offset_minutes: int | None = None,
    now_utc: datetime | None = None,
) -> bool:
    selected_books = {book.strip() for book in (books or []) if book.strip()}
    normalized_search = str(search or "").strip().lower()
    normalized_market = str(market or "").strip().lower()
    current_now = now_utc or datetime.now(UTC)

    if normalized_market and normalized_market != "all":
        if str(item.get("market_key") or "").strip().lower() != normalized_market:
            return False
    if not matches_board_time_filter(
        str(item.get("commence_time") or ""),
        time_filter,
        now_utc=current_now,
        tz_offset_minutes=tz_offset_minutes,
    ):
        return False
    if selected_books:
        card_books = {str(book).strip() for book in item.get("exact_line_bookmakers") or [] if str(book).strip()}
        if not card_books.intersection(selected_books):
            return False
    if normalized_search:
        haystack = " ".join(
            [
                str(item.get("player_name") or ""),
                str(item.get("market") or ""),
                str(item.get("event") or ""),
                str(item.get("team") or ""),
                str(item.get("opponent") or ""),
                str(item.get("best_over_sportsbook") or ""),
                str(item.get("best_under_sportsbook") or ""),
                " ".join(str(book) for book in item.get("exact_line_bookmakers") or []),
            ]
        ).lower()
        if normalized_search not in haystack:
            return False
    return True


def build_player_prop_board_item(side: dict[str, Any]) -> dict[str, Any]:
    return {
        "surface": "player_props",
        "event_id": side.get("event_id"),
        "market_key": side.get("market_key"),
        "selection_key": side.get("selection_key"),
        "sportsbook": side.get("sportsbook"),
        "sportsbook_deeplink_url": side.get("sportsbook_deeplink_url"),
        "sportsbook_deeplink_level": side.get("sportsbook_deeplink_level"),
        "sport": side.get("sport"),
        "event": side.get("event"),
        "event_short": side.get("event_short"),
        "commence_time": side.get("commence_time"),
        "market": side.get("market"),
        "player_name": side.get("player_name"),
        "participant_id": side.get("participant_id"),
        "team": side.get("team"),
        "team_short": side.get("team_short"),
        "opponent": side.get("opponent"),
        "opponent_short": side.get("opponent_short"),
        "selection_side": side.get("selection_side"),
        "line_value": side.get("line_value"),
        "display_name": side.get("display_name"),
        "reference_odds": side.get("reference_odds"),
        "reference_source": side.get("reference_source"),
        "reference_bookmaker_count": side.get("reference_bookmaker_count"),
        "confidence_label": side.get("confidence_label"),
        "book_odds": side.get("book_odds"),
        "true_prob": side.get("true_prob"),
        "base_kelly_fraction": side.get("base_kelly_fraction"),
        "book_decimal": side.get("book_decimal"),
        "ev_percentage": side.get("ev_percentage"),
        "scanner_duplicate_state": side.get("scanner_duplicate_state"),
        "best_logged_odds_american": side.get("best_logged_odds_american"),
        "current_odds_american": side.get("current_odds_american"),
        "matched_pending_bet_id": side.get("matched_pending_bet_id"),
    }


def build_player_prop_board_detail(side: dict[str, Any]) -> dict[str, Any] | None:
    selection_key = str(side.get("selection_key") or "").strip()
    sportsbook = str(side.get("sportsbook") or "").strip()
    if not selection_key or not sportsbook:
        return None
    return {
        "selection_key": selection_key,
        "sportsbook": sportsbook,
        "reference_bookmakers": list(side.get("reference_bookmakers") or []),
        "reference_bookmaker_count": int(side.get("reference_bookmaker_count") or 0) or None,
    }


def build_player_prop_board_pickem_cards(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for side in items:
        line_value = side.get("line_value")
        if line_value is None:
            continue
        normalized_side = str(side.get("selection_side") or "").strip().lower()
        if normalized_side not in {"over", "under"}:
            continue

        key = "|".join(
            [
                str(side.get("event_id") or side.get("event") or "").strip(),
                str(side.get("market_key") or "").strip(),
                _canonicalize(str(side.get("player_name") or "")),
                str(line_value),
            ]
        )
        existing = grouped.get(key)
        if existing is None:
            existing = {
                "comparison_key": key,
                "event_id": side.get("event_id"),
                "sport": side.get("sport"),
                "event": side.get("event"),
                "event_short": side.get("event_short"),
                "commence_time": side.get("commence_time"),
                "player_name": side.get("player_name"),
                "participant_id": side.get("participant_id"),
                "team": side.get("team"),
                "team_short": side.get("team_short"),
                "opponent": side.get("opponent"),
                "opponent_short": side.get("opponent_short"),
                "market_key": side.get("market_key"),
                "market": side.get("market"),
                "line_value": line_value,
                "by_book": {},
            }
            grouped[key] = existing

        by_book = existing["by_book"]
        sportsbook = str(side.get("sportsbook") or "").strip()
        if not sportsbook:
            continue
        pair = by_book.setdefault(sportsbook, {})
        pair[normalized_side] = side

    cards: list[dict[str, Any]] = []
    for entry in grouped.values():
        valid_pairs: list[tuple[str, dict[str, Any]]] = []
        for sportsbook, pair in entry["by_book"].items():
            if pair.get("over") and pair.get("under"):
                valid_pairs.append((sportsbook, pair))
        if not valid_pairs:
            continue

        over_sides = [pair["over"] for _, pair in valid_pairs if pair.get("over")]
        under_sides = [pair["under"] for _, pair in valid_pairs if pair.get("under")]
        over_probs = [float(side.get("true_prob")) for side in over_sides if isinstance(side.get("true_prob"), (int, float))]
        under_probs = [float(side.get("true_prob")) for side in under_sides if isinstance(side.get("true_prob"), (int, float))]
        if not over_probs or not under_probs:
            continue

        best_over = max(over_sides, key=lambda side: _odds_quality(side.get("book_odds")), default=None)
        best_under = max(under_sides, key=lambda side: _odds_quality(side.get("book_odds")), default=None)
        support_books = [sportsbook for sportsbook, _pair in valid_pairs]
        consensus_over = round(_median(over_probs), 4)
        consensus_under = round(_median(under_probs), 4)

        cards.append(
            {
                "comparison_key": entry["comparison_key"],
                "event_id": entry.get("event_id"),
                "sport": entry.get("sport"),
                "event": entry.get("event"),
                "event_short": entry.get("event_short"),
                "commence_time": entry.get("commence_time"),
                "player_name": entry.get("player_name"),
                "participant_id": entry.get("participant_id"),
                "team": entry.get("team"),
                "team_short": entry.get("team_short"),
                "opponent": entry.get("opponent"),
                "opponent_short": entry.get("opponent_short"),
                "market_key": entry.get("market_key"),
                "market": entry.get("market"),
                "line_value": entry.get("line_value"),
                "exact_line_bookmakers": support_books,
                "exact_line_bookmaker_count": len(support_books),
                "consensus_over_prob": consensus_over,
                "consensus_under_prob": consensus_under,
                "consensus_side": "over" if consensus_over >= consensus_under else "under",
                "confidence_label": _confidence_label(len(support_books)),
                "best_over_sportsbook": best_over.get("sportsbook") if best_over else None,
                "best_over_odds": best_over.get("book_odds") if best_over else None,
                "best_over_deeplink_url": best_over.get("sportsbook_deeplink_url") if best_over else None,
                "best_under_sportsbook": best_under.get("sportsbook") if best_under else None,
                "best_under_odds": best_under.get("book_odds") if best_under else None,
                "best_under_deeplink_url": best_under.get("sportsbook_deeplink_url") if best_under else None,
            }
        )

    confidence_rank = {"elite": 4, "high": 3, "solid": 2, "thin": 1}
    cards = [card for card in cards if max(card["consensus_over_prob"], card["consensus_under_prob"]) > 0.5]
    cards.sort(
        key=lambda card: (
            max(card["consensus_over_prob"], card["consensus_under_prob"]),
            card["exact_line_bookmaker_count"],
            confidence_rank.get(str(card.get("confidence_label") or "").lower(), 0),
            str(card.get("player_name") or ""),
        ),
        reverse=True,
    )
    return cards


def persist_player_prop_board_artifacts(
    *,
    db,
    payload: dict[str, Any],
    retry_supabase,
    log_event,
    chunk_size: int = 250,
    legacy_max_items: int = 150,
    detail_batch_size: int = 200,
) -> dict[str, Any]:
    raw_sides = payload.get("sides")
    sides = raw_sides if isinstance(raw_sides, list) else []
    browse_items: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    available_books_set: set[str] = set()
    available_markets_set: set[str] = set()
    scanned_at = payload.get("scanned_at")
    detail_total = 0

    for side in sides:
        if not isinstance(side, dict):
            continue

        item = build_player_prop_board_item(side)
        browse_items.append(item)
        if is_player_prop_board_opportunity(item):
            opportunities.append(item)

        sportsbook = str(item.get("sportsbook") or "").strip()
        market_key = str(item.get("market_key") or "").strip()
        if sportsbook:
            available_books_set.add(sportsbook)
        if market_key:
            available_markets_set.add(market_key)

        detail = build_player_prop_board_detail(side)
        if detail is not None:
            detail_rows.append(
                {
                    "key": f"player_props:{_detail_scope(detail['selection_key'], detail['sportsbook'])}",
                    "surface": "player_props",
                    "payload": detail,
                }
            )
            detail_total += 1
            if len(detail_rows) >= max(1, detail_batch_size):
                _persist_chunked_rows(
                    db=db,
                    rows=detail_rows,
                    retry_supabase=retry_supabase,
                    log_event=log_event,
                    batch_size=detail_batch_size,
                )
                detail_rows = []

    if detail_rows:
        _persist_chunked_rows(
            db=db,
            rows=detail_rows,
            retry_supabase=retry_supabase,
            log_event=log_event,
            batch_size=detail_batch_size,
        )

    opportunities.sort(key=_ev_value, reverse=True)
    browse_items.sort(key=lambda item: str(item.get("commence_time") or ""))
    raw_pickem_cards = payload.get("pickem_cards")
    if isinstance(raw_pickem_cards, list):
        pickem = [card for card in raw_pickem_cards if isinstance(card, dict)]
    else:
        pickem = build_player_prop_board_pickem_cards(browse_items)
    available_books = sorted(available_books_set)
    available_markets = sorted(available_markets_set)

    def _persist_view(view: str, items: list[dict[str, Any]]) -> None:
        safe_chunk_size = max(1, chunk_size)
        chunk_count = max(1, (len(items) + safe_chunk_size - 1) // safe_chunk_size)
        meta_payload = {
            "view": view,
            "page_size": safe_chunk_size,
            "chunk_count": chunk_count,
            "total": len(items),
            "scanned_at": scanned_at,
            "available_books": available_books,
            "available_markets": available_markets,
        }
        _persist_cache_row(
            db=db,
            row={
                "key": f"player_props:{_artifact_meta_scope(view)}",
                "surface": "player_props",
                "payload": meta_payload,
            },
            retry_supabase=retry_supabase,
            log_event=log_event,
        )
        chunk_rows_batch: list[dict[str, Any]] = []
        for index, chunk in enumerate(_iter_chunk_items(items, chunk_size=safe_chunk_size), start=1):
            chunk_rows_batch.append(
                {
                    "key": f"player_props:{_artifact_chunk_scope(view, index)}",
                    "surface": "player_props",
                    "payload": {"items": chunk},
                }
            )
            if len(chunk_rows_batch) >= max(1, detail_batch_size):
                _persist_chunked_rows(
                    db=db,
                    rows=chunk_rows_batch,
                    retry_supabase=retry_supabase,
                    log_event=log_event,
                    batch_size=max(1, detail_batch_size),
                )
                chunk_rows_batch = []
        if chunk_rows_batch:
            _persist_chunked_rows(
                db=db,
                rows=chunk_rows_batch,
                retry_supabase=retry_supabase,
                log_event=log_event,
                batch_size=max(1, detail_batch_size),
            )

    _persist_view(BOARD_VIEW_OPPORTUNITIES, opportunities)
    _persist_view(BOARD_VIEW_BROWSE, browse_items)
    _persist_view(BOARD_VIEW_PICKEM, pickem)

    legacy_payload = {
        "surface": "player_props",
        "sport": payload.get("sport") or "basketball_nba",
        "sides": opportunities[: max(0, legacy_max_items)],
        "events_fetched": int(payload.get("events_fetched") or 0),
        "events_with_both_books": int(payload.get("events_with_both_books") or 0),
        "api_requests_remaining": payload.get("api_requests_remaining"),
        "scanned_at": scanned_at,
        "diagnostics": None,
        "prizepicks_cards": None,
    }
    _persist_cache_row(
        db=db,
        row={
            "key": f"player_props:{_legacy_surface_scope()}",
            "surface": "player_props",
            "payload": legacy_payload,
        },
        retry_supabase=retry_supabase,
        log_event=log_event,
    )
    return {
        "lean_total": len(browse_items),
        "opportunities_total": len(opportunities),
        "browse_total": len(browse_items),
        "pickem_total": len(pickem),
        "legacy_total": len(legacy_payload["sides"]),
        "detail_total": detail_total,
    }


def load_player_prop_board_artifact(
    *,
    db,
    retry_supabase,
    view: Literal["opportunities", "browse", "pickem"],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    meta = load_player_prop_board_meta(
        db=db,
        retry_supabase=retry_supabase,
        view=view,
    )
    if not isinstance(meta, dict):
        return None, []
    items: list[dict[str, Any]] = []
    for index in range(1, int(meta.get("chunk_count") or 0) + 1):
        chunk = load_player_prop_board_chunk(
            db=db,
            retry_supabase=retry_supabase,
            view=view,
            index=index,
        )
        chunk_items = chunk.get("items") if isinstance(chunk, dict) else None
        if isinstance(chunk_items, list):
            items.extend(item for item in chunk_items if isinstance(item, dict))
    return meta, items


def load_player_prop_board_meta(
    *,
    db,
    retry_supabase,
    view: Literal["opportunities", "browse", "pickem"],
) -> dict[str, Any] | None:
    return load_latest_scan_payload(
        db=db,
        retry_supabase=retry_supabase,
        surface="player_props",
        scope=_artifact_meta_scope(view),
    )


def load_player_prop_board_chunk(
    *,
    db,
    retry_supabase,
    view: Literal["opportunities", "browse", "pickem"],
    index: int,
) -> dict[str, Any] | None:
    return load_latest_scan_payload(
        db=db,
        retry_supabase=retry_supabase,
        surface="player_props",
        scope=_artifact_chunk_scope(view, index),
    )


def load_player_prop_board_filtered_page(
    *,
    db,
    retry_supabase,
    view: Literal["opportunities", "browse", "pickem"],
    page: int,
    page_size: int,
    filter_item,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int, int, bool]:
    meta = load_player_prop_board_meta(
        db=db,
        retry_supabase=retry_supabase,
        view=view,
    )
    if not isinstance(meta, dict):
        return None, [], 0, 0, False

    source_total = int(meta.get("total") or 0)
    safe_page = max(1, int(page))
    safe_page_size = max(1, int(page_size))
    page_start = (safe_page - 1) * safe_page_size
    page_end = page_start + safe_page_size

    filtered_total = 0
    paged_items: list[dict[str, Any]] = []
    has_more = False

    for index in range(1, int(meta.get("chunk_count") or 0) + 1):
        chunk = load_player_prop_board_chunk(
            db=db,
            retry_supabase=retry_supabase,
            view=view,
            index=index,
        )
        chunk_items = chunk.get("items") if isinstance(chunk, dict) else None
        if not isinstance(chunk_items, list):
            continue

        for item in chunk_items:
            if not isinstance(item, dict) or not filter_item(item):
                continue

            if filtered_total >= page_end:
                has_more = True
            elif filtered_total >= page_start:
                paged_items.append(item)

            filtered_total += 1

    return meta, paged_items, filtered_total, source_total, has_more


def load_player_prop_board_legacy_surface(
    *,
    db,
    retry_supabase,
) -> dict[str, Any] | None:
    return load_latest_scan_payload(
        db=db,
        retry_supabase=retry_supabase,
        surface="player_props",
        scope=_legacy_surface_scope(),
    )


def load_player_prop_board_detail(
    *,
    db,
    retry_supabase,
    selection_key: str,
    sportsbook: str,
) -> dict[str, Any] | None:
    payload = load_latest_scan_payload(
        db=db,
        retry_supabase=retry_supabase,
        surface="player_props",
        scope=_detail_scope(selection_key, sportsbook),
    )
    return payload if isinstance(payload, dict) else None


def _localize_for_offset(dt: datetime, tz_offset_minutes: int | None) -> datetime:
    if tz_offset_minutes is None:
        return dt.astimezone(UTC)
    return (dt.astimezone(UTC) - timedelta(minutes=tz_offset_minutes)).replace(tzinfo=None)


def matches_board_time_filter(
    commence_time: str,
    time_filter: str,
    *,
    now_utc: datetime | None = None,
    tz_offset_minutes: int | None = None,
) -> bool:
    try:
        start = datetime.fromisoformat(commence_time.replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return False
    now = now_utc or datetime.now(UTC)
    if time_filter == "all_games":
        return True
    if time_filter == "upcoming":
        return start >= now

    start_local = _localize_for_offset(start, tz_offset_minutes)
    now_local = _localize_for_offset(now, tz_offset_minutes)
    if time_filter == "today":
        return start_local.date() == now_local.date() and start_local >= now_local
    return start_local.date() == now_local.date() and start_local < now_local


def filter_player_prop_board_items(
    items: list[dict[str, Any]],
    *,
    books: list[str] | None = None,
    time_filter: str = "today",
    market: str | None = None,
    search: str | None = None,
    tz_offset_minutes: int | None = None,
) -> list[dict[str, Any]]:
    selected_books = {book.strip() for book in (books or []) if book.strip()}
    normalized_search = str(search or "").strip().lower()
    normalized_market = str(market or "").strip().lower()
    now_utc = datetime.now(UTC)

    out: list[dict[str, Any]] = []
    for item in items:
        if selected_books and str(item.get("sportsbook") or "") not in selected_books:
            continue
        if normalized_market and normalized_market != "all":
            if str(item.get("market_key") or "").strip().lower() != normalized_market:
                continue
        if not matches_board_time_filter(
            str(item.get("commence_time") or ""),
            time_filter,
            now_utc=now_utc,
            tz_offset_minutes=tz_offset_minutes,
        ):
            continue
        if normalized_search:
            haystack = " ".join(
                [
                    str(item.get("event") or ""),
                    str(item.get("event_short") or ""),
                    str(item.get("sport") or ""),
                    str(item.get("sportsbook") or ""),
                    str(item.get("player_name") or ""),
                    str(item.get("team") or ""),
                    str(item.get("team_short") or ""),
                    str(item.get("opponent") or ""),
                    str(item.get("opponent_short") or ""),
                ]
            ).lower()
            if normalized_search not in haystack:
                continue
        out.append(item)
    return out


def filter_player_prop_board_pickem_items(
    items: list[dict[str, Any]],
    *,
    books: list[str] | None = None,
    time_filter: str = "today",
    market: str | None = None,
    search: str | None = None,
    tz_offset_minutes: int | None = None,
) -> list[dict[str, Any]]:
    selected_books = {book.strip() for book in (books or []) if book.strip()}
    normalized_search = str(search or "").strip().lower()
    normalized_market = str(market or "").strip().lower()
    now_utc = datetime.now(UTC)

    out: list[dict[str, Any]] = []
    for item in items:
        if normalized_market and normalized_market != "all":
            if str(item.get("market_key") or "").strip().lower() != normalized_market:
                continue
        if not matches_board_time_filter(
            str(item.get("commence_time") or ""),
            time_filter,
            now_utc=now_utc,
            tz_offset_minutes=tz_offset_minutes,
        ):
            continue
        if selected_books:
            card_books = {str(book).strip() for book in item.get("exact_line_bookmakers") or [] if str(book).strip()}
            if not card_books.intersection(selected_books):
                continue
        if normalized_search:
            haystack = " ".join(
                [
                    str(item.get("player_name") or ""),
                    str(item.get("market") or ""),
                    str(item.get("event") or ""),
                    str(item.get("team") or ""),
                    str(item.get("opponent") or ""),
                    str(item.get("best_over_sportsbook") or ""),
                    str(item.get("best_under_sportsbook") or ""),
                    " ".join(str(book) for book in item.get("exact_line_bookmakers") or []),
                ]
            ).lower()
            if normalized_search not in haystack:
                continue
        out.append(item)
    return out


def paginate_board_items(
    items: list[dict[str, Any]],
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], bool]:
    safe_page = max(1, page)
    safe_page_size = max(1, page_size)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return items[start:end], end < len(items)
