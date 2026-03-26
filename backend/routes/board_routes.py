"""Board API routes.

GET  /api/board/latest  — returns the canonical board snapshot (no outbound calls)
POST /api/board/refresh — scoped manual refresh (rate-limited, does NOT overwrite board:latest)
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from database import get_db
from models import BoardResponse, BoardSnapshotMeta, FullScanResponse, ScopedRefreshResponse
from services.board_snapshot import load_board_snapshot, persist_scoped_refresh
from services.bet_crud import _retry_supabase

router = APIRouter()

_EMPTY_META = BoardSnapshotMeta(
    snapshot_id="none",
    snapshot_type="scheduled",
    scanned_at="",
    surfaces_included=[],
    sports_included=[],
    next_scheduled_drop=None,
    events_scanned=0,
    total_sides=0,
)


def _empty_surface(surface: str) -> FullScanResponse:
    return FullScanResponse(
        surface=surface,  # type: ignore[arg-type]
        sport="all",
        sides=[],
        events_fetched=0,
        events_with_both_books=0,
        api_requests_remaining=None,
        scanned_at=None,
    )


def _load_surface_fallback(db, surface: str) -> FullScanResponse | None:
    """Try the per-surface latest cache (straight_bets:latest / player_props:latest).

    Used when the canonical board:latest snapshot is absent or lacks a given surface.
    Never triggers outbound API calls.
    """
    from services.scan_cache import load_latest_scan_payload
    try:
        raw = load_latest_scan_payload(db=db, retry_supabase=_retry_supabase, surface=surface)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return FullScanResponse(**raw)
    except Exception:
        return None


def _meta_from_fallback_surfaces(
    straight: FullScanResponse | None,
    player: FullScanResponse | None,
) -> BoardSnapshotMeta:
    """Build a synthetic BoardSnapshotMeta when serving entirely from per-surface fallbacks."""
    surfaces_included: list[str] = []
    sports_included: list[str] = []
    total_sides = 0
    total_events = 0
    scanned_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    if straight:
        surfaces_included.append("straight_bets")
        if straight.sport not in sports_included:
            sports_included.append(straight.sport)
        total_sides += len(straight.sides)
        total_events += straight.events_fetched
        if straight.scanned_at:
            scanned_at = straight.scanned_at

    if player:
        surfaces_included.append("player_props")
        if player.sport not in sports_included:
            sports_included.append(player.sport)
        total_sides += len(player.sides)
        total_events += player.events_fetched
        # Use player scanned_at only if straight didn't provide one
        if player.scanned_at and not (straight and straight.scanned_at):
            scanned_at = player.scanned_at

    snapshot_id = f"fallback_{abs(hash(scanned_at)) % 0xFFFFFF:06x}"
    return BoardSnapshotMeta(
        snapshot_id=snapshot_id,
        snapshot_type="manual",
        scanned_at=scanned_at,
        surfaces_included=surfaces_included,  # type: ignore[arg-type]
        sports_included=sports_included,
        next_scheduled_drop=None,
        events_scanned=total_events,
        total_sides=total_sides,
    )


@router.get("/board/latest", response_model=BoardResponse)
def get_board_latest(user: dict = Depends(get_current_user)):
    """Return the latest canonical board snapshot.

    Pure DB read — never triggers outbound API calls.
    Falls back to per-surface latest caches (straight_bets:latest / player_props:latest)
    when the canonical board is absent or missing a surface.
    Returns an empty board only if no data exists anywhere.
    """
    db = get_db()
    try:
        raw = load_board_snapshot(db=db, retry_supabase=_retry_supabase)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load board: {e}")

    if raw is None:
        # No canonical board yet — try per-surface fallbacks before returning empty
        straight = _load_surface_fallback(db, "straight_bets")
        player = _load_surface_fallback(db, "player_props")
        if straight is None and player is None:
            return BoardResponse(meta=_EMPTY_META, straight_bets=None, player_props=None)
        return BoardResponse(
            meta=_meta_from_fallback_surfaces(straight, player),
            straight_bets=straight,
            player_props=player,
        )

    meta_raw = raw.get("meta") or {}
    try:
        meta = BoardSnapshotMeta(**meta_raw)
    except Exception:
        meta = _EMPTY_META

    game_context = raw.get("game_context") if isinstance(raw, dict) else None
    if not isinstance(game_context, dict):
        game_context = None

    straight_raw = raw.get("straight_bets")
    player_raw = raw.get("player_props")

    straight = None
    if isinstance(straight_raw, dict):
        try:
            straight = FullScanResponse(**straight_raw)
        except Exception:
            straight = None
    # If this surface is absent from the canonical board, check per-surface cache
    if straight is None:
        straight = _load_surface_fallback(db, "straight_bets")

    player = None
    if isinstance(player_raw, dict):
        try:
            player = FullScanResponse(**player_raw)
        except Exception:
            player = None
    # If this surface is absent from the canonical board, check per-surface cache
    if player is None:
        player = _load_surface_fallback(db, "player_props")

    return BoardResponse(meta=meta, game_context=game_context, straight_bets=straight, player_props=player)


@router.post("/board/refresh", response_model=ScopedRefreshResponse)
async def refresh_board_scope(
    scope: str = Query(default="player_props", description="Surface to refresh: straight_bets or player_props"),
    user: dict = Depends(get_current_user),
):
    """Trigger a scoped manual refresh for a specific surface.

    Rate-limited. Writes to a scoped cache key and does NOT overwrite the
    canonical board:latest snapshot.
    """
    from services.shared_state import allow_fixed_window_rate_limit
    uid = user["id"]
    allowed = allow_fixed_window_rate_limit(
        bucket_key=f"board_refresh:{uid}",
        max_requests=3,
        window_seconds=15 * 60,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many refresh requests. Please try again in a few minutes.",
        )

    if scope not in ("straight_bets", "player_props"):
        raise HTTPException(status_code=400, detail="scope must be straight_bets or player_props")

    db = get_db()

    try:
        if scope == "player_props":
            from services.player_props import get_cached_or_scan_player_props
            result = await get_cached_or_scan_player_props("basketball_nba", source="manual_refresh")
        else:
            from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS
            merged_sides: list = []
            total_fetched = 0
            total_both = 0
            api_rem = None
            scanned_at = None
            for sport_key in SUPPORTED_SPORTS:
                r = await get_cached_or_scan(sport_key, source="manual_refresh")
                merged_sides.extend(r.get("sides") or [])
                total_fetched += int(r.get("events_fetched") or 0)
                total_both += int(r.get("events_with_both_books") or 0)
                if r.get("api_requests_remaining") is not None:
                    api_rem = r["api_requests_remaining"]
                if scanned_at is None:
                    scanned_at = r.get("scanned_at")
            result = {
                "surface": "straight_bets",
                "sport": "all",
                "sides": merged_sides,
                "events_fetched": total_fetched,
                "events_with_both_books": total_both,
                "api_requests_remaining": api_rem,
                "scanned_at": scanned_at,
            }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Refresh failed: {e}")

    try:
        scan_payload = FullScanResponse(
            surface=scope,  # type: ignore[arg-type]
            sport=result.get("sport") or ("basketball_nba" if scope == "player_props" else "all"),
            sides=result.get("sides") or [],
            events_fetched=int(result.get("events_fetched") or 0),
            events_with_both_books=int(result.get("events_with_both_books") or 0),
            api_requests_remaining=result.get("api_requests_remaining"),
            scanned_at=result.get("scanned_at"),
            diagnostics=result.get("diagnostics"),
            prizepicks_cards=result.get("prizepicks_cards"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build response: {e}")

    from main import _log_event
    refreshed_at = persist_scoped_refresh(
        db=db,
        surface=scope,
        scan_payload=scan_payload.model_dump(),
        retry_supabase=_retry_supabase,
        log_event=_log_event,
    )

    return ScopedRefreshResponse(
        surface=scope,  # type: ignore[arg-type]
        refreshed_at=refreshed_at,
        data=scan_payload,
    )
