from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from calculations import american_to_decimal
from models import (
    ResearchOpportunityBreakdownItem,
    ResearchOpportunityRecentRow,
    ResearchOpportunitySummaryResponse,
)
from services.match_keys import scanner_match_key_from_side

EDGE_BUCKET_ORDER = ["0-0.5%", "0.5-1%", "1-2%", "2-4%", "4%+"]
ODDS_BUCKET_ORDER = ["<= +150", "+151 to +300", "+301 to +500", "+501+"]
SOURCE_ORDER = ["manual_scan", "scheduled_scan", "ops_trigger_scan"]
SURFACE_ORDER = ["straight_bets", "player_props"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_source(value: str | None) -> str:
    return (value or "unknown").strip() or "unknown"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_line_value(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _line_token(value: Any) -> str:
    line_value = _normalize_line_value(value)
    if line_value is None:
        return ""
    return f"{line_value:g}"


def is_missing_scan_opportunities_error(error: Exception) -> bool:
    msg = str(error)
    return "PGRST205" in msg or ("scan_opportunities" in msg and "schema cache" in msg)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _price_quality(american: Any) -> float | None:
    odds = _coerce_float(american)
    if odds is None:
        return None
    try:
        return american_to_decimal(odds)
    except Exception:
        return None


def _opportunity_key_from_side(side: dict[str, Any]) -> str:
    surface = _normalize_text(side.get("surface")) or "straight_bets"
    if surface == "player_props":
        sport = _normalize_text(side.get("sport"))
        event_id = _normalize_text(side.get("event_id"))
        commence_time = str(side.get("commence_time") or "").strip()
        event_ref = f"id:{event_id}" if event_id else f"time:{commence_time}"
        market_key = _normalize_text(side.get("market_key"))
        player_name = _normalize_text(side.get("player_name"))
        selection_side = _normalize_text(side.get("selection_side"))
        sportsbook = _normalize_text(side.get("sportsbook"))
        return "|".join(
            [
                "player_props",
                sport,
                event_ref,
                market_key,
                player_name,
                selection_side,
                _line_token(side.get("line_value")),
                sportsbook,
            ]
        )

    sport, event_ref, market, team, sportsbook = scanner_match_key_from_side(side)
    return "|".join(["straight_bets", sport, event_ref, market, team, sportsbook])


def _reference_odds_from_side(side: dict[str, Any]) -> float | None:
    surface = _normalize_text(side.get("surface")) or "straight_bets"
    if surface == "player_props":
        return _coerce_float(side.get("reference_odds"))
    return _coerce_float(side.get("pinnacle_odds"))


def is_research_capture_candidate(side: dict[str, Any]) -> bool:
    surface = str(side.get("surface") or "straight_bets").strip().lower()
    if surface == "straight_bets":
        if str(side.get("market_key") or "h2h").strip().lower() != "h2h":
            return False
    elif surface == "player_props":
        if not _normalize_text(side.get("player_name")):
            return False
        if not _normalize_text(side.get("market_key")):
            return False
        if not _normalize_text(side.get("selection_side")):
            return False
        if _normalize_line_value(side.get("line_value")) is None:
            return False
    else:
        return False

    ev = _coerce_float(side.get("ev_percentage"))
    book_odds = _coerce_float(side.get("book_odds"))
    ref_odds = _reference_odds_from_side(side)
    if ev is None or ev <= 0:
        return False
    if book_odds is None or ref_odds is None:
        return False
    return True


def capture_scan_opportunities(
    db,
    *,
    sides: list[dict[str, Any]],
    source: str,
    captured_at: str,
) -> dict[str, int]:
    eligible = [side for side in sides if is_research_capture_candidate(side)]
    if not eligible:
        return {"eligible_seen": 0, "inserted": 0, "updated": 0}

    collapsed_by_key: dict[str, dict[str, Any]] = {}
    for side in eligible:
        opportunity_key = _opportunity_key_from_side(side)
        book_odds = float(side["book_odds"])
        ref_odds = float(_reference_odds_from_side(side) or 0)
        ev_percentage = float(side["ev_percentage"])
        current_quality = _price_quality(book_odds)
        existing = collapsed_by_key.get(opportunity_key)
        if existing is None:
            collapsed_by_key[opportunity_key] = {
                "side": dict(side),
                "book_odds": book_odds,
                "ref_odds": ref_odds,
                "ev_percentage": ev_percentage,
                "best_book_odds": book_odds,
                "best_reference_odds": ref_odds,
                "best_ev_percentage": ev_percentage,
                "best_quality": current_quality,
            }
            continue

        existing["side"] = dict(side)
        existing["book_odds"] = book_odds
        existing["ref_odds"] = ref_odds
        existing["ev_percentage"] = ev_percentage
        best_quality = existing.get("best_quality")
        if current_quality is not None and (best_quality is None or current_quality > best_quality):
            existing["best_book_odds"] = book_odds
            existing["best_reference_odds"] = ref_odds
            existing["best_ev_percentage"] = ev_percentage
            existing["best_quality"] = current_quality

    normalized_source = _normalize_source(source)
    opportunity_keys = list(collapsed_by_key.keys())
    existing_res = (
        db.table("scan_opportunities")
        .select(
            "id,opportunity_key,seen_count,best_book_odds,event,commence_time,team,sportsbook,event_id,"
            "surface,market,player_name,source_market_key,selection_side,line_value"
        )
        .in_("opportunity_key", opportunity_keys)
        .execute()
    )
    existing_by_key = {
        str(row.get("opportunity_key") or ""): row
        for row in (existing_res.data or [])
        if row.get("opportunity_key")
    }

    insert_payloads: list[dict[str, Any]] = []
    updated = 0

    for opportunity_key, collapsed in collapsed_by_key.items():
        side = collapsed["side"]
        book_odds = float(collapsed["book_odds"])
        ref_odds = float(collapsed["ref_odds"])
        ev_percentage = float(collapsed["ev_percentage"])
        surface = str(side.get("surface") or "straight_bets").strip().lower() or "straight_bets"
        event_id = str(side.get("event_id") or "").strip() or None
        player_name = str(side.get("player_name") or "").strip() or None
        source_market_key = str(side.get("market_key") or "").strip() or None
        selection_side = str(side.get("selection_side") or "").strip().lower() or None
        line_value = _normalize_line_value(side.get("line_value"))
        row = existing_by_key.get(opportunity_key)

        if row is None:
            insert_payloads.append(
                {
                    "opportunity_key": opportunity_key,
                    "surface": surface,
                    "sport": str(side.get("sport") or ""),
                    "event": str(side.get("event") or ""),
                    "commence_time": str(side.get("commence_time") or ""),
                    "team": str(side.get("team") or ""),
                    "sportsbook": str(side.get("sportsbook") or ""),
                    "market": "ML" if surface == "straight_bets" else str(side.get("market") or source_market_key or ""),
                    "event_id": event_id,
                    "player_name": player_name,
                    "source_market_key": source_market_key,
                    "selection_side": selection_side,
                    "line_value": line_value,
                    "first_source": normalized_source,
                    "last_source": normalized_source,
                    "seen_count": 1,
                    "first_seen_at": captured_at,
                    "last_seen_at": captured_at,
                    "best_seen_at": captured_at,
                    "first_book_odds": book_odds,
                    "last_book_odds": book_odds,
                    "best_book_odds": float(collapsed["best_book_odds"]),
                    "first_reference_odds": ref_odds,
                    "last_reference_odds": ref_odds,
                    "best_reference_odds": float(collapsed["best_reference_odds"]),
                    "first_ev_percentage": ev_percentage,
                    "last_ev_percentage": ev_percentage,
                    "best_ev_percentage": float(collapsed["best_ev_percentage"]),
                    "latest_reference_odds": ref_odds,
                    "latest_reference_updated_at": captured_at,
                    "reference_odds_at_close": None,
                    "close_captured_at": None,
                    "clv_ev_percent": None,
                    "beat_close": None,
                }
            )
            continue

        best_book_odds = _coerce_float(row.get("best_book_odds"))
        batch_best_quality = collapsed.get("best_quality")
        best_quality = _price_quality(best_book_odds)
        payload = {
            "surface": surface,
            "event": str(side.get("event") or row.get("event") or ""),
            "commence_time": str(side.get("commence_time") or row.get("commence_time") or ""),
            "team": str(side.get("team") or row.get("team") or ""),
            "sportsbook": str(side.get("sportsbook") or row.get("sportsbook") or ""),
            "market": "ML" if surface == "straight_bets" else str(side.get("market") or row.get("market") or source_market_key or ""),
            "event_id": event_id or row.get("event_id"),
            "player_name": player_name or row.get("player_name"),
            "source_market_key": source_market_key or row.get("source_market_key"),
            "selection_side": selection_side or row.get("selection_side"),
            "line_value": line_value if line_value is not None else row.get("line_value"),
            "last_source": normalized_source,
            "seen_count": int(row.get("seen_count") or 0) + 1,
            "last_seen_at": captured_at,
            "last_book_odds": book_odds,
            "last_reference_odds": ref_odds,
            "last_ev_percentage": ev_percentage,
            "latest_reference_odds": ref_odds,
            "latest_reference_updated_at": captured_at,
        }
        if batch_best_quality is not None and (best_quality is None or batch_best_quality > best_quality):
            payload.update(
                {
                    "best_seen_at": captured_at,
                    "best_book_odds": float(collapsed["best_book_odds"]),
                    "best_reference_odds": float(collapsed["best_reference_odds"]),
                    "best_ev_percentage": float(collapsed["best_ev_percentage"]),
                }
            )

        db.table("scan_opportunities").update(payload).eq("id", row["id"]).execute()
        updated += 1

    if insert_payloads:
        db.table("scan_opportunities").insert(insert_payloads).execute()

    return {
        "eligible_seen": len(eligible),
        "inserted": len(insert_payloads),
        "updated": updated,
    }


def empty_research_opportunities_summary() -> ResearchOpportunitySummaryResponse:
    return ResearchOpportunitySummaryResponse(
        captured_count=0,
        open_count=0,
        close_captured_count=0,
        clv_ready_count=0,
        beat_close_pct=None,
        avg_clv_percent=None,
        by_surface=[],
        by_source=[],
        by_sportsbook=[],
        by_edge_bucket=[],
        by_odds_bucket=[],
        recent_opportunities=[],
    )


def _edge_bucket(ev_percentage: float | None) -> str:
    value = ev_percentage or 0.0
    if value < 0.5:
        return "0-0.5%"
    if value < 1.0:
        return "0.5-1%"
    if value < 2.0:
        return "1-2%"
    if value < 4.0:
        return "2-4%"
    return "4%+"


def _odds_bucket(book_odds: float | None) -> str:
    value = book_odds or 0.0
    if value <= 150:
        return "<= +150"
    if value <= 300:
        return "+151 to +300"
    if value <= 500:
        return "+301 to +500"
    return "+501+"


def _aggregate_breakdown(
    rows: list[dict[str, Any]],
    *,
    key_fn,
    preferred_order: list[str] | None = None,
) -> list[ResearchOpportunityBreakdownItem]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)

    preferred_position = {key: index for index, key in enumerate(preferred_order or [])}
    items: list[ResearchOpportunityBreakdownItem] = []
    for key, bucket_rows in groups.items():
        clv_rows = [row for row in bucket_rows if _coerce_float(row.get("clv_ev_percent")) is not None]
        beat_close_count = sum(1 for row in clv_rows if row.get("beat_close") is True)
        avg_clv = None
        if clv_rows:
            avg_clv = round(
                sum(float(row["clv_ev_percent"]) for row in clv_rows if _coerce_float(row.get("clv_ev_percent")) is not None)
                / len(clv_rows),
                2,
            )
        beat_close_pct = None
        if clv_rows:
            beat_close_pct = round((beat_close_count / len(clv_rows)) * 100, 2)
        items.append(
            ResearchOpportunityBreakdownItem(
                key=key,
                captured_count=len(bucket_rows),
                clv_ready_count=len(clv_rows),
                beat_close_pct=beat_close_pct,
                avg_clv_percent=avg_clv,
            )
        )

    items.sort(
        key=lambda item: (
            preferred_position.get(item.key, len(preferred_position)),
            -item.captured_count,
            item.key,
        )
    )
    return items


def get_research_opportunities_summary(db) -> ResearchOpportunitySummaryResponse:
    try:
        res = (
            db.table("scan_opportunities")
            .select(
                "opportunity_key,surface,first_seen_at,last_seen_at,commence_time,sport,event,team,sportsbook,market,event_id,"
                "player_name,source_market_key,selection_side,line_value,"
                "first_source,last_source,seen_count,first_ev_percentage,first_book_odds,best_book_odds,"
                "latest_reference_odds,reference_odds_at_close,clv_ev_percent,beat_close"
            )
            .execute()
        )
    except Exception as e:
        if is_missing_scan_opportunities_error(e):
            return empty_research_opportunities_summary()
        raise
    rows = list(res.data or [])
    clv_rows = [row for row in rows if _coerce_float(row.get("clv_ev_percent")) is not None]
    beat_close_count = sum(1 for row in clv_rows if row.get("beat_close") is True)

    beat_close_pct = None
    avg_clv_percent = None
    if clv_rows:
        beat_close_pct = round((beat_close_count / len(clv_rows)) * 100, 2)
        avg_clv_percent = round(
            sum(float(row["clv_ev_percent"]) for row in clv_rows if _coerce_float(row.get("clv_ev_percent")) is not None)
            / len(clv_rows),
            2,
        )

    recent_rows = sorted(
        rows,
        key=lambda row: _coerce_datetime(row.get("first_seen_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:15]

    recent = [
        ResearchOpportunityRecentRow(
            opportunity_key=str(row.get("opportunity_key") or ""),
            surface=str(row.get("surface") or "straight_bets"),
            first_seen_at=_coerce_datetime(row.get("first_seen_at")) or _utc_now(),
            last_seen_at=_coerce_datetime(row.get("last_seen_at")) or _utc_now(),
            commence_time=str(row.get("commence_time") or ""),
            sport=str(row.get("sport") or ""),
            event=str(row.get("event") or ""),
            team=str(row.get("team") or ""),
            sportsbook=str(row.get("sportsbook") or ""),
            market=str(row.get("market") or "ML"),
            event_id=str(row.get("event_id") or "").strip() or None,
            player_name=str(row.get("player_name") or "").strip() or None,
            source_market_key=str(row.get("source_market_key") or "").strip() or None,
            selection_side=str(row.get("selection_side") or "").strip() or None,
            line_value=_coerce_float(row.get("line_value")),
            first_source=str(row.get("first_source") or "unknown"),
            seen_count=int(row.get("seen_count") or 0),
            first_ev_percentage=float(row.get("first_ev_percentage") or 0),
            first_book_odds=float(row.get("first_book_odds") or 0),
            best_book_odds=float(row.get("best_book_odds") or 0),
            latest_reference_odds=_coerce_float(row.get("latest_reference_odds")),
            reference_odds_at_close=_coerce_float(row.get("reference_odds_at_close")),
            clv_ev_percent=_coerce_float(row.get("clv_ev_percent")),
            beat_close=row.get("beat_close"),
        )
        for row in recent_rows
    ]

    return ResearchOpportunitySummaryResponse(
        captured_count=len(rows),
        open_count=sum(1 for row in rows if _coerce_float(row.get("reference_odds_at_close")) is None),
        close_captured_count=sum(1 for row in rows if _coerce_float(row.get("reference_odds_at_close")) is not None),
        clv_ready_count=len(clv_rows),
        beat_close_pct=beat_close_pct,
        avg_clv_percent=avg_clv_percent,
        by_surface=_aggregate_breakdown(
            rows,
            key_fn=lambda row: row.get("surface") or "straight_bets",
            preferred_order=SURFACE_ORDER,
        ),
        by_source=_aggregate_breakdown(rows, key_fn=lambda row: row.get("first_source") or "unknown", preferred_order=SOURCE_ORDER),
        by_sportsbook=_aggregate_breakdown(rows, key_fn=lambda row: row.get("sportsbook") or "Unknown"),
        by_edge_bucket=_aggregate_breakdown(
            rows,
            key_fn=lambda row: _edge_bucket(_coerce_float(row.get("first_ev_percentage"))),
            preferred_order=EDGE_BUCKET_ORDER,
        ),
        by_odds_bucket=_aggregate_breakdown(
            rows,
            key_fn=lambda row: _odds_bucket(_coerce_float(row.get("first_book_odds"))),
            preferred_order=ODDS_BUCKET_ORDER,
        ),
        recent_opportunities=recent,
    )
