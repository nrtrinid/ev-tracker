from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo
from uuid import uuid4

from utils.telemetry import rss_mb


DAILY_BOARD_SPORT = "basketball_nba"
DAILY_BOARD_MAX_GAMES = 4
DAILY_BOARD_GAME_LINE_SPORTS = [
    "basketball_nba",
    "baseball_mlb",
]
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


def _approx_sampled_json_bytes(value: Any, *, sample_sides: int = 100) -> int | None:
    """
    Best-effort, cheap-ish size proxy.
    Avoids dumping entire payloads by sampling up to N sides when present.
    """
    try:
        import json
    except Exception:
        return None
    try:
        if isinstance(value, dict) and isinstance(value.get("sides"), list):
            sides = value["sides"]
            sampled = dict(value)
            sampled["sides"] = sides[:sample_sides]
            return len(json.dumps(sampled, default=str))
        return len(json.dumps(value, default=str))
    except Exception:
        return None


def _ensure_surface_in_place(sides: list[Any], *, surface: str) -> None:
    for side in sides:
        if isinstance(side, dict) and not side.get("surface"):
            side["surface"] = surface


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cap_payload_sides(
    payload: dict[str, Any],
    *,
    max_sides: int | None,
    surface: str,
    run_id: str,
    log_event: Callable[..., None],
) -> dict[str, Any]:
    if not max_sides or max_sides <= 0:
        return payload
    sides_raw = payload.get("sides")
    if not isinstance(sides_raw, list):
        return payload
    total = len(sides_raw)
    if total <= max_sides:
        return payload

    capped = dict(payload)
    capped["sides"] = sides_raw[:max_sides]
    diagnostics = capped.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    capped["diagnostics"] = {
        **diagnostics,
        "latest_cache_capped": True,
        "latest_cache_original_sides": total,
        "latest_cache_max_sides": max_sides,
    }
    log_event(
        "board.drop.surface_payload_capped",
        level="warning",
        run_id=run_id,
        surface=surface,
        original_sides=total,
        capped_sides=max_sides,
        rss_mb=rss_mb(),
    )
    return capped


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
    3) Scan straight bets for EV-ranked NBA + MLB Game Lines cards.
    4) Scan player props for the full NBA slate across 5 flagship markets.
    5) Capture research opportunities from fresh board sides.
    6) Persist board:latest with game_context + straight_bets + player_props.
    """
    from models import FullScanResponse as _FSR
    from services.board_snapshot import persist_board_meta_snapshot
    from services.odds_api import fetch_events, fetch_featured_lines_slate, get_cached_or_scan
    from services.pickem_research import capture_pickem_research_observations
    from services.player_prop_board import (
        build_player_prop_board_item,
        build_player_prop_board_pickem_cards,
        persist_player_prop_board_artifacts,
    )
    from services.player_props import scan_player_props_for_event_ids
    from services.research_opportunities import capture_scan_opportunities
    from services.scan_cache import persist_latest_scan_payload
    from services.scan_markets import (
        aggregate_manual_scan_all_sports,
        manual_scan_sports_for_env,
        scanned_at_from_fetched_timestamp,
    )

    run_id = f"board_{uuid4().hex[:12]}"
    started_at = time.monotonic()
    scanned_at = _utc_now_iso()

    log_event(
        "board.drop.started",
        run_id=run_id,
        source=source,
        scanned_at=scanned_at,
        rss_mb=rss_mb(),
    )

    featured_nba_task = fetch_featured_lines_slate(sport="basketball_nba", source=source)
    featured_mlb_task = fetch_featured_lines_slate(sport="baseball_mlb", source=source)
    nba_events_task = fetch_events(DAILY_BOARD_SPORT, source=f"{source}_props_events")

    (
        featured_nba_raw,
        featured_mlb_raw,
        nba_events_resp_raw,
    ) = await asyncio.gather(
        featured_nba_task,
        featured_mlb_task,
        nba_events_task,
        return_exceptions=True,
    )

    if isinstance(featured_nba_raw, Exception):
        raise featured_nba_raw
    featured_nba_payload = featured_nba_raw

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
        supported_sports=list(DAILY_BOARD_GAME_LINE_SPORTS),
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
    log_event(
        "board.drop.straight_built",
        run_id=run_id,
        source=source,
        straight_sides=len(straight_sides),
        rss_mb=rss_mb(),
        approx_bytes_sampled=_approx_sampled_json_bytes({"sides": straight_sides}, sample_sides=80),
    )

    props_result = await scan_player_props_for_event_ids(
        sport=DAILY_BOARD_SPORT,
        event_ids=full_slate_event_ids,
        markets=DAILY_BOARD_PROP_MARKETS,
        source=source,
    )
    props_sides = props_result.get("sides") or []
    if isinstance(props_sides, list):
        _ensure_surface_in_place(props_sides, surface="player_props")
    log_event(
        "board.drop.props_built",
        run_id=run_id,
        source=source,
        player_sides=len(props_sides) if isinstance(props_sides, list) else None,
        rss_mb=rss_mb(),
        approx_bytes_sampled=_approx_sampled_json_bytes({"sides": props_sides}, sample_sides=80) if isinstance(props_sides, list) else None,
    )

    # Persist +EV board sides into scan_opportunities for both surfaces.
    if db is not None:
        try:
            capture_scan_opportunities(
                db,
                # Avoid extra copies here; capture_scan_opportunities already copies each eligible side.
                sides=[*straight_sides, *(props_sides if isinstance(props_sides, list) else [])],
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

    # Build payload dicts manually to avoid Pydantic model_dump() copying large sides arrays.
    straight_payload: dict[str, Any] = {
        "surface": "straight_bets",
        "sport": "all",
        "sides": straight_sides,
        "events_fetched": int(straight_aggregate.get("total_events") or 0),
        "events_with_both_books": int(straight_aggregate.get("total_with_both") or 0),
        "api_requests_remaining": straight_aggregate.get("min_remaining"),
        "scanned_at": straight_scanned_at,
        "diagnostics": straight_aggregate.get("diagnostics"),
        "prizepicks_cards": straight_aggregate.get("prizepicks_cards"),
    }

    props_payload: dict[str, Any] = {
        "surface": "player_props",
        "sport": DAILY_BOARD_SPORT,
        "sides": (props_sides if isinstance(props_sides, list) else []),
        "events_fetched": int(props_result.get("events_fetched") or 0),
        "events_with_both_books": int(props_result.get("events_with_both_books") or 0),
        "api_requests_remaining": props_result.get("api_requests_remaining"),
        "scanned_at": props_result.get("scanned_at") or scanned_at,
        "diagnostics": props_result.get("diagnostics"),
        "prizepicks_cards": props_result.get("prizepicks_cards"),
    }

    board_props_artifacts_summary: dict[str, Any] | None = None
    if db is not None:
        board_chunk_size = int(os.getenv("PLAYER_PROPS_BOARD_CHUNK_SIZE") or "250") or 250
        board_legacy_max = int(os.getenv("PLAYER_PROPS_BOARD_LEGACY_MAX_ITEMS") or "150") or 150
        board_props_artifacts_summary = persist_player_prop_board_artifacts(
            db=db,
            payload=props_payload,
            retry_supabase=retry_supabase,
            log_event=log_event,
            chunk_size=board_chunk_size,
            legacy_max_items=board_legacy_max,
        )
        log_event(
            "board.drop.player_props_board_artifacts_persisted",
            run_id=run_id,
            source=source,
            chunk_size=board_chunk_size,
            legacy_max_items=board_legacy_max,
            lean_total=board_props_artifacts_summary.get("lean_total") if isinstance(board_props_artifacts_summary, dict) else None,
            opportunities_total=board_props_artifacts_summary.get("opportunities_total") if isinstance(board_props_artifacts_summary, dict) else None,
            pickem_total=board_props_artifacts_summary.get("pickem_total") if isinstance(board_props_artifacts_summary, dict) else None,
            detail_total=board_props_artifacts_summary.get("detail_total") if isinstance(board_props_artifacts_summary, dict) else None,
            rss_mb=rss_mb(),
        )
        try:
            raw_pickem_cards = props_payload.get("pickem_cards")
            if isinstance(raw_pickem_cards, list):
                pickem_cards = [card for card in raw_pickem_cards if isinstance(card, dict)]
            else:
                pickem_cards = build_player_prop_board_pickem_cards(
                    [
                        build_player_prop_board_item(side)
                        for side in props_sides
                        if isinstance(side, dict)
                    ]
                )
            pickem_capture = capture_pickem_research_observations(
                db,
                cards=pickem_cards,
                source=source,
                captured_at=str(props_payload.get("scanned_at") or scanned_at),
            )
            log_event(
                "board.drop.pickem_research_captured",
                run_id=run_id,
                source=source,
                eligible_seen=pickem_capture.get("eligible_seen") if isinstance(pickem_capture, dict) else None,
                inserted=pickem_capture.get("inserted") if isinstance(pickem_capture, dict) else None,
                updated=pickem_capture.get("updated") if isinstance(pickem_capture, dict) else None,
                rss_mb=rss_mb(),
            )
        except Exception as exc:
            log_event(
                "board.drop.pickem_research_capture_failed",
                level="warning",
                run_id=run_id,
                source=source,
                error_class=type(exc).__name__,
                error=str(exc),
            )

    featured_nba_games = _rank_featured_games(
        featured_nba_payload.get("games") if isinstance(featured_nba_payload, dict) else [],
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
        "game_lines_scan_sports": sports_to_scan,
        "events_fetched": int(featured_nba_payload.get("events_fetched") or 0),
        "api_requests_remaining": featured_nba_payload.get("api_requests_remaining"),
        "featured_lines": {
            "basketball_nba": featured_nba_games,
            "baseball_mlb": featured_mlb_games,
        },
        "featured_lines_meta": {
            "basketball_nba": {
                "events_fetched": int(featured_nba_payload.get("events_fetched") or 0),
                "api_requests_remaining": featured_nba_payload.get("api_requests_remaining"),
                "games_included": len(featured_nba_games),
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
        # Persist per-surface latest caches for lazy loading.
        log_event(
            "board.drop.before_persist_surface",
            run_id=run_id,
            source=source,
            straight_sides=len(straight_payload.get("sides") or []),
            player_sides=len(props_payload.get("sides") or []),
            rss_mb=rss_mb(),
        )

        max_straight = int(os.getenv("SURFACE_LATEST_MAX_SIDES_STRAIGHT_BETS") or "0") or None
        max_props = int(os.getenv("SURFACE_LATEST_MAX_SIDES_PLAYER_PROPS") or "0") or None
        straight_payload_to_persist = _cap_payload_sides(
            straight_payload,
            max_sides=max_straight,
            surface="straight_bets",
            run_id=run_id,
            log_event=log_event,
        )
        props_payload_to_persist = _cap_payload_sides(
            props_payload,
            max_sides=max_props,
            surface="player_props",
            run_id=run_id,
            log_event=log_event,
        )

        try:
            persist_latest_scan_payload(
                db=db,
                payload=straight_payload_to_persist,
                retry_supabase=retry_supabase,
                log_event=log_event,
                surface="straight_bets",
                scope="latest",
            )
        except Exception as exc:
            log_event(
                "daily_board.persist_surface_latest_failed",
                level="warning",
                surface="straight_bets",
                error_class=type(exc).__name__,
                error=str(exc),
            )
        try:
            persist_latest_scan_payload(
                db=db,
                payload=props_payload_to_persist,
                retry_supabase=retry_supabase,
                log_event=log_event,
                surface="player_props",
                scope="latest",
            )
        except Exception as exc:
            log_event(
                "daily_board.persist_surface_latest_failed",
                level="warning",
                surface="player_props",
                error_class=type(exc).__name__,
                error=str(exc),
            )

        log_event(
            "board.drop.after_persist_surface",
            run_id=run_id,
            source=source,
            rss_mb=rss_mb(),
        )

        # Release large refs ASAP before meta snapshot persistence / any downstream work.
        try:
            del straight_payload_to_persist
            del props_payload_to_persist
        except Exception:
            pass

        log_event(
            "board.drop.before_persist_meta",
            run_id=run_id,
            source=source,
            rss_mb=rss_mb(),
        )
        snapshot_id = persist_board_meta_snapshot(
            db=db,
            snapshot_type="scheduled",
            scanned_at=scanned_at,
            retry_supabase=retry_supabase,
            log_event=log_event,
            game_context=game_context,
            surfaces_included=["straight_bets", "player_props"],
            sports_included=list(dict.fromkeys([*sports_to_scan, DAILY_BOARD_SPORT])),
            events_scanned=int(straight_aggregate.get("total_events") or 0) + int(props_result.get("events_fetched") or 0),
            total_sides=len(straight_sides) + len(props_sides),
        )
        log_event(
            "board.drop.completed",
            run_id=run_id,
            source=source,
            snapshot_id=snapshot_id,
            rss_mb=rss_mb(),
        )

    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    props_diagnostics = props_result.get("diagnostics") if isinstance(props_result.get("diagnostics"), dict) else {}
    board_props_counts = (
        board_props_artifacts_summary if isinstance(board_props_artifacts_summary, dict) else {}
    )
    game_lines_summary = {
        "sports_scanned": sports_to_scan,
        "events_fetched": int(straight_aggregate.get("total_events") or 0),
        "events_with_both_books": int(straight_aggregate.get("total_with_both") or 0),
        "api_requests_remaining": straight_aggregate.get("min_remaining"),
        "surfaced_sides": len(straight_sides),
        "fresh_sides_count": len(straight_aggregate.get("fresh_sides") or []),
    }
    player_props_summary = {
        "events_scanned": len(full_slate_event_ids),
        "events_fetched": int(props_result.get("events_fetched") or 0),
        "events_with_both_books": int(props_result.get("events_with_both_books") or 0),
        "api_requests_remaining": props_result.get("api_requests_remaining"),
        "events_skipped_pregame": _coerce_int(props_diagnostics.get("events_skipped_pregame")),
        "events_with_results": _coerce_int(props_diagnostics.get("events_with_results")),
        "candidate_sides": _coerce_int(props_diagnostics.get("candidate_sides_count")),
        "quality_gate_filtered": _coerce_int(props_diagnostics.get("quality_gate_filtered_count")),
        "quality_gate_min_reference_bookmakers": _coerce_optional_int(
            props_diagnostics.get("quality_gate_min_reference_bookmakers")
        ),
        "pickem_quality_gate_min_reference_bookmakers": _coerce_optional_int(
            props_diagnostics.get("pickem_quality_gate_min_reference_bookmakers")
        ),
        "pickem_cards_count": _coerce_int(
            props_diagnostics.get("pickem_cards_count"),
            default=len(props_result.get("pickem_cards") or []),
        ),
        "markets_requested": (
            list(props_diagnostics.get("markets_requested") or [])
            if isinstance(props_diagnostics.get("markets_requested"), list)
            else list(DAILY_BOARD_PROP_MARKETS)
        ),
        "surfaced_sides": len(props_sides),
        "board_items": {
            "browse_total": _coerce_int(board_props_counts.get("browse_total"), default=len(props_sides)),
            "opportunities_total": _coerce_int(board_props_counts.get("opportunities_total")),
            "pickem_total": _coerce_int(
                board_props_counts.get("pickem_total"),
                default=len(props_result.get("pickem_cards") or []),
            ),
            "legacy_total": _coerce_int(board_props_counts.get("legacy_total")),
            "detail_total": _coerce_int(board_props_counts.get("detail_total")),
        },
    }
    board_summary = {
        "scan_label": scan_label,
        "anchor_time_mst": mst_anchor_time,
        "selected_event_ids": selected_event_ids,
        "selected_event_count": len(selected_event_ids),
        "selected_games": selected_games,
        "selected_games_count": len(selected_games),
        "props_scan_event_ids": full_slate_event_ids,
        "props_scan_event_count": len(full_slate_event_ids),
        "straight_sides": len(straight_sides),
        "props_sides": len(props_sides),
        "total_sides": len(straight_sides) + len(props_sides),
        "featured_games_count": len(featured_nba_games) + len(featured_mlb_games),
        "game_line_sports_scanned": sports_to_scan,
        "game_lines_events_fetched": game_lines_summary["events_fetched"],
        "game_lines_events_with_both_books": game_lines_summary["events_with_both_books"],
        "game_lines_api_requests_remaining": game_lines_summary["api_requests_remaining"],
        "props_events_scanned": player_props_summary["events_scanned"],
        "props_events_fetched": player_props_summary["events_fetched"],
        "props_events_with_both_books": player_props_summary["events_with_both_books"],
        "props_api_requests_remaining": player_props_summary["api_requests_remaining"],
        "props_candidate_sides": player_props_summary["candidate_sides"],
        "props_quality_gate_filtered": player_props_summary["quality_gate_filtered"],
        "props_events_skipped_pregame": player_props_summary["events_skipped_pregame"],
        "props_events_with_results": player_props_summary["events_with_results"],
        "props_quality_gate_min_reference_bookmakers": player_props_summary[
            "quality_gate_min_reference_bookmakers"
        ],
        "props_pickem_quality_gate_min_reference_bookmakers": player_props_summary[
            "pickem_quality_gate_min_reference_bookmakers"
        ],
        "props_pickem_cards_count": player_props_summary["pickem_cards_count"],
        "player_props_board_artifacts": player_props_summary["board_items"],
        "game_lines": game_lines_summary,
        "player_props": player_props_summary,
        "duration_ms": duration_ms,
    }
    log_event(
        "daily_board.drop.completed",
        run_id=run_id,
        source=source,
        scan_label=scan_label,
        mst_anchor_time=mst_anchor_time,
        snapshot_id=snapshot_id,
        scanned_at=scanned_at,
        selected_games=len(selected_games),
        props_sides=len(props_sides),
        duration_ms=duration_ms,
        rss_mb=rss_mb(),
    )

    return {
        "ok": True,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "scanned_at": scanned_at,
        "scan_label": scan_label,
        "mst_anchor_time": mst_anchor_time,
        "selected_event_ids": selected_event_ids,
        "props_scan_event_ids": full_slate_event_ids,
        "selected_games": selected_games,
        "straight_sides": len(straight_sides),
        "props_sides": len(props_sides),
        "featured_games_count": len(featured_nba_games) + len(featured_mlb_games),
        "game_line_sports_scanned": sports_to_scan,
        "game_lines_events_fetched": int(straight_aggregate.get("total_events") or 0),
        "game_lines_events_with_both_books": int(straight_aggregate.get("total_with_both") or 0),
        "game_lines_api_requests_remaining": straight_aggregate.get("min_remaining"),
        "props_events_scanned": len(full_slate_event_ids),
        "props_events_fetched": int(props_result.get("events_fetched") or 0),
        "props_events_with_both_books": int(props_result.get("events_with_both_books") or 0),
        "props_api_requests_remaining": props_result.get("api_requests_remaining"),
        "props_candidate_sides": _coerce_int(props_diagnostics.get("candidate_sides_count")),
        "props_quality_gate_filtered": _coerce_int(props_diagnostics.get("quality_gate_filtered_count")),
        "props_events_skipped_pregame": _coerce_int(props_diagnostics.get("events_skipped_pregame")),
        "props_events_with_results": _coerce_int(props_diagnostics.get("events_with_results")),
        "props_quality_gate_min_reference_bookmakers": _coerce_optional_int(
            props_diagnostics.get("quality_gate_min_reference_bookmakers")
        ),
        "props_pickem_quality_gate_min_reference_bookmakers": _coerce_optional_int(
            props_diagnostics.get("pickem_quality_gate_min_reference_bookmakers")
        ),
        "props_pickem_cards_count": _coerce_int(
            props_diagnostics.get("pickem_cards_count"),
            default=len(props_result.get("pickem_cards") or []),
        ),
        "player_props_board_artifacts": player_props_summary["board_items"],
        "duration_ms": duration_ms,
        "fresh_straight_sides_count": len(straight_aggregate.get("fresh_sides") or []),
        "fresh_prop_sides_count": len(props_sides) if isinstance(props_sides, list) else 0,
        "fresh_straight_sides": straight_aggregate.get("fresh_sides") or [],
        "fresh_prop_sides": props_sides if isinstance(props_sides, list) else [],
        "summary": board_summary,
    }

