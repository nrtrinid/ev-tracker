from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from calculations import calculate_clv

CLOSE_WINDOW_MINUTES = 20


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    raw = (value or "").strip()
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


def build_reference_snapshots(sides: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    snapshot_by_event: dict[tuple[str, str], float] = {}
    snapshot_by_time: dict[tuple[str, str], float] = {}
    for side in sides:
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


def update_bet_reference_snapshots(
    db,
    *,
    sides: list[dict[str, Any]],
    allow_close: bool,
    now: datetime | None = None,
) -> dict[str, int]:
    if not sides:
        return {"latest_updated": 0, "close_updated": 0}

    snapshot_by_event, snapshot_by_time = build_reference_snapshots(sides)
    if not snapshot_by_event and not snapshot_by_time:
        return {"latest_updated": 0, "close_updated": 0}

    sports = sorted({str(side.get("sport") or "").strip() for side in sides if side.get("sport")})
    query = (
        db.table("bets")
        .select(
            "id,result,clv_team,commence_time,clv_event_id,clv_sport_key,odds_american,"
            "latest_pinnacle_odds,latest_pinnacle_updated_at,pinnacle_odds_at_close,clv_updated_at"
        )
        .eq("result", "pending")
        .not_.is_("clv_team", "null")
    )
    if sports:
        query = query.in_("clv_sport_key", sports)
    result = query.execute()

    current = now or _utc_now()
    latest_updated = 0
    close_updated = 0
    updated_at = current.isoformat()

    for row in result.data or []:
        reference_odds = lookup_reference_odds(
            team=row.get("clv_team"),
            commence_time=row.get("commence_time"),
            event_id=row.get("clv_event_id"),
            snapshot_by_event=snapshot_by_event,
            snapshot_by_time=snapshot_by_time,
        )
        if reference_odds is None:
            continue

        payload: dict[str, Any] = {
            "latest_pinnacle_odds": reference_odds,
            "latest_pinnacle_updated_at": updated_at,
        }

        if allow_close and row.get("pinnacle_odds_at_close") is None and is_within_close_window(
            row.get("commence_time"),
            now=current,
        ):
            payload["pinnacle_odds_at_close"] = reference_odds
            payload["clv_updated_at"] = updated_at
            close_updated += 1
        latest_updated += 1

        db.table("bets").update(payload).eq("id", row["id"]).execute()

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

    snapshot_by_event, snapshot_by_time = build_reference_snapshots(sides)
    if not snapshot_by_event and not snapshot_by_time:
        return {"latest_updated": 0, "close_updated": 0}

    from services.research_opportunities import is_missing_scan_opportunities_error

    sports = sorted({str(side.get("sport") or "").strip() for side in sides if side.get("sport")})
    try:
        query = (
            db.table("scan_opportunities")
            .select(
                "id,sport,team,commence_time,event_id,first_book_odds,latest_reference_odds,"
                "latest_reference_updated_at,reference_odds_at_close,close_captured_at,clv_ev_percent,beat_close"
            )
            .is_("reference_odds_at_close", "null")
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
        reference_odds = lookup_reference_odds(
            team=row.get("team"),
            commence_time=row.get("commence_time"),
            event_id=row.get("event_id"),
            snapshot_by_event=snapshot_by_event,
            snapshot_by_time=snapshot_by_time,
        )
        if reference_odds is None:
            continue

        payload: dict[str, Any] = {
            "latest_reference_odds": reference_odds,
            "latest_reference_updated_at": updated_at,
        }
        latest_updated += 1

        if allow_close and row.get("reference_odds_at_close") is None and is_within_close_window(
            row.get("commence_time"),
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
