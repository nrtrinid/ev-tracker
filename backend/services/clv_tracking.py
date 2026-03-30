from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from calculations import calculate_clv

CLOSE_WINDOW_MINUTES = 20


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def is_within_close_window(
    commence_time: str | None,
    *,
    now: datetime | None = None,
    window_minutes: int = CLOSE_WINDOW_MINUTES,
) -> bool:
    commence_dt = _parse_iso_datetime(commence_time)
    if commence_dt is None:
        return False
    current = now or _utc_now()
    if commence_dt <= current:
        return False
    return commence_dt <= current + timedelta(minutes=window_minutes)


def has_valid_close_snapshot(
    commence_time: str | None,
    captured_at: Any,
    *,
    window_minutes: int = CLOSE_WINDOW_MINUTES,
) -> bool:
    commence_dt = _parse_iso_datetime(commence_time)
    captured_dt = _parse_iso_datetime(captured_at)
    if commence_dt is None or captured_dt is None:
        return False
    close_window_start = commence_dt - timedelta(minutes=window_minutes)
    return close_window_start <= captured_dt <= commence_dt


def should_capture_close_snapshot(
    commence_time: str | None,
    *,
    existing_close: Any,
    captured_at: Any,
    now: datetime | None = None,
    window_minutes: int = CLOSE_WINDOW_MINUTES,
) -> bool:
    current = now or _utc_now()
    if not is_within_close_window(commence_time, now=current, window_minutes=window_minutes):
        return False
    if existing_close is None:
        return True
    return not has_valid_close_snapshot(commence_time, captured_at, window_minutes=window_minutes)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_line_value(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def build_reference_snapshots(sides: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    snapshot_by_event: dict[tuple[str, str], float] = {}
    snapshot_by_time: dict[tuple[str, str], float] = {}
    for side in sides:
        if str(side.get("surface") or "straight_bets").strip().lower() != "straight_bets":
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        team = str(side.get("team") or "")
        pinnacle_odds = side.get("pinnacle_odds")
        if pinnacle_odds is None or not team:
            continue
        if commence_time:
            snapshot_by_time[(commence_time, team)] = float(pinnacle_odds)
        if event_id:
            snapshot_by_event[(event_id, team)] = float(pinnacle_odds)
    return snapshot_by_event, snapshot_by_time


def build_prop_reference_snapshots(
    sides: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, str, float], float], dict[tuple[str, str, str, str, float], float]]:
    snapshot_by_event: dict[tuple[str, str, str, str, float], float] = {}
    snapshot_by_time: dict[tuple[str, str, str, str, float], float] = {}
    for side in sides:
        if str(side.get("surface") or "").strip().lower() != "player_props":
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        player_name = _normalize_text(side.get("player_name"))
        market_key = _normalize_text(side.get("market_key"))
        selection_side = _normalize_text(side.get("selection_side"))
        line_value = _normalize_line_value(side.get("line_value"))
        reference_odds = side.get("reference_odds")
        if reference_odds is None or not player_name or not market_key or not selection_side or line_value is None:
            continue
        if commence_time:
            snapshot_by_time[(commence_time, player_name, market_key, selection_side, line_value)] = float(reference_odds)
        if event_id:
            snapshot_by_event[(event_id, player_name, market_key, selection_side, line_value)] = float(reference_odds)
    return snapshot_by_event, snapshot_by_time


def lookup_reference_odds(
    *,
    team: str | None,
    commence_time: str | None,
    event_id: str | None,
    snapshot_by_event: dict[tuple[str, str], float],
    snapshot_by_time: dict[tuple[str, str], float],
) -> float | None:
    normalized_team = str(team or "")
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    if normalized_event_id and normalized_team:
        match = snapshot_by_event.get((normalized_event_id, normalized_team))
        if match is not None:
            return match
    if normalized_commence and normalized_team:
        return snapshot_by_time.get((normalized_commence, normalized_team))
    return None


def lookup_prop_reference_odds(
    *,
    player_name: str | None,
    source_market_key: str | None,
    selection_side: str | None,
    line_value: float | None,
    commence_time: str | None,
    event_id: str | None,
    snapshot_by_event: dict[tuple[str, str, str, str, float], float],
    snapshot_by_time: dict[tuple[str, str, str, str, float], float],
) -> float | None:
    normalized_player = _normalize_text(player_name)
    normalized_market = _normalize_text(source_market_key)
    normalized_side = _normalize_text(selection_side)
    normalized_line = _normalize_line_value(line_value)
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    if not normalized_player or not normalized_market or not normalized_side or normalized_line is None:
        return None
    if normalized_event_id:
        match = snapshot_by_event.get(
            (normalized_event_id, normalized_player, normalized_market, normalized_side, normalized_line)
        )
        if match is not None:
            return match
    if normalized_commence:
        return snapshot_by_time.get(
            (normalized_commence, normalized_player, normalized_market, normalized_side, normalized_line)
        )
    return None


def _coerce_selection_meta_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        return copy.deepcopy(parsed) if isinstance(parsed, dict) else None
    return None


def _parlay_leg_sport_key(leg: dict[str, Any]) -> str:
    return str(leg.get("sport") or "").strip()


def _parlay_meta_has_leg_in_sports(meta: dict[str, Any], sports_set: set[str]) -> bool:
    legs = meta.get("legs")
    if not isinstance(legs, list):
        return False
    for leg in legs:
        if isinstance(leg, dict) and _parlay_leg_sport_key(leg) in sports_set:
            return True
    return False


def lookup_parlay_leg_reference_odds(
    leg: dict[str, Any],
    *,
    straight_snapshot_by_event: dict[tuple[str, str], float],
    straight_snapshot_by_time: dict[tuple[str, str], float],
    prop_snapshot_by_event: dict[tuple[str, str, str, str, float], float],
    prop_snapshot_by_time: dict[tuple[str, str, str, str, float], float],
) -> float | None:
    surface = str(leg.get("surface") or "straight_bets").strip().lower()
    commence = str(leg.get("commenceTime") or leg.get("commence_time") or "").strip()
    event_id = str(
        leg.get("sourceEventId")
        or leg.get("source_event_id")
        or leg.get("eventId")
        or leg.get("event_id")
        or ""
    ).strip()
    if surface == "player_props":
        return lookup_prop_reference_odds(
            player_name=leg.get("participantName") or leg.get("participant_name"),
            source_market_key=leg.get("sourceMarketKey") or leg.get("source_market_key"),
            selection_side=leg.get("selectionSide") or leg.get("selection_side"),
            line_value=_normalize_line_value(
                leg.get("lineValue") if leg.get("lineValue") is not None else leg.get("line_value")
            ),
            commence_time=commence or None,
            event_id=event_id or None,
            snapshot_by_event=prop_snapshot_by_event,
            snapshot_by_time=prop_snapshot_by_time,
        )
    team = leg.get("team")
    if not team:
        return None
    return lookup_reference_odds(
        team=team,
        commence_time=commence or None,
        event_id=event_id or None,
        snapshot_by_event=straight_snapshot_by_event,
        snapshot_by_time=straight_snapshot_by_time,
    )


def _update_parlay_bet_leg_snapshots(
    db,
    *,
    sports_set: set[str],
    straight_snapshot_by_event: dict[tuple[str, str], float],
    straight_snapshot_by_time: dict[tuple[str, str], float],
    prop_snapshot_by_event: dict[tuple[str, str, str, str, float], float],
    prop_snapshot_by_time: dict[tuple[str, str, str, str, float], float],
    allow_close: bool,
    current: datetime,
    updated_at: str,
) -> tuple[int, int]:
    """Merge per-leg reference / close CLV into bets.selection_meta.legs (parlay rows only)."""
    if not sports_set:
        return (0, 0)

    parlay_result = (
        db.table("bets")
        .select("id,result,surface,selection_meta")
        .eq("result", "pending")
        .eq("surface", "parlay")
        .execute()
    )

    latest_updated = 0
    close_updated = 0

    for row in parlay_result.data or []:
        meta = _coerce_selection_meta_dict(row.get("selection_meta"))
        if meta is None or str(meta.get("type") or "").strip().lower() != "parlay":
            continue
        if not _parlay_meta_has_leg_in_sports(meta, sports_set):
            continue
        legs = meta.get("legs")
        if not isinstance(legs, list):
            continue

        new_legs: list[Any] = []
        row_touched = False

        for leg in legs:
            if not isinstance(leg, dict):
                new_legs.append(leg)
                continue
            if _parlay_leg_sport_key(leg) not in sports_set:
                new_legs.append(leg)
                continue

            leg_out = dict(leg)
            reference_odds = lookup_parlay_leg_reference_odds(
                leg_out,
                straight_snapshot_by_event=straight_snapshot_by_event,
                straight_snapshot_by_time=straight_snapshot_by_time,
                prop_snapshot_by_event=prop_snapshot_by_event,
                prop_snapshot_by_time=prop_snapshot_by_time,
            )
            if reference_odds is None:
                new_legs.append(leg_out)
                continue

            row_touched = True
            leg_out["latest_reference_odds"] = reference_odds
            leg_out["latest_reference_updated_at"] = updated_at

            book_raw = (
                leg_out.get("oddsAmerican")
                if leg_out.get("oddsAmerican") is not None
                else leg_out.get("odds_american")
            )
            try:
                book_am = float(book_raw) if book_raw is not None else None
            except (TypeError, ValueError):
                book_am = None

            leg_commence = str(leg_out.get("commenceTime") or leg_out.get("commence_time") or "").strip() or None

            if allow_close and book_am is not None and should_capture_close_snapshot(
                leg_commence,
                existing_close=leg_out.get("pinnacle_odds_at_close"),
                captured_at=leg_out.get("reference_updated_at"),
                now=current,
            ):
                clv_result = calculate_clv(book_am, float(reference_odds))
                leg_out["pinnacle_odds_at_close"] = reference_odds
                leg_out["reference_updated_at"] = updated_at
                leg_out["clv_ev_percent"] = clv_result["clv_ev_percent"]
                leg_out["beat_close"] = clv_result["beat_close"]
                close_updated += 1

            new_legs.append(leg_out)

        if row_touched:
            meta["legs"] = new_legs
            latest_updated += 1
            db.table("bets").update({"selection_meta": meta}).eq("id", row["id"]).execute()

    return latest_updated, close_updated


def update_bet_reference_snapshots(
    db,
    *,
    sides: list[dict[str, Any]],
    allow_close: bool,
    now: datetime | None = None,
) -> dict[str, int]:
    if not sides:
        return {"latest_updated": 0, "close_updated": 0}

    straight_snapshot_by_event, straight_snapshot_by_time = build_reference_snapshots(sides)
    prop_snapshot_by_event, prop_snapshot_by_time = build_prop_reference_snapshots(sides)

    if (
        not straight_snapshot_by_event
        and not straight_snapshot_by_time
        and not prop_snapshot_by_event
        and not prop_snapshot_by_time
    ):
        return {"latest_updated": 0, "close_updated": 0}

    sports = sorted({str(side.get("sport") or "").strip() for side in sides if side.get("sport")})
    sports_set = {s for s in sports if s}
    query = (
        db.table("bets")
        .select(
            "id,result,surface,commence_time,clv_event_id,source_event_id,clv_sport_key,clv_team,"
            "participant_name,source_market_key,selection_side,line_value,odds_american,"
            "latest_pinnacle_odds,latest_pinnacle_updated_at,pinnacle_odds_at_close,clv_updated_at"
        )
        .eq("result", "pending")
    )
    if sports:
        query = query.in_("clv_sport_key", sports)

    result = query.execute()

    current = now or _utc_now()
    updated_at = current.isoformat()
    latest_updated = 0
    close_updated = 0

    for row in result.data or []:
        surface = str(row.get("surface") or "straight_bets").strip().lower()

        if surface == "player_props":
            reference_odds = lookup_prop_reference_odds(
                player_name=row.get("participant_name"),
                source_market_key=row.get("source_market_key"),
                selection_side=row.get("selection_side"),
                line_value=_normalize_line_value(row.get("line_value")),
                commence_time=row.get("commence_time"),
                event_id=row.get("source_event_id") or row.get("clv_event_id"),
                snapshot_by_event=prop_snapshot_by_event,
                snapshot_by_time=prop_snapshot_by_time,
            )
        else:
            if not row.get("clv_team"):
                continue

            reference_odds = lookup_reference_odds(
                team=row.get("clv_team"),
                commence_time=row.get("commence_time"),
                event_id=row.get("clv_event_id"),
                snapshot_by_event=straight_snapshot_by_event,
                snapshot_by_time=straight_snapshot_by_time,
            )

        if reference_odds is None:
            continue

        payload: dict[str, Any] = {
            "latest_pinnacle_odds": reference_odds,
            "latest_pinnacle_updated_at": updated_at,
        }
        latest_updated += 1

        if allow_close and should_capture_close_snapshot(
            row.get("commence_time"),
            existing_close=row.get("pinnacle_odds_at_close"),
            captured_at=row.get("clv_updated_at"),
            now=current,
        ):
            payload.update(
                {
                    "pinnacle_odds_at_close": reference_odds,
                    "clv_updated_at": updated_at,
                }
            )
            close_updated += 1

        db.table("bets").update(payload).eq("id", row["id"]).execute()

    p_latest, p_close = _update_parlay_bet_leg_snapshots(
        db,
        sports_set=sports_set,
        straight_snapshot_by_event=straight_snapshot_by_event,
        straight_snapshot_by_time=straight_snapshot_by_time,
        prop_snapshot_by_event=prop_snapshot_by_event,
        prop_snapshot_by_time=prop_snapshot_by_time,
        allow_close=allow_close,
        current=current,
        updated_at=updated_at,
    )
    latest_updated += p_latest
    close_updated += p_close

    return {"latest_updated": latest_updated, "close_updated": close_updated}

def update_scan_opportunity_reference_snapshots(
    db,
    *,
    sides: list[dict[str, Any]],
    allow_close: bool,
    now: datetime | None = None,
) -> dict[str, int]:
    if not sides:
        return {"latest_updated": 0, "close_updated": 0}

    straight_snapshot_by_event, straight_snapshot_by_time = build_reference_snapshots(sides)
    prop_snapshot_by_event, prop_snapshot_by_time = build_prop_reference_snapshots(sides)
    if not straight_snapshot_by_event and not straight_snapshot_by_time and not prop_snapshot_by_event and not prop_snapshot_by_time:
        return {"latest_updated": 0, "close_updated": 0}

    from services.research_opportunities import is_missing_scan_opportunities_error

    sports = sorted({str(side.get("sport") or "").strip() for side in sides if side.get("sport")})
    try:
        query = (
            db.table("scan_opportunities")
            .select(
                "id,surface,sport,team,commence_time,event_id,player_name,source_market_key,selection_side,line_value,"
                "first_book_odds,latest_reference_odds,"
                "latest_reference_updated_at,reference_odds_at_close,close_captured_at,clv_ev_percent,beat_close"
            )
        )
        if sports:
            query = query.in_("sport", sports)
        result = query.execute()
    except Exception as e:
        if is_missing_scan_opportunities_error(e):
            return {"latest_updated": 0, "close_updated": 0}
        raise

    current = now or _utc_now()
    updated_at = current.isoformat()
    latest_updated = 0
    close_updated = 0

    for row in result.data or []:
        if str(row.get("surface") or "straight_bets").strip().lower() == "player_props":
            reference_odds = lookup_prop_reference_odds(
                player_name=row.get("player_name"),
                source_market_key=row.get("source_market_key"),
                selection_side=row.get("selection_side"),
                line_value=_normalize_line_value(row.get("line_value")),
                commence_time=row.get("commence_time"),
                event_id=row.get("event_id"),
                snapshot_by_event=prop_snapshot_by_event,
                snapshot_by_time=prop_snapshot_by_time,
            )
        else:
            reference_odds = lookup_reference_odds(
                team=row.get("team"),
                commence_time=row.get("commence_time"),
                event_id=row.get("event_id"),
                snapshot_by_event=straight_snapshot_by_event,
                snapshot_by_time=straight_snapshot_by_time,
            )
        if reference_odds is None:
            continue

        payload: dict[str, Any] = {
            "latest_reference_odds": reference_odds,
            "latest_reference_updated_at": updated_at,
        }
        latest_updated += 1

        if allow_close and should_capture_close_snapshot(
            row.get("commence_time"),
            existing_close=row.get("reference_odds_at_close"),
            captured_at=row.get("close_captured_at"),
            now=current,
        ):
            clv_result = calculate_clv(float(row.get("first_book_odds")), reference_odds)
            payload.update(
                {
                    "reference_odds_at_close": reference_odds,
                    "close_captured_at": updated_at,
                    "clv_ev_percent": clv_result["clv_ev_percent"],
                    "beat_close": clv_result["beat_close"],
                }
            )
            close_updated += 1

        db.table("scan_opportunities").update(payload).eq("id", row["id"]).execute()

    return {"latest_updated": latest_updated, "close_updated": close_updated}
