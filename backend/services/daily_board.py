from __future__ import annotations

import asyncio
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
    "player_assists",
    "player_points_rebounds_assists",
    "player_threes",
]
DAILY_BOARD_MIN_POST_DROP_LEAD_MINUTES = 30
DAILY_BOARD_MIN_TOTALS_OFFERS = 2
FEATURED_LINES_PER_SPORT_CAP = 6
FEATURED_LINES_STALE_AFTER_SECONDS = 60 * 45


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


def _rank_featured_games(games: list[dict], *, max_games: int) -> list[dict]:
    now_dt = datetime.now(timezone.utc)
    ranked: list[tuple[tuple[float, int, int, str], dict]] = []
    for game in games or []:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        commence = _parse_utc_iso(game.get("commence_time"))
        if commence is None:
            continue
        if commence <= now_dt:
            continue
        h2h_count = len(game.get("h2h_offers") or [])
        spread_count = len(game.get("spreads_offers") or [])
        totals_count = len(game.get("totals_offers") or [])
        coverage = h2h_count + spread_count + totals_count
        if coverage <= 0:
            continue
        rank = (
            commence.timestamp(),
            -coverage,
            -(1 if _has_pinnacle_offer((game.get("totals_offers") or []) + (game.get("h2h_offers") or [])) else 0),
            event_id,
        )
        ranked.append((rank, game))
    ranked.sort(key=lambda item: item[0])
    return [game for _rank, game in ranked[:max_games]]


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
    scan_label: str = "Scheduled Board Drop",
    mst_anchor_time: str | None = None,
    retry_supabase: Callable,
    log_event: Callable[..., None],
) -> dict[str, Any]:
    """
    Canonical daily-board publisher.

    Steps:
    1) Broad NBA totals fetch (slate-level) for selection + context.
    2) Select up to 4 games for the board.
    3) Scan straight bets (multi-sport) for EV-ranked Game Lines cards.
    4) Scan player props for the full NBA slate across 5 flagship markets.
    5) Capture research opportunities from fresh board sides.
    6) Persist board:latest with game_context + straight_bets + player_props.
    """
    from models import FullScanResponse as _FSR
    from services.board_snapshot import persist_board_snapshot
    from services.odds_api import SUPPORTED_SPORTS, fetch_events, fetch_featured_lines_slate, get_cached_or_scan
    from services.player_props import scan_player_props_for_event_ids
    from services.research_opportunities import capture_scan_opportunities
    from services.scan_markets import (
        aggregate_manual_scan_all_sports,
        manual_scan_sports_for_env,
        scanned_at_from_fetched_timestamp,
    )

    started_at = time.monotonic()
    scanned_at = _utc_now_iso()

    featured_nba_task = fetch_featured_lines_slate(sport="basketball_nba", source=source)
    featured_cbb_task = fetch_featured_lines_slate(sport="basketball_ncaab", source=source)
    featured_mlb_task = fetch_featured_lines_slate(sport="baseball_mlb", source=source)
    nba_events_task = fetch_events(DAILY_BOARD_SPORT, source=f"{source}_props_events")

    (
        featured_nba_raw,
        featured_cbb_raw,
        featured_mlb_raw,
        nba_events_resp_raw,
    ) = await asyncio.gather(
        featured_nba_task,
        featured_cbb_task,
        featured_mlb_task,
        nba_events_task,
        return_exceptions=True,
    )

    if isinstance(featured_nba_raw, Exception):
        raise featured_nba_raw
    featured_nba_payload = featured_nba_raw

    if isinstance(featured_cbb_raw, Exception):
        log_event(
            "daily_board.featured_lines.failed",
            level="warning",
            source=source,
            sport="basketball_ncaab",
            error_class=type(featured_cbb_raw).__name__,
            error=str(featured_cbb_raw),
        )
        featured_cbb_payload = {"sport": "basketball_ncaab", "games": [], "events_fetched": 0, "api_requests_remaining": None}
    else:
        featured_cbb_payload = featured_cbb_raw

    if isinstance(featured_mlb_raw, Exception):
        log_event(
            "daily_board.featured_lines.failed",
            level="warning",
            source=source,
            sport="baseball_mlb",
            error_class=type(featured_mlb_raw).__name__,
            error=str(featured_mlb_raw),
        )
        featured_mlb_payload = {"sport": "baseball_mlb", "games": [], "events_fetched": 0, "api_requests_remaining": None}
    else:
        featured_mlb_payload = featured_mlb_raw

    if isinstance(nba_events_resp_raw, Exception):
        raise nba_events_resp_raw
    nba_events_resp = nba_events_resp_raw

    totals_games = featured_nba_payload.get("games") if isinstance(featured_nba_payload, dict) else []
    totals_games = totals_games if isinstance(totals_games, list) else []

    selected_games = _select_daily_games(totals_games, max_games=DAILY_BOARD_MAX_GAMES)
    selected_event_ids = [
        str(game.get("event_id") or "").strip()
        for game in selected_games
        if str(game.get("event_id") or "").strip()
    ]

    nba_events_payload, nba_events_http = nba_events_resp
    nba_events = nba_events_payload if isinstance(nba_events_payload, list) else []
    full_slate_event_ids = [
        str(event.get("id") or "").strip()
        for event in nba_events
        if str(event.get("id") or "").strip()
    ]

    sports_to_scan = manual_scan_sports_for_env(
        environment=os.getenv("ENVIRONMENT", "production"),
        supported_sports=SUPPORTED_SPORTS,
    )
    straight_aggregate = await aggregate_manual_scan_all_sports(
        sports_to_scan=sports_to_scan,
        get_cached_or_scan=lambda sport: get_cached_or_scan(sport, source=source),
    )
    straight_sides = [
        side if isinstance(side, dict) and side.get("surface") else {"surface": "straight_bets", **side}
        for side in (straight_aggregate.get("all_sides") or [])
        if isinstance(side, dict)
    ]
    straight_scanned_at = scanned_at_from_fetched_timestamp(straight_aggregate.get("oldest_fetched")) or scanned_at

    props_result = await scan_player_props_for_event_ids(
        sport=DAILY_BOARD_SPORT,
        event_ids=full_slate_event_ids,
        markets=DAILY_BOARD_PROP_MARKETS,
        source=source,
    )
    props_sides = props_result.get("sides") or []

    # Persist +EV board sides into scan_opportunities for both surfaces.
    if db is not None:
        try:
            straight_surface_sides = [
                {**s, "surface": "straight_bets"} if isinstance(s, dict) else s
                for s in straight_sides
            ]
            props_surface_sides = [
                {**s, "surface": "player_props"} if isinstance(s, dict) else s
                for s in props_sides
            ]
            capture_scan_opportunities(
                db,
                sides=[*straight_surface_sides, *props_surface_sides],
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

    straight_payload = _FSR(
        surface="straight_bets",
        sport="all",
        sides=straight_sides,
        events_fetched=int(straight_aggregate.get("total_events") or 0),
        events_with_both_books=int(straight_aggregate.get("total_with_both") or 0),
        api_requests_remaining=straight_aggregate.get("min_remaining"),
        scanned_at=straight_scanned_at,
        diagnostics=straight_aggregate.get("diagnostics"),
        prizepicks_cards=straight_aggregate.get("prizepicks_cards"),
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

    featured_nba_games = _rank_featured_games(
        featured_nba_payload.get("games") if isinstance(featured_nba_payload, dict) else [],
        max_games=FEATURED_LINES_PER_SPORT_CAP,
    )
    featured_cbb_games = _rank_featured_games(
        featured_cbb_payload.get("games") if isinstance(featured_cbb_payload, dict) else [],
        max_games=FEATURED_LINES_PER_SPORT_CAP,
    )
    featured_mlb_games = _rank_featured_games(
        featured_mlb_payload.get("games") if isinstance(featured_mlb_payload, dict) else [],
        max_games=FEATURED_LINES_PER_SPORT_CAP,
    )

    game_context = {
        "sport": DAILY_BOARD_SPORT,
        "selection_mode": "totals_slate",
        "selection_params": {
            "min_post_drop_lead_minutes": DAILY_BOARD_MIN_POST_DROP_LEAD_MINUTES,
            "min_totals_offers": DAILY_BOARD_MIN_TOTALS_OFFERS,
        },
        "selected_event_ids": selected_event_ids,
        "props_scan_event_ids": full_slate_event_ids,
        "props_scan_scope": "full_nba_slate",
        "scan_label": scan_label,
        "scan_anchor_timezone": "America/Phoenix",
        "scan_anchor_time_mst": mst_anchor_time,
        "games": selected_games,
        "events_fetched": int(featured_nba_payload.get("events_fetched") or 0),
        "api_requests_remaining": featured_nba_payload.get("api_requests_remaining"),
        "featured_lines": {
            "basketball_nba": featured_nba_games,
            "basketball_ncaab": featured_cbb_games,
            "baseball_mlb": featured_mlb_games,
        },
        "featured_lines_meta": {
            "basketball_nba": {
                "events_fetched": int(featured_nba_payload.get("events_fetched") or 0),
                "api_requests_remaining": featured_nba_payload.get("api_requests_remaining"),
                "games_included": len(featured_nba_games),
            },
            "basketball_ncaab": {
                "events_fetched": int(featured_cbb_payload.get("events_fetched") or 0),
                "api_requests_remaining": featured_cbb_payload.get("api_requests_remaining"),
                "games_included": len(featured_cbb_games),
            },
            "baseball_mlb": {
                "events_fetched": int(featured_mlb_payload.get("events_fetched") or 0),
                "api_requests_remaining": featured_mlb_payload.get("api_requests_remaining"),
                "games_included": len(featured_mlb_games),
            },
            "captured_at": scanned_at,
            "stale_after_seconds": FEATURED_LINES_STALE_AFTER_SECONDS,
        },
        "nba_props_events_meta": {
            "events_fetched": len(nba_events),
            "api_requests_remaining": nba_events_http.headers.get("x-requests-remaining")
            or nba_events_http.headers.get("x-request-remaining"),
        },
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
        scan_label=scan_label,
        mst_anchor_time=mst_anchor_time,
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
        "scan_label": scan_label,
        "mst_anchor_time": mst_anchor_time,
        "selected_event_ids": selected_event_ids,
        "props_scan_event_ids": full_slate_event_ids,
        "selected_games": selected_games,
        "props_sides": len(props_sides),
        "featured_games_count": len(featured_nba_games) + len(featured_cbb_games) + len(featured_mlb_games),
        "props_events_scanned": len(full_slate_event_ids),
        "duration_ms": duration_ms,
    }

