"""Board API routes.

GET  /api/board/latest  — returns the canonical board snapshot (no outbound calls)
POST /api/board/refresh — scoped manual refresh (rate-limited, does NOT overwrite board:latest)
"""

from __future__ import annotations

import os
import time

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from auth import get_current_user
from database import get_db
from models import (
    BoardResponse,
    BoardSnapshotMeta,
    FullScanResponse,
    PlayerPropBoardDetail,
    PlayerPropBoardPageResponse,
    PlayerPropBoardPickEmPageResponse,
    ScopedRefreshResponse,
)
from services.board_snapshot import load_board_snapshot, persist_scoped_refresh
from services.bet_crud import _retry_supabase
from services.player_prop_board import (
    BOARD_VIEW_BROWSE,
    BOARD_VIEW_OPPORTUNITIES,
    BOARD_VIEW_PICKEM,
    is_player_prop_board_opportunity,
    load_player_prop_board_artifact,
    load_player_prop_board_detail,
    load_player_prop_board_filtered_page,
    load_player_prop_board_legacy_surface,
    matches_player_prop_board_item,
    matches_player_prop_board_pickem_item,
)
from services.scanner_duplicate_detection import annotate_sides_with_duplicate_state
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


def _noop_log_event(*_args, **_kwargs) -> None:
    return None


def _noop_set_ops_status(*_args, **_kwargs) -> None:
    return None


def _noop_persist_ops_job_run(**_kwargs) -> None:
    return None


async def _refresh_player_props_result(*, source: str) -> dict:
    from services.player_props import (
        get_cached_or_scan_player_props,
        merge_player_prop_scan_results,
    )
    from services.player_prop_markets import get_supported_player_prop_sports
    from services.scan_markets import scanned_at_from_fetched_timestamp

    results_by_sport: list[tuple[str, dict]] = []
    oldest_fetched: float | None = None
    cache_hit = True
    for sport_key in get_supported_player_prop_sports():
        result = await get_cached_or_scan_player_props(sport_key, source=source)
        results_by_sport.append((sport_key, result))
        cache_hit = cache_hit and bool(result.get("cache_hit"))
        fetched_at = result.get("fetched_at")
        if isinstance(fetched_at, (int, float)):
            oldest_fetched = fetched_at if oldest_fetched is None else min(oldest_fetched, fetched_at)

    if not results_by_sport:
        return {
            "surface": "player_props",
            "sport": "all",
            "sides": [],
            "events_fetched": 0,
            "events_with_both_books": 0,
            "api_requests_remaining": None,
            "scanned_at": None,
            "diagnostics": None,
            "prizepicks_cards": None,
            "cache_hit": False,
        }

    merged = merge_player_prop_scan_results(
        *results_by_sport,
        scan_mode="manual_refresh_multi_sport",
        scan_scope="all_supported_sports",
    )
    merged["scanned_at"] = scanned_at_from_fetched_timestamp(oldest_fetched)
    merged["cache_hit"] = cache_hit
    return merged


def _resolve_main_runtime_hooks():
    """Best-effort access to main runtime helpers without hard crashing routes."""
    try:
        import main as main_module

        log_event = getattr(main_module, "_log_event", _noop_log_event)
        boot_id = getattr(main_module, "_BOOT_ID", None)
        sync_pickem = getattr(main_module, "_sync_pickem_research_from_props_payload", lambda *_args, **_kwargs: None)
        set_ops_status = getattr(main_module, "_set_ops_status", _noop_set_ops_status)
        persist_ops_job_run = getattr(main_module, "_persist_ops_job_run", _noop_persist_ops_job_run)
        return log_event, boot_id, sync_pickem, set_ops_status, persist_ops_job_run
    except Exception:
        return _noop_log_event, None, (lambda *_args, **_kwargs: None), _noop_set_ops_status, _noop_persist_ops_job_run


def _scoped_refresh_label(surface: str) -> str:
    return "Manual Player Props Refresh" if surface == "player_props" else "Manual Game Lines Refresh"


def _surface_sports_from_sides(sides: list[dict]) -> list[str]:
    sports = {
        str(side.get("sport") or "").strip().lower()
        for side in sides
        if isinstance(side, dict) and str(side.get("sport") or "").strip()
    }
    return sorted(sports)


def _build_scoped_refresh_result_summary(*, surface: str, scan_payload: FullScanResponse) -> dict[str, object]:
    total_sides = len(scan_payload.sides)
    summary: dict[str, object] = {
        "scan_label": _scoped_refresh_label(surface),
        "total_sides": total_sides,
    }
    if surface == "player_props":
        summary["props_sides"] = total_sides
        summary["props_events_fetched"] = scan_payload.events_fetched
        summary["props_events_with_both_books"] = scan_payload.events_with_both_books
        summary["props_api_requests_remaining"] = scan_payload.api_requests_remaining
        diagnostics = scan_payload.diagnostics
        if diagnostics is not None:
            summary["props_candidate_sides"] = diagnostics.candidate_sides_count
            summary["props_quality_gate_filtered"] = diagnostics.quality_gate_filtered_count
            summary["props_events_skipped_pregame"] = diagnostics.events_skipped_pregame
            summary["props_events_with_provider_markets"] = diagnostics.events_with_provider_markets
            summary["props_events_with_supported_book_markets"] = diagnostics.events_with_supported_book_markets
            summary["props_events_provider_only"] = diagnostics.events_provider_only
            summary["props_events_with_results"] = diagnostics.events_with_results
            summary["props_quality_gate_min_reference_bookmakers"] = diagnostics.quality_gate_min_reference_bookmakers
            summary["props_pickem_quality_gate_min_reference_bookmakers"] = diagnostics.pickem_quality_gate_min_reference_bookmakers
    else:
        summary["straight_sides"] = total_sides
        summary["game_lines_events_fetched"] = scan_payload.events_fetched
        summary["game_lines_events_with_both_books"] = scan_payload.events_with_both_books
        summary["game_lines_api_requests_remaining"] = scan_payload.api_requests_remaining
        summary["game_line_sports_scanned"] = _surface_sports_from_sides([side.model_dump() for side in scan_payload.sides])
    return summary


def _build_scoped_refresh_status_payload(
    *,
    run_id: str,
    surface: str,
    status: str,
    started_at: str,
    finished_at: str,
    duration_ms: float,
    refreshed_at: str,
    scan_payload: FullScanResponse | None,
    errors: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    result_summary = (
        _build_scoped_refresh_result_summary(surface=surface, scan_payload=scan_payload)
        if scan_payload is not None
        else {"scan_label": _scoped_refresh_label(surface)}
    )
    total_sides = len(scan_payload.sides) if scan_payload is not None else None
    payload: dict[str, object] = {
        "kind": "scoped_refresh",
        "source": "manual_refresh",
        "surface": surface,
        "status": status,
        "canonical_board_updated": False,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "captured_at": finished_at,
        "refreshed_at": refreshed_at,
        "duration_ms": duration_ms,
        "total_sides": total_sides,
        "result": result_summary,
    }
    if errors is not None:
        payload["error_count"] = len(errors)
        payload["errors"] = errors
    return payload


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
    """Load a per-surface latest cache payload without outbound API calls.

    This helper is kept for future fallback work; `/api/board/latest` currently
    serves only the canonical snapshot metadata and optional game context.
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


def _parse_books_param(books: str | None) -> list[str]:
    if not books:
        return []
    return [book.strip() for book in books.split(",") if book.strip()]


@router.get("/board/latest", response_model=BoardResponse)
def get_board_latest(user: dict = Depends(get_current_user)):
    """Return the latest canonical board snapshot.

    Pure DB read — never triggers outbound API calls.
    Serves the canonical snapshot metadata plus optional game context, with
    nullable surface payloads. Returns an empty sentinel if the canonical
    snapshot is missing or malformed.
    """
    _log_event, _BOOT_ID, _, _, _ = _resolve_main_runtime_hooks()

    request_id = f"board_latest_{uuid4().hex[:10]}"
    rss_before = rss_mb()
    mode = (os.getenv("BOARD_LATEST_MODE") or "full").strip().lower()
    if mode not in {"hardcoded_minimal", "meta_only", "minimal_game_context", "full"}:
        mode = "full"

    _log_event(
        "board.latest.entered",
        request_id=request_id,
        boot_id=_BOOT_ID,
        pid=os.getpid(),
        mode=mode,
        rss_mb=rss_before,
    )

    # Ultra-safe isolation mode: prove request-path stability without touching cache data.
    if mode == "hardcoded_minimal":
        payload = {
            "meta": {
                "snapshot_id": "hardcoded_minimal",
                "snapshot_type": "manual",
                "scanned_at": utc_now_iso_z(),
                "surfaces_included": [],
                "sports_included": [],
                "next_scheduled_drop": None,
                "events_scanned": 0,
                "total_sides": 0,
                "degraded": True,
            },
            "game_context": None,
            "straight_bets": None,
            "player_props": None,
        }
        encoded = jsonable_encoder(payload)
        _log_event(
            "board.latest.mode",
            request_id=request_id,
            boot_id=_BOOT_ID,
            pid=os.getpid(),
            mode=mode,
            status="completed",
            rss_mb_before=rss_before,
            rss_mb_after=rss_mb(),
        )
        _log_event(
            "board.latest.completed",
            request_id=request_id,
            boot_id=_BOOT_ID,
            pid=os.getpid(),
            mode=mode,
            rss_mb=rss_mb(),
        )
        return JSONResponse(status_code=200, content=encoded)

    try:
        db = get_db()
    except Exception as e:
        _log_event(
            "board.latest.mode",
            level="error",
            request_id=request_id,
            mode=mode,
            status="db_init_failed",
            error_class=type(e).__name__,
            error=str(e),
            rss_mb_before=rss_before,
            rss_mb_after=rss_mb(),
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "board_db_init_failed",
                "request_id": request_id,
                "message": "Failed to initialize board database client.",
                "error_class": type(e).__name__,
            },
        )

    try:
        raw = load_board_snapshot(db=db, retry_supabase=_retry_supabase)
    except Exception as e:
        _log_event("board.latest.mode", level="warning", request_id=request_id, mode=mode, status="load_failed")
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

    def _safe_type(value: object) -> str:
        try:
            return type(value).__name__
        except Exception:
            return "unknown"

    def _minimal_game_context(value: object) -> tuple[dict[str, object] | None, bool]:
        """
        Return a stable, minimal game_context subset to avoid crashing on weird/stale cache rows.
        Returns (game_context_or_none, degraded_flag).
        """
        if not isinstance(value, dict):
            return (None, False)

        keep_keys = {
            "sport",
            "scan_label",
            "scan_anchor_timezone",
            "scan_anchor_time_mst",
            "selection_mode",
            "selection_params",
            "selected_event_ids",
            "props_scan_scope",
            "props_scan_event_ids",
            "props_scan_event_ids_by_sport",
            "events_fetched",
            "api_requests_remaining",
            "featured_lines_meta",
            "nba_props_events_meta",
            "player_props_events_meta",
            "captured_at",
        }
        out: dict[str, object] = {}
        degraded = False
        for k in keep_keys:
            if k in value:
                out[k] = value.get(k)
        # If we dropped anything, note degradation.
        if set(value.keys()) - keep_keys:
            degraded = True
        return (out or None, degraded)

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

        game_context_obj = raw_board.get("game_context")
        game_context: dict[str, object] | None
        gc_degraded = False
        if mode == "meta_only":
            game_context = None
        elif mode == "minimal_game_context":
            game_context, gc_degraded = _minimal_game_context(game_context_obj)
        else:
            # full
            game_context = game_context_obj if isinstance(game_context_obj, dict) else None

        if gc_degraded and isinstance(meta, dict):
            meta = dict(meta)
            meta["degraded"] = True

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
        payload = _build_response_payload(raw_board=raw_board)
        # Use jsonable_encoder to tolerate datetimes/UUIDs that may exist in older/stale cache rows.
        encoded = jsonable_encoder(payload)
        _log_event(
            "board.latest.mode",
            request_id=request_id,
            mode=mode,
            status="completed",
            rss_mb_before=rss_before,
            rss_mb_after=rss_mb(),
            raw_type=_safe_type(raw),
            raw_is_dict=isinstance(raw, dict),
            top_keys=_safe_keys(raw_board),
            meta_type=_safe_type((raw_board or {}).get("meta") if isinstance(raw_board, dict) else None),
            game_context_type=_safe_type((raw_board or {}).get("game_context") if isinstance(raw_board, dict) else None),
        )
        _log_event(
            "board.latest.completed",
            request_id=request_id,
            boot_id=_BOOT_ID,
            pid=os.getpid(),
            mode=mode,
            rss_mb=rss_mb(),
        )
        return JSONResponse(status_code=200, content=encoded)
    except MemoryError as e:
        _log_event("board.latest.mode", level="error", request_id=request_id, mode=mode, status="oom_guard")
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
            "board.latest.mode",
            level="error",
            request_id=request_id,
            mode=mode,
            status="failed",
            error_class=type(e).__name__,
            error=str(e),
            rss_mb_before=rss_before,
            rss_mb_after=rss_mb(),
        )
        # Keep behavior stable but controlled.
        meta = _EMPTY_META.model_dump()
        meta["scanned_at"] = utc_now_iso_z()
        meta["degraded"] = True
        return JSONResponse(status_code=200, content=jsonable_encoder({"meta": meta, "game_context": None, "straight_bets": None, "player_props": None}))


@router.get("/board/latest/surface", response_model=FullScanResponse | None)
def get_board_latest_surface(
    surface: str = Query(..., description="Surface to load: straight_bets or player_props"),
    user: dict = Depends(get_current_user),
):
    """Load a per-surface latest payload from global_scan_cache (surface:latest)."""
    _log_event, _boot_id, _, _, _ = _resolve_main_runtime_hooks()
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

    try:
        db = get_db()
        if surface == "player_props":
            payload = load_player_prop_board_legacy_surface(db=db, retry_supabase=_retry_supabase)
        else:
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

    if surface == "player_props":
        sides_raw = payload.get("sides")
        sides = sides_raw if isinstance(sides_raw, list) else []
        payload = {
            **payload,
            "sides": annotate_sides_with_duplicate_state(db, str(user.get("id") or ""), sides),
        }

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


def _build_player_prop_board_page_response(
    *,
    view: str,
    user_id: str,
    books: list[str],
    time_filter: str,
    sport: str | None,
    market: str | None,
    search: str | None,
    page: int,
    page_size: int,
    tz_offset_minutes: int | None,
):
    try:
        db = get_db()
        meta, paged_items, filtered_total, source_total, has_more = load_player_prop_board_filtered_page(
            db=db,
            retry_supabase=_retry_supabase,
            view=view,  # type: ignore[arg-type]
            page=page,
            page_size=page_size,
            filter_item=lambda item: (
                is_player_prop_board_opportunity(item) if view == BOARD_VIEW_OPPORTUNITIES else True
            ) and matches_player_prop_board_item(
                item,
                books=books,
                time_filter=time_filter,
                sport=sport,
                market=market,
                search=search,
                tz_offset_minutes=tz_offset_minutes,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load player-props board page: {e}")

    if meta is None:
        return None

    annotated_items = annotate_sides_with_duplicate_state(db, user_id, paged_items)
    return {
        "items": annotated_items,
        "page": page,
        "page_size": page_size,
        "total": filtered_total,
        "source_total": source_total,
        "has_more": has_more,
        "scanned_at": meta.get("scanned_at"),
        "available_books": meta.get("available_books") or [],
        "available_markets": meta.get("available_markets") or [],
        "available_sports": meta.get("available_sports") or [],
    }


@router.get("/board/latest/player-props/opportunities", response_model=PlayerPropBoardPageResponse | None)
def get_board_latest_player_props_opportunities(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    books: str | None = Query(default=None),
    time_filter: str = Query(default="today"),
    sport: str | None = Query(default=None),
    market: str | None = Query(default=None),
    search: str | None = Query(default=None),
    tz_offset_minutes: int | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    return _build_player_prop_board_page_response(
        view=BOARD_VIEW_OPPORTUNITIES,
        user_id=str(user.get("id") or ""),
        books=_parse_books_param(books),
        time_filter=time_filter,
        sport=sport,
        market=market,
        search=search,
        page=page,
        page_size=page_size,
        tz_offset_minutes=tz_offset_minutes,
    )


@router.get("/board/latest/player-props/browse", response_model=PlayerPropBoardPageResponse | None)
def get_board_latest_player_props_browse(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    books: str | None = Query(default=None),
    time_filter: str = Query(default="today"),
    sport: str | None = Query(default=None),
    market: str | None = Query(default=None),
    search: str | None = Query(default=None),
    tz_offset_minutes: int | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    return _build_player_prop_board_page_response(
        view=BOARD_VIEW_BROWSE,
        user_id=str(user.get("id") or ""),
        books=_parse_books_param(books),
        time_filter=time_filter,
        sport=sport,
        market=market,
        search=search,
        page=page,
        page_size=page_size,
        tz_offset_minutes=tz_offset_minutes,
    )


@router.get("/board/latest/player-props/pickem", response_model=PlayerPropBoardPickEmPageResponse | None)
def get_board_latest_player_props_pickem(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    books: str | None = Query(default=None),
    time_filter: str = Query(default="today"),
    sport: str | None = Query(default=None),
    market: str | None = Query(default=None),
    search: str | None = Query(default=None),
    tz_offset_minutes: int | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    meta, paged_items, filtered_total, source_total, has_more = load_player_prop_board_filtered_page(
        db=db,
        retry_supabase=_retry_supabase,
        view=BOARD_VIEW_PICKEM,
        page=page,
        page_size=page_size,
        filter_item=lambda item: matches_player_prop_board_pickem_item(
            item,
            books=_parse_books_param(books),
            time_filter=time_filter,
            sport=sport,
            market=market,
            search=search,
            tz_offset_minutes=tz_offset_minutes,
        ),
    )
    if meta is None:
        return None

    return {
        "items": paged_items,
        "page": page,
        "page_size": page_size,
        "total": filtered_total,
        "source_total": source_total,
        "has_more": has_more,
        "scanned_at": meta.get("scanned_at"),
        "available_books": meta.get("available_books") or [],
        "available_markets": meta.get("available_markets") or [],
        "available_sports": meta.get("available_sports") or [],
    }


@router.get("/board/latest/player-props/detail", response_model=PlayerPropBoardDetail)
def get_board_latest_player_prop_detail(
    selection_key: str = Query(...),
    sportsbook: str = Query(...),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    detail = load_player_prop_board_detail(
        db=db,
        retry_supabase=_retry_supabase,
        selection_key=selection_key,
        sportsbook=sportsbook,
    )
    if not isinstance(detail, dict):
        raise HTTPException(status_code=404, detail="Player prop board detail not found")
    return detail


@router.get("/board/latest/promos")
def get_board_latest_promos(
    limit: int = Query(default=300, ge=20, le=1500),
    user: dict = Depends(get_current_user),
):
    """
    Optional lightweight promos payload to avoid client-side merging of huge arrays.

    Loads per-surface latest payloads and returns a capped combined sides list.
    """
    _log_event, _boot_id, _, _, _ = _resolve_main_runtime_hooks()
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

    try:
        db = get_db()
        board = load_board_snapshot(db=db, retry_supabase=_retry_supabase)
        meta = board.get("meta") if isinstance(board, dict) and isinstance(board.get("meta"), dict) else _EMPTY_META.model_dump()
        game_context = board.get("game_context") if isinstance(board, dict) and isinstance(board.get("game_context"), dict) else None

        straight = load_latest_scan_payload(db=db, retry_supabase=_retry_supabase, surface="straight_bets") or {}
        _props_meta, props_items = load_player_prop_board_artifact(
            db=db,
            retry_supabase=_retry_supabase,
            view=BOARD_VIEW_OPPORTUNITIES,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load promos board payload: {e}")

    straight_sides = straight.get("sides") if isinstance(straight, dict) else None
    straight_list = straight_sides if isinstance(straight_sides, list) else []
    props_list = props_items if isinstance(props_items, list) else []

    def _ev(side: object) -> float:
        if not isinstance(side, dict):
            return -1e9
        try:
            return float(side.get("ev_percentage") or -1e9)
        except Exception:
            return -1e9

    # Rank within each surface before slicing so late-arriving sports/markets are not
    # dropped just because they appear later in the cached payload order.
    candidate_window = min(max(limit * 3, 120), 600)
    try:
        props_candidates = sorted(props_list, key=_ev, reverse=True)[:candidate_window]
    except Exception:
        props_candidates = props_list[:candidate_window]
    try:
        straight_candidates = sorted(straight_list, key=_ev, reverse=True)[:candidate_window]
    except Exception:
        straight_candidates = straight_list[:candidate_window]

    combined = [*props_candidates, *straight_candidates]
    combined = annotate_sides_with_duplicate_state(db, str(user.get("id") or ""), combined)

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
        straight_candidates=len(straight_candidates),
        player_candidates=len(props_candidates),
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

    try:
        db = get_db()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to initialize database client: {e}")

    _log_event, _boot_id, _sync_pickem_research_from_props_payload, _set_ops_status, _persist_ops_job_run = _resolve_main_runtime_hooks()
    started_at = utc_now_iso_z()
    started_clock = time.monotonic()
    run_id = f"scoped_refresh_{uuid4().hex[:10]}"

    def _record_scoped_refresh_failure(error: Exception, *, status_code: int, detail: str) -> None:
        finished_at = utc_now_iso_z()
        duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
        errors = [{"error": str(error), "error_class": type(error).__name__}]
        status_payload = _build_scoped_refresh_status_payload(
            run_id=run_id,
            surface=scope,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            refreshed_at=finished_at,
            scan_payload=None,
            errors=errors,
        )
        _set_ops_status("last_board_refresh", status_payload)
        _persist_ops_job_run(
            job_kind="board_scoped_refresh",
            source="manual_refresh",
            status="failed",
            run_id=run_id,
            scan_session_id=run_id,
            surface=scope,
            scan_scope="all",
            requested_sport="all",
            captured_at=finished_at,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            error_count=len(errors),
            errors=errors,
            meta={
                "canonical_board_updated": False,
                "refreshed_at": finished_at,
                "result_summary": status_payload.get("result"),
                "response_status_code": status_code,
                "response_detail": detail,
            },
        )

    try:
        if scope == "player_props":
            result = await _refresh_player_props_result(source="manual_refresh")
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
        _record_scoped_refresh_failure(e, status_code=502, detail=f"Refresh failed: {e}")
        raise HTTPException(status_code=502, detail=f"Refresh failed: {e}")

    try:
        scan_payload = FullScanResponse(
            surface=scope,  # type: ignore[arg-type]
            sport=result.get("sport") or "all",
            sides=result.get("sides") or [],
            events_fetched=int(result.get("events_fetched") or 0),
            events_with_both_books=int(result.get("events_with_both_books") or 0),
            api_requests_remaining=result.get("api_requests_remaining"),
            scanned_at=result.get("scanned_at"),
            diagnostics=result.get("diagnostics"),
            prizepicks_cards=result.get("prizepicks_cards"),
        )
    except Exception as e:
        _record_scoped_refresh_failure(e, status_code=500, detail=f"Failed to build response: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to build response: {e}")

    refreshed_at = persist_scoped_refresh(
        db=db,
        surface=scope,
        scan_payload=scan_payload.model_dump(),
        retry_supabase=_retry_supabase,
        log_event=_log_event,
    )
    if scope == "player_props" and not bool(result.get("cache_hit")):
        _sync_pickem_research_from_props_payload(scan_payload.model_dump(), source="manual_refresh")

    finished_at = refreshed_at
    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    status_payload = _build_scoped_refresh_status_payload(
        run_id=run_id,
        surface=scope,
        status="completed",
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        refreshed_at=refreshed_at,
        scan_payload=scan_payload,
        errors=[],
    )
    _set_ops_status("last_board_refresh", status_payload)
    _persist_ops_job_run(
        job_kind="board_scoped_refresh",
        source="manual_refresh",
        status="completed",
        run_id=run_id,
        scan_session_id=run_id,
        surface=scope,
        scan_scope="all",
        requested_sport="all",
        captured_at=finished_at,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        events_fetched=scan_payload.events_fetched,
        events_with_both_books=scan_payload.events_with_both_books,
        total_sides=len(scan_payload.sides),
        api_requests_remaining=scan_payload.api_requests_remaining,
        error_count=0,
        errors=[],
        meta={
            "canonical_board_updated": False,
            "refreshed_at": refreshed_at,
            "result_summary": status_payload.get("result"),
        },
    )

    return ScopedRefreshResponse(
        surface=scope,  # type: ignore[arg-type]
        refreshed_at=refreshed_at,
        data=scan_payload,
    )
