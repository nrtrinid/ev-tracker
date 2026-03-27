"""Board snapshot persistence and retrieval.

The board:latest cache key stores a unified BoardResponse containing both
straight_bets and player_props surfaces, stamped with a snapshot_id and
snapshot_type so the frontend can show a coherent global board timestamp.

Scoped manual refreshes write to <surface>:scoped:latest instead of
overwriting the canonical board:latest key.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4


BOARD_LATEST_KEY = "board:latest"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _new_snapshot_id() -> str:
    return f"snap_{uuid4().hex[:12]}"


def persist_board_snapshot(
    *,
    db,
    snapshot_type: str,
    straight_bets_payload: dict[str, Any] | None,
    player_props_payload: dict[str, Any] | None,
    game_context: dict[str, Any] | None = None,
    scanned_at: str | None = None,
    retry_supabase: Callable,
    log_event: Callable[..., None],
) -> str:
    """Persist a unified board snapshot to the global_scan_cache table.

    Returns the snapshot_id for the persisted snapshot.
    Does NOT overwrite per-surface keys (straight_bets:latest / player_props:latest)
    — those are written separately by the existing per-surface persist calls.
    """
    snapshot_id = _new_snapshot_id()
    now = scanned_at or _utc_now_iso()

    surfaces_included: list[str] = []
    sports_included: list[str] = []
    total_sides = 0
    total_events = 0

    if straight_bets_payload:
        surfaces_included.append("straight_bets")
        sports_included.append(straight_bets_payload.get("sport") or "all")
        total_sides += len(straight_bets_payload.get("sides") or [])
        total_events += int(straight_bets_payload.get("events_fetched") or 0)

    if player_props_payload:
        surfaces_included.append("player_props")
        sport = player_props_payload.get("sport") or "basketball_nba"
        if sport not in sports_included:
            sports_included.append(sport)
        total_sides += len(player_props_payload.get("sides") or [])
        total_events += int(player_props_payload.get("events_fetched") or 0)

    meta = {
        "snapshot_id": snapshot_id,
        "snapshot_type": snapshot_type,
        "scanned_at": now,
        "surfaces_included": surfaces_included,
        "sports_included": sports_included,
        "next_scheduled_drop": None,
        "events_scanned": total_events,
        "total_sides": total_sides,
    }

    payload = {
        "meta": meta,
        "game_context": game_context,
        "straight_bets": straight_bets_payload,
        "player_props": player_props_payload,
    }

    try:
        retry_supabase(
            lambda: (
                db.table("global_scan_cache")
                .upsert(
                    {"key": BOARD_LATEST_KEY, "surface": "board", "payload": payload},
                    on_conflict="key",
                )
                .execute()
            )
        )
    except Exception as e:
        log_event(
            "board_snapshot.persist_failed",
            level="warning",
            snapshot_id=snapshot_id,
            error_class=type(e).__name__,
            error=str(e),
        )

    return snapshot_id


def persist_board_meta_snapshot(
    *,
    db,
    snapshot_type: str,
    game_context: dict[str, Any] | None,
    scanned_at: str | None = None,
    retry_supabase: Callable,
    log_event: Callable[..., None],
    surfaces_included: list[str] | None = None,
    sports_included: list[str] | None = None,
    events_scanned: int | None = None,
    total_sides: int | None = None,
) -> str:
    """
    Persist a lightweight canonical board snapshot (meta + game_context only).

    This intentionally does NOT store large surface payloads under board:latest.
    Surfaces should be loaded from their existing per-surface latest keys.
    """
    snapshot_id = _new_snapshot_id()
    now = scanned_at or _utc_now_iso()

    meta = {
        "snapshot_id": snapshot_id,
        "snapshot_type": snapshot_type,
        "scanned_at": now,
        "surfaces_included": surfaces_included or [],
        "sports_included": sports_included or [],
        "next_scheduled_drop": None,
        "events_scanned": int(events_scanned or 0),
        "total_sides": int(total_sides or 0),
    }

    payload = {
        "meta": meta,
        "game_context": game_context,
        # Explicitly omit large surfaces.
        "straight_bets": None,
        "player_props": None,
    }

    try:
        retry_supabase(
            lambda: (
                db.table("global_scan_cache")
                .upsert(
                    {"key": BOARD_LATEST_KEY, "surface": "board", "payload": payload},
                    on_conflict="key",
                )
                .execute()
            )
        )
    except Exception as e:
        log_event(
            "board_snapshot.persist_meta_failed",
            level="warning",
            snapshot_id=snapshot_id,
            error_class=type(e).__name__,
            error=str(e),
        )

    return snapshot_id


def load_board_snapshot(
    *,
    db,
    retry_supabase: Callable,
) -> dict[str, Any] | None:
    """Load the latest board snapshot from the canonical board:latest key.

    Returns None if no snapshot has been persisted yet.
    Never triggers outbound API calls.
    """
    try:
        res = retry_supabase(
            lambda: (
                db.table("global_scan_cache")
                .select("payload")
                .eq("key", BOARD_LATEST_KEY)
                .limit(1)
                .execute()
            )
        )
    except Exception as e:
        msg = str(e)
        if "PGRST205" in msg or ("global_scan_cache" in msg and "schema cache" in msg):
            return None
        raise

    rows = getattr(res, "data", None) or []
    if not rows:
        return None
    payload = rows[0].get("payload") if isinstance(rows[0], dict) else None
    if not isinstance(payload, dict):
        return None
    return payload


def persist_scoped_refresh(
    *,
    db,
    surface: str,
    scan_payload: dict[str, Any],
    retry_supabase: Callable,
    log_event: Callable[..., None],
) -> str:
    """Persist a scoped manual refresh result to a surface-specific key.

    Writes to <surface>:scoped:latest — does NOT overwrite board:latest
    or the surface:latest key used by the canonical board.
    """
    scoped_key = f"{surface}:scoped:latest"
    refreshed_at = _utc_now_iso()
    wrapped = {
        "surface": surface,
        "refreshed_at": refreshed_at,
        "data": scan_payload,
    }
    try:
        retry_supabase(
            lambda: (
                db.table("global_scan_cache")
                .upsert(
                    {"key": scoped_key, "surface": surface, "payload": wrapped},
                    on_conflict="key",
                )
                .execute()
            )
        )
    except Exception as e:
        log_event(
            "board_snapshot.scoped_persist_failed",
            level="warning",
            surface=surface,
            error_class=type(e).__name__,
            error=str(e),
        )
    return refreshed_at
