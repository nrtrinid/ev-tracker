from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo


DAILY_BOARD_SPORT = "basketball_nba"
DAILY_BOARD_MAX_GAMES = 4
DAILY_BOARD_PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_threes",
]
DAILY_BOARD_MIN_POST_DROP_LEAD_MINUTES = 30
DAILY_BOARD_MIN_TOTALS_OFFERS = 2


def _parse_utc_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


try:
    PHOENIX_TZ = ZoneInfo("America/Phoenix")
except Exception:
    # Phoenix does not observe DST; fixed UTC-7 fallback keeps behavior consistent
    # even when IANA tzdata isn't available in the runtime (common on Windows).
    PHOENIX_TZ = timezone(timedelta(hours=-7))
DAILY_DROP_HOUR = 15
DAILY_DROP_MINUTE = 30


def _phoenix_drop_for_date(day: datetime) -> datetime:
    local_day = day.astimezone(PHOENIX_TZ)
    return local_day.replace(hour=DAILY_DROP_HOUR, minute=DAILY_DROP_MINUTE, second=0, microsecond=0)


def _mode_total(offers: list[dict]) -> float | None:
    counts: dict[float, int] = {}
    for offer in offers or []:
        try:
            total = float(offer.get("total"))
        except Exception:
            continue
        counts[total] = counts.get(total, 0) + 1
    if not counts:
        return None
    # Deterministic: highest frequency, then higher total.
    return sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)[0][0]


def _has_pinnacle_offer(offers: list[dict]) -> bool:
    for offer in offers or []:
        if str(offer.get("sportsbook") or "").strip().lower() == "pinnacle":
            return True
    return False


def _select_daily_games(
    games: list[dict],
    *,
    max_games: int = DAILY_BOARD_MAX_GAMES,
    now: datetime | None = None,
) -> list[dict]:
    """
    Totals-driven heuristic selection.

    Beta intent: pick a small set of "useful" NBA games after the daily drop.
    Current heuristic:
    - only games that haven't started (with a 1-minute buffer)
    - prefer games that start sooner (closest commence_time)
    - require at least one totals offer (already enforced upstream)
    """
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now_dt + timedelta(minutes=1)

    drop_local = _phoenix_drop_for_date(now_dt)
    # If we’re before today’s drop, selection should still prefer games after the upcoming drop.
    # If we’re after the drop (or job misfired), prefer games after "now".
    is_after_drop = now_dt.astimezone(PHOENIX_TZ) >= drop_local
    preferred_after = (now_dt if is_after_drop else drop_local.astimezone(timezone.utc))
    preferred_after_with_lead = preferred_after + timedelta(minutes=DAILY_BOARD_MIN_POST_DROP_LEAD_MINUTES)

    candidates: list[tuple[tuple[int, int, int, float, float, str], dict]] = []
    for idx, game in enumerate(games):
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        commence = _parse_utc_iso(game.get("commence_time"))
        if commence is None:
            continue
        if commence <= cutoff:
            continue
        offers = game.get("totals_offers") or []
        offer_count = len(offers) if isinstance(offers, list) else 0
        if offer_count < DAILY_BOARD_MIN_TOTALS_OFFERS:
            continue

        # Bucket 0: "strong" games that start at least N minutes after preferred anchor.
        # Bucket 1: otherwise-eligible future games (fallback pool) from the same totals slate.
        bucket = 1
        if commence >= preferred_after_with_lead:
            bucket = 0

        mode_total = _mode_total(offers if isinstance(offers, list) else [])
        total_value = float(mode_total) if mode_total is not None else 0.0
        has_pinnacle = 1 if _has_pinnacle_offer(offers if isinstance(offers, list) else []) else 0

        commence_epoch = commence.timestamp()
        # Rank within bucket:
        # - more coverage (offer_count) first
        # - prefer Pinnacle present
        # - higher total magnitude (simple “more offense / more prop richness” heuristic)
        # - earlier start (still useful) first
        rank = (
            bucket,
            -offer_count,
            -has_pinnacle,
            -total_value,
            commence_epoch,
            f"{idx:04d}:{event_id}",
        )
        candidates.append((rank, game))

    candidates.sort(key=lambda item: item[0])

    selected: list[dict] = []
    for (bucket, _neg_offers, _neg_pin, _neg_total, _epoch, _stable), game in candidates[:max_games]:
        reason = "post_drop_preferred" if bucket == 0 and not is_after_drop else ("post_now_preferred" if bucket == 0 else "fallback_pool")
        offers = game.get("totals_offers") or []
        offers_list = offers if isinstance(offers, list) else []
        selected.append(
            {
                **game,
                "selection_reason": reason,
                "totals_offer_count": len(offers_list),
                "has_pinnacle_totals": _has_pinnacle_offer(offers_list),
                "consensus_total": _mode_total(offers_list),
            }
        )
    return selected


async def run_daily_board_drop(
    *,
    db,
    source: str,
    retry_supabase: Callable,
    log_event: Callable[..., None],
) -> dict[str, Any]:
    """
    Canonical daily-board publisher.

    Steps:
    1) Broad NBA totals fetch (slate-level) for selection + context.
    2) Select up to 4 games for the board.
    3) Scan player props only for selected event_ids × 3 markets.
    4) Capture research opportunities from prop sides (props-first).
    5) Persist board:latest with game_context + player_props (keep straight_bets compat as empty for now).
    """
    from models import FullScanResponse as _FSR
    from services.board_snapshot import persist_board_snapshot
    from services.odds_api import fetch_nba_totals_slate
    from services.player_props import scan_player_props_for_event_ids
    from services.research_opportunities import capture_scan_opportunities

    started_at = time.monotonic()
    scanned_at = _utc_now_iso()

    totals_payload = await fetch_nba_totals_slate(source=source)
    totals_games = totals_payload.get("games") if isinstance(totals_payload, dict) else []
    totals_games = totals_games if isinstance(totals_games, list) else []

    selected_games = _select_daily_games(totals_games, max_games=DAILY_BOARD_MAX_GAMES)
    selected_event_ids = [
        str(game.get("event_id") or "").strip()
        for game in selected_games
        if str(game.get("event_id") or "").strip()
    ]

    props_result = await scan_player_props_for_event_ids(
        sport=DAILY_BOARD_SPORT,
        event_ids=selected_event_ids,
        markets=DAILY_BOARD_PROP_MARKETS,
        source=source,
    )
    props_sides = props_result.get("sides") or []

    # Props-first research capture: persist +EV prop sides into scan_opportunities.
    if db is not None:
        try:
            capture_scan_opportunities(
                db,
                sides=[{**s, "surface": "player_props"} if isinstance(s, dict) else s for s in props_sides],
                source=source,
                captured_at=scanned_at,
            )
        except Exception as exc:
            log_event(
                "daily_board.research_capture_failed",
                level="warning",
                error_class=type(exc).__name__,
                error=str(exc),
            )

    # Keep straight_bets for compatibility, but the daily-board path no longer
    # runs broad h2h scans.
    straight_payload = _FSR(
        surface="straight_bets",
        sport="all",
        sides=[],
        events_fetched=0,
        events_with_both_books=0,
        api_requests_remaining=None,
        scanned_at=scanned_at,
    ).model_dump()

    props_payload = _FSR(
        surface="player_props",
        sport=DAILY_BOARD_SPORT,
        sides=props_sides,
        events_fetched=int(props_result.get("events_fetched") or 0),
        events_with_both_books=int(props_result.get("events_with_both_books") or 0),
        api_requests_remaining=props_result.get("api_requests_remaining"),
        scanned_at=props_result.get("scanned_at") or scanned_at,
        diagnostics=props_result.get("diagnostics"),
        prizepicks_cards=props_result.get("prizepicks_cards"),
    ).model_dump()

    game_context = {
        "sport": DAILY_BOARD_SPORT,
        "selection_mode": "totals_slate",
        "selection_params": {
            "min_post_drop_lead_minutes": DAILY_BOARD_MIN_POST_DROP_LEAD_MINUTES,
            "min_totals_offers": DAILY_BOARD_MIN_TOTALS_OFFERS,
        },
        "selected_event_ids": selected_event_ids,
        "games": selected_games,
        "events_fetched": int(totals_payload.get("events_fetched") or 0),
        "api_requests_remaining": totals_payload.get("api_requests_remaining"),
        "captured_at": scanned_at,
    }

    snapshot_id = "snap_none"
    if db is not None:
        snapshot_id = persist_board_snapshot(
            db=db,
            snapshot_type="scheduled",
            straight_bets_payload=straight_payload,
            player_props_payload=props_payload,
            scanned_at=scanned_at,
            retry_supabase=retry_supabase,
            log_event=log_event,
            game_context=game_context,
        )

    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    log_event(
        "daily_board.drop.completed",
        source=source,
        snapshot_id=snapshot_id,
        scanned_at=scanned_at,
        selected_games=len(selected_games),
        props_sides=len(props_sides),
        duration_ms=duration_ms,
    )

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "scanned_at": scanned_at,
        "selected_event_ids": selected_event_ids,
        "selected_games": selected_games,
        "props_sides": len(props_sides),
        "duration_ms": duration_ms,
    }

