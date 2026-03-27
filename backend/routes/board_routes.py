"""Board API routes.

GET  /api/board/latest  — returns the canonical board snapshot (no outbound calls)
POST /api/board/refresh — scoped manual refresh (rate-limited, does NOT overwrite board:latest)
"""

from __future__ import annotations

import os

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from auth import get_current_user
from database import get_db
from models import BoardResponse, BoardSnapshotMeta, FullScanResponse, ScopedRefreshResponse
from services.board_snapshot import load_board_snapshot, persist_scoped_refresh
from services.bet_crud import _retry_supabase
from utils.telemetry import rss_mb
from utils.time_utils import utc_now_iso_z

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
    scanned_at = utc_now_iso_z()

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
    from main import _log_event

    request_id = f"board_latest_{uuid4().hex[:10]}"
    rss_before = rss_mb()
    # With chunked board loading, /board/latest should be meta + game_context only.
    # Sides are served via /board/latest/surface.
    _log_event(
        "board.latest.started",
        request_id=request_id,
        rss_mb=rss_before,
        user_id=str(user.get("id") or ""),
    )

    db = get_db()
    try:
        raw = load_board_snapshot(db=db, retry_supabase=_retry_supabase)
    except Exception as e:
        _log_event(
            "board.latest.load_failed",
            level="warning",
            request_id=request_id,
            rss_mb=rss_mb(),
            error_class=type(e).__name__,
            error=str(e),
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "board_load_failed",
                "request_id": request_id,
                "message": "Failed to load board snapshot.",
                "error_class": type(e).__name__,
            },
        )

    # Helper: build a response dict and return as JSONResponse to avoid
    # heavyweight Pydantic parsing/serialization on large cached payloads.
    def _safe_keys(value: object) -> list[str]:
        return sorted(list(value.keys())) if isinstance(value, dict) else []

    def _build_response_payload(*, raw_board: dict | None) -> dict:
        if raw_board is None:
            return {
                "meta": _EMPTY_META.model_dump(),
                "game_context": None,
                "straight_bets": None,
                "player_props": None,
            }

        meta = raw_board.get("meta") if isinstance(raw_board.get("meta"), dict) else None
        if not meta:
            meta = _EMPTY_META.model_dump()
            meta["scanned_at"] = utc_now_iso_z()
        game_context = raw_board.get("game_context")
        if not isinstance(game_context, dict):
            game_context = None

        # Meta-only: do not return surfaces from board:latest.
        straight = None
        player = None
        return {
            "meta": meta,
            "game_context": game_context,
            "straight_bets": straight,
            "player_props": player,
        }

    try:
        raw_board = raw if isinstance(raw, dict) else None
        meta_raw = raw_board.get("meta") if isinstance(raw_board, dict) else None
        game_context_raw = raw_board.get("game_context") if isinstance(raw_board, dict) else None

        _log_event(
            "board.latest.cache_loaded",
            request_id=request_id,
            source="canonical_board",
            rss_mb=rss_mb(),
            top_keys=_safe_keys(raw_board),
            meta_keys=_safe_keys(meta_raw),
            game_context_keys=_safe_keys(game_context_raw),
        )

        payload = _build_response_payload(raw_board=raw_board)
        _log_event(
            "board.latest.pre_serialize",
            request_id=request_id,
            source="canonical_board",
            rss_mb=rss_mb(),
        )
        _log_event(
            "board.latest.response_ready",
            request_id=request_id,
            source="canonical_board",
            rss_mb=rss_mb(),
        )
        _log_event(
            "board.latest.completed",
            request_id=request_id,
            rss_mb_before=rss_before,
            rss_mb_after=rss_mb(),
            source="canonical_board",
        )
        return JSONResponse(status_code=200, content=payload)
    except MemoryError as e:
        _log_event(
            "board.latest.oom_guard",
            level="error",
            request_id=request_id,
            rss_mb_before=rss_before,
            rss_mb_after=rss_mb(),
            error_class=type(e).__name__,
            error=str(e),
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "board_too_large",
                "request_id": request_id,
                "message": "Board payload is too large to serve safely on this instance.",
            },
        )
    except Exception as e:
        _log_event(
            "board.latest.failed",
            level="error",
            request_id=request_id,
            rss_mb_before=rss_before,
            rss_mb_after=rss_mb(),
            error_class=type(e).__name__,
            error=str(e),
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "board_latest_failed",
                "request_id": request_id,
                "message": "Failed to build board response.",
                "error_class": type(e).__name__,
            },
        )


@router.get("/board/latest/surface", response_model=FullScanResponse | None)
def get_board_latest_surface(
    surface: str = Query(..., description="Surface to load: straight_bets or player_props"),
    user: dict = Depends(get_current_user),
):
    """Load a per-surface latest payload from global_scan_cache (surface:latest)."""
    from main import _log_event
    from services.scan_cache import load_latest_scan_payload

    request_id = f"board_surface_{uuid4().hex[:10]}"
    rss_before = rss_mb()
    _log_event(
        "board.latest_surface.started",
        request_id=request_id,
        rss_mb=rss_before,
        user_id=str(user.get("id") or ""),
        surface=surface,
    )

    if surface not in ("straight_bets", "player_props"):
        raise HTTPException(status_code=400, detail="surface must be straight_bets or player_props")

    db = get_db()
    try:
        payload = load_latest_scan_payload(db=db, retry_supabase=_retry_supabase, surface=surface)
    except Exception as e:
        _log_event(
            "board.latest_surface.load_failed",
            level="warning",
            request_id=request_id,
            surface=surface,
            rss_mb_after=rss_mb(),
            error_class=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=502, detail="Failed to load board surface payload")

    if payload is None:
        _log_event(
            "board.latest_surface.missing",
            request_id=request_id,
            surface=surface,
            rss_mb_after=rss_mb(),
        )
        return None

    sides_raw = payload.get("sides")
    sides_count = len(sides_raw) if isinstance(sides_raw, list) else None
    _log_event(
        "board.latest_surface.completed",
        request_id=request_id,
        surface=surface,
        rss_mb_after=rss_mb(),
        sides_count=sides_count,
        scanned_at=payload.get("scanned_at"),
    )
    return payload


@router.get("/board/latest/promos")
def get_board_latest_promos(
    limit: int = Query(default=300, ge=20, le=1500),
    user: dict = Depends(get_current_user),
):
    """
    Optional lightweight promos payload to avoid client-side merging of huge arrays.

    Loads per-surface latest payloads and returns a capped combined sides list.
    """
    from main import _log_event
    from services.scan_cache import load_latest_scan_payload

    request_id = f"board_promos_{uuid4().hex[:10]}"
    rss_before = rss_mb()
    _log_event(
        "board.latest_promos.started",
        request_id=request_id,
        rss_mb=rss_before,
        user_id=str(user.get("id") or ""),
        limit=limit,
    )

    db = get_db()
    board = load_board_snapshot(db=db, retry_supabase=_retry_supabase)
    meta = board.get("meta") if isinstance(board, dict) and isinstance(board.get("meta"), dict) else _EMPTY_META.model_dump()
    game_context = board.get("game_context") if isinstance(board, dict) and isinstance(board.get("game_context"), dict) else None

    straight = load_latest_scan_payload(db=db, retry_supabase=_retry_supabase, surface="straight_bets") or {}
    props = load_latest_scan_payload(db=db, retry_supabase=_retry_supabase, surface="player_props") or {}

    straight_sides = straight.get("sides") if isinstance(straight, dict) else None
    props_sides = props.get("sides") if isinstance(props, dict) else None
    straight_list = straight_sides if isinstance(straight_sides, list) else []
    props_list = props_sides if isinstance(props_sides, list) else []

    # Take a bounded slice from each surface first to avoid doubling memory.
    take_each = max(10, int(limit / 2))
    combined = [*props_list[:take_each], *straight_list[:take_each]]

    def _ev(side: object) -> float:
        if not isinstance(side, dict):
            return -1e9
        try:
            return float(side.get("ev_percentage") or -1e9)
        except Exception:
            return -1e9

    try:
        combined.sort(key=_ev, reverse=True)
    except Exception:
        pass

    combined = combined[:limit]
    _log_event(
        "board.latest_promos.completed",
        request_id=request_id,
        rss_mb_before=rss_before,
        rss_mb_after=rss_mb(),
        straight_sides=len(straight_list),
        player_sides=len(props_list),
        returned=len(combined),
    )

    return JSONResponse(
        status_code=200,
        content={
            "meta": meta,
            "game_context": game_context,
            "limit": limit,
            "sides": combined,
        },
    )


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
