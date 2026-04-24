"""Canonical scanner runtime helpers used by routes, cron, and scheduler jobs."""

from __future__ import annotations

import os
from typing import Any

from database import get_db
from models import FullScanResponse, ScanResponse
from services.ops_runtime import persist_ops_job_run, set_ops_status
from services.runtime_support import log_event, new_run_id, retry_supabase, utc_now_iso
from services.scan_cache import persist_latest_full_scan as persist_latest_full_scan_service


def annotate_sides_with_duplicate_state(db, user_id: str, sides: list[dict]) -> list[dict]:
    from services.scanner_duplicate_detection import annotate_sides_with_duplicate_state as _annotate

    return _annotate(db, user_id, sides)


def capture_research_opportunities(sides: list[dict], *, source: str) -> None:
    if not sides:
        return

    from services.research_opportunities import capture_scan_opportunities

    try:
        capture_scan_opportunities(
            get_db(),
            sides=sides,
            source=source,
            captured_at=utc_now_iso(),
        )
    except Exception as exc:
        log_event(
            "research.capture.failed",
            level="warning",
            source=source,
            error_class=type(exc).__name__,
            error=str(exc),
        )


def capture_model_candidate_observations(
    candidate_sets: dict[str, list[dict]],
    *,
    source: str,
    captured_at: str | None = None,
) -> None:
    if not candidate_sets:
        return

    from services.player_prop_candidate_observations import capture_player_prop_model_candidate_observations

    try:
        capture_player_prop_model_candidate_observations(
            get_db(),
            candidate_sets=candidate_sets,
            source=source,
            captured_at=captured_at or utc_now_iso(),
        )
    except Exception as exc:
        log_event(
            "player_props.model_candidate_observations.capture_failed",
            level="warning",
            source=source,
            error_class=type(exc).__name__,
            error=str(exc),
        )


def sync_pickem_research_from_props_payload(payload: dict | None, *, source: str = "unknown") -> None:
    if not isinstance(payload, dict):
        return
    try:
        from services.pickem_research import capture_pickem_research_observations

        capture_pickem_research_observations(
            get_db(),
            payload,
            source=source,
            captured_at=utc_now_iso(),
        )
    except Exception:
        return


async def piggyback_clv(sides: list[dict]) -> None:
    """
    Best-effort CLV snapshot refresh for pending bets and research opportunities.
    Errors are swallowed so scan responses and board publishing remain stable.
    """
    from services.clv_tracking import (
        update_bet_reference_snapshots,
        update_scan_opportunity_reference_snapshots,
    )

    try:
        db = get_db()
        update_bet_reference_snapshots(db, sides=sides, allow_close=True)
        update_scan_opportunity_reference_snapshots(db, sides=sides, allow_close=True)
    except Exception as exc:
        print(f"[CLV piggyback] Error: {exc}")


async def apply_fresh_straight_scan_followups(result: dict, *, source: str) -> None:
    sides = result.get("sides") or []
    if not sides or result.get("cache_hit"):
        return
    capture_research_opportunities(sides, source=source)
    await piggyback_clv(sides)


def get_environment() -> str:
    return os.getenv("ENVIRONMENT", "production").lower()


def scanner_supported_sports(surface: str) -> list[str]:
    if surface == "player_props":
        from services.player_prop_markets import get_supported_player_prop_sports

        return get_supported_player_prop_sports()
    from services.odds_api import SUPPORTED_SPORTS

    return SUPPORTED_SPORTS


def append_scan_activity(**kwargs: Any) -> None:
    from services.odds_api import append_scan_activity as append_scan_activity_service

    append_scan_activity_service(**kwargs)


async def get_cached_or_scan_for_surface(surface: str, sport: str, *, source: str = "unknown") -> dict:
    if surface == "player_props":
        from services.player_props import get_cached_or_scan_player_props

        return await get_cached_or_scan_player_props(sport, source=source)
    from services.odds_api import get_cached_or_scan

    return await get_cached_or_scan(sport, source=source)


async def scan_for_ev_surface(sport: str) -> dict:
    from services.odds_api import scan_for_ev

    return await scan_for_ev(sport)


def build_scan_response(*, sport: str, result: dict) -> ScanResponse:
    return ScanResponse(
        sport=sport,
        opportunities=result["opportunities"],
        events_fetched=result["events_fetched"],
        events_with_both_books=result["events_with_both_books"],
        api_requests_remaining=result.get("api_requests_remaining"),
    )


def build_full_scan_response(payload: dict) -> FullScanResponse:
    return FullScanResponse(**payload)


def persist_latest_full_scan(
    *,
    db,
    surface: str,
    sport: str,
    sides: list[dict],
    events_fetched: int,
    events_with_both_books: int,
    api_requests_remaining: str | None,
    scanned_at: str | None,
    diagnostics: dict | None = None,
    prizepicks_cards: list[dict] | None = None,
    retry_supabase_fn=retry_supabase,
    log_event_fn=log_event,
    **legacy_kwargs,
):
    retry_fn = legacy_kwargs.get("retry_supabase") or retry_supabase_fn
    log_fn = legacy_kwargs.get("log_event") or log_event_fn
    return persist_latest_full_scan_service(
        db=db,
        surface=surface,
        sport=sport,
        sides=sides,
        events_fetched=events_fetched,
        events_with_both_books=events_with_both_books,
        api_requests_remaining=api_requests_remaining,
        scanned_at=scanned_at,
        diagnostics=diagnostics,
        prizepicks_cards=prizepicks_cards,
        retry_supabase=retry_fn,
        log_event=log_fn,
    )
