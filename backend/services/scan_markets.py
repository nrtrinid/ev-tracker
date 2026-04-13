import asyncio
import inspect
from typing import Any, Awaitable, Callable
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException


def manual_scan_sports_for_env(
    *,
    environment: str,
    supported_sports: list[str],
    surface: str = "straight_bets",
) -> list[str]:
    if environment.lower() != "development":
        return supported_sports
    if surface == "player_props":
        return supported_sports
    return ["basketball_nba"]


def scanned_at_from_fetched_timestamp(fetched_at: float | None) -> str | None:
    if fetched_at is None:
        return None
    return datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _with_surface(surface: str, sides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        side if isinstance(side, dict) and side.get("surface") else {"surface": surface, **side}
        for side in sides
    ]


def build_single_sport_manual_scan_outputs(
    *,
    surface: str = "straight_bets",
    result: dict[str, Any],
    sport: str,
    scanned_at: str | None,
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    base_sides = _with_surface(surface, result["sides"])
    fresh_sides = base_sides if not result.get("cache_hit") else []
    response_sides = _with_surface(surface, annotate_sides(base_sides))
    response_payload = {
        "surface": surface,
        "sport": sport,
        "sides": response_sides,
        "events_fetched": result["events_fetched"],
        "events_with_both_books": result["events_with_both_books"],
        "api_requests_remaining": result.get("api_requests_remaining"),
        "scanned_at": scanned_at,
        "diagnostics": result.get("diagnostics"),
        "prizepicks_cards": result.get("prizepicks_cards"),
    }
    persist_payload = {
        "surface": surface,
        "sport": sport,
        "sides": base_sides,
        "events_fetched": result["events_fetched"],
        "events_with_both_books": result["events_with_both_books"],
        "api_requests_remaining": result.get("api_requests_remaining"),
        "scanned_at": scanned_at,
        "diagnostics": result.get("diagnostics"),
        "prizepicks_cards": result.get("prizepicks_cards"),
    }
    ops_status_payload = {
        "surface": surface,
        "sport": sport,
        "events_fetched": result.get("events_fetched"),
        "events_with_both_books": result.get("events_with_both_books"),
        "total_sides": len(base_sides or []),
        "api_requests_remaining": result.get("api_requests_remaining"),
    }
    return {
        "base_sides": base_sides,
        "fresh_sides": fresh_sides,
        "response_payload": response_payload,
        "persist_payload": persist_payload,
        "ops_status_payload": ops_status_payload,
    }


def build_all_sports_manual_scan_outputs(
    *,
    surface: str = "straight_bets",
    all_sides: list[dict[str, Any]],
    fresh_sides: list[dict[str, Any]],
    total_events: int,
    total_with_both: int,
    min_remaining: str | None,
    scanned_at: str | None,
    diagnostics: dict[str, Any] | None,
    prizepicks_cards: list[dict[str, Any]] | None,
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    normalized_sides = _with_surface(surface, all_sides)
    response_sides = _with_surface(surface, annotate_sides(normalized_sides))
    response_payload = {
        "surface": surface,
        "sport": "all",
        "sides": response_sides,
        "events_fetched": total_events,
        "events_with_both_books": total_with_both,
        "api_requests_remaining": min_remaining,
        "scanned_at": scanned_at,
        "diagnostics": diagnostics,
        "prizepicks_cards": prizepicks_cards,
    }
    persist_payload = {
        "surface": surface,
        "sport": "all",
        "sides": normalized_sides,
        "events_fetched": total_events,
        "events_with_both_books": total_with_both,
        "api_requests_remaining": min_remaining,
        "scanned_at": scanned_at,
        "diagnostics": diagnostics,
        "prizepicks_cards": prizepicks_cards,
    }
    ops_status_payload = {
        "surface": surface,
        "sport": "all",
        "events_fetched": total_events,
        "events_with_both_books": total_with_both,
        "total_sides": len(all_sides),
        "api_requests_remaining": min_remaining,
    }
    return {
        "fresh_sides": _with_surface(surface, fresh_sides),
        "response_payload": response_payload,
        "persist_payload": persist_payload,
        "ops_status_payload": ops_status_payload,
    }


def apply_manual_scan_bundle(
    *,
    bundle: dict[str, Any],
    captured_at: str,
    set_last_manual_scan_status: Callable[[dict[str, Any]], None],
    schedule_piggyback: Callable[[list[dict[str, Any]]], Any],
    schedule_research_capture: Callable[[list[dict[str, Any]]], Any],
    persist_latest_scan: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    set_last_manual_scan_status(
        {
            "captured_at": captured_at,
            **bundle["ops_status_payload"],
        }
    )
    persist_payload = bundle["persist_payload"]
    fresh_sides = bundle.get("fresh_sides") or []
    research_result = schedule_research_capture(fresh_sides)
    if inspect.isawaitable(research_result):
        asyncio.create_task(research_result)
    piggyback_result = schedule_piggyback(fresh_sides)
    if inspect.isawaitable(piggyback_result):
        asyncio.create_task(piggyback_result)
    persist_latest_scan(persist_payload)
    return bundle["response_payload"]


def scan_exception_to_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, ValueError):
        return HTTPException(status_code=500, detail=str(error))
    return HTTPException(status_code=502, detail=f"Odds API error: {error}")


async def aggregate_manual_scan_all_sports(
    *,
    sports_to_scan: list[str],
    get_cached_or_scan: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    all_sides: list[dict[str, Any]] = []
    fresh_sides: list[dict[str, Any]] = []
    total_events = 0
    total_with_both = 0
    min_remaining: str | None = None
    oldest_fetched: float | None = None
    diagnostics: dict[str, Any] | None = None
    prizepicks_cards: list[dict[str, Any]] = []
    results_by_sport: list[tuple[str, dict[str, Any]]] = []

    for sport in sports_to_scan:
        try:
            result = await get_cached_or_scan(sport)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                continue
            raise

        results_by_sport.append((sport, result))
        all_sides.extend(result["sides"])
        if not result.get("cache_hit"):
            fresh_sides.extend(result["sides"])
        total_events += int(result["events_fetched"])
        total_with_both += int(result["events_with_both_books"])

        rem = result.get("api_requests_remaining")
        if rem is not None:
            try:
                r = int(rem)
                min_remaining = str(r) if min_remaining is None else str(min(r, int(min_remaining)))
            except (TypeError, ValueError):
                min_remaining = str(rem)

        ft = result.get("fetched_at")
        if ft is not None:
            oldest_fetched = ft if oldest_fetched is None else min(oldest_fetched, ft)

        if diagnostics is None and isinstance(result.get("diagnostics"), dict):
            diagnostics = result["diagnostics"]
        cards = result.get("prizepicks_cards")
        if isinstance(cards, list):
            prizepicks_cards.extend(card for card in cards if isinstance(card, dict))

    if results_by_sport and all(str(result.get("surface") or "").strip().lower() == "player_props" for _sport, result in results_by_sport):
        from services.player_props import merge_player_prop_scan_results

        merged = merge_player_prop_scan_results(
            *results_by_sport,
            scan_mode="manual_scan_multi_sport",
            scan_scope="all_supported_sports",
        )
        merged_diagnostics = merged.get("diagnostics")
        diagnostics = merged_diagnostics if isinstance(merged_diagnostics, dict) else diagnostics
        merged_cards = merged.get("prizepicks_cards")
        if isinstance(merged_cards, list):
            prizepicks_cards = [card for card in merged_cards if isinstance(card, dict)]

    return {
        "all_sides": all_sides,
        "fresh_sides": fresh_sides,
        "total_events": total_events,
        "total_with_both": total_with_both,
        "min_remaining": min_remaining,
        "oldest_fetched": oldest_fetched,
        "diagnostics": diagnostics,
        "prizepicks_cards": prizepicks_cards or None,
    }


async def run_single_sport_manual_scan(
    *,
    surface: str = "straight_bets",
    sport: str,
    get_cached_or_scan: Callable[[str], Awaitable[dict[str, Any]]],
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    result = await get_cached_or_scan(sport)
    scanned_at = scanned_at_from_fetched_timestamp(result.get("fetched_at"))
    return build_single_sport_manual_scan_outputs(
        surface=surface,
        result=result,
        sport=sport,
        scanned_at=scanned_at,
        annotate_sides=annotate_sides,
    )


async def run_all_sports_manual_scan(
    *,
    surface: str = "straight_bets",
    environment: str,
    supported_sports: list[str],
    get_cached_or_scan: Callable[[str], Awaitable[dict[str, Any]]],
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    sports_to_scan = manual_scan_sports_for_env(
        environment=environment,
        supported_sports=supported_sports,
        surface=surface,
    )
    aggregate = await aggregate_manual_scan_all_sports(
        sports_to_scan=sports_to_scan,
        get_cached_or_scan=get_cached_or_scan,
    )
    scanned_at = scanned_at_from_fetched_timestamp(aggregate["oldest_fetched"])
    return build_all_sports_manual_scan_outputs(
        surface=surface,
        all_sides=aggregate["all_sides"],
        fresh_sides=aggregate["fresh_sides"],
        total_events=aggregate["total_events"],
        total_with_both=aggregate["total_with_both"],
        min_remaining=aggregate["min_remaining"],
        scanned_at=scanned_at,
        diagnostics=aggregate.get("diagnostics"),
        prizepicks_cards=aggregate.get("prizepicks_cards"),
        annotate_sides=annotate_sides,
    )
