from typing import Any, Awaitable, Callable
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException


def manual_scan_sports_for_env(*, environment: str, supported_sports: list[str]) -> list[str]:
    return ["basketball_nba"] if environment.lower() == "development" else supported_sports


def scanned_at_from_fetched_timestamp(fetched_at: float | None) -> str | None:
    if fetched_at is None:
        return None
    return datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_single_sport_manual_scan_outputs(
    *,
    result: dict[str, Any],
    sport: str,
    scanned_at: str | None,
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    base_sides = result["sides"]
    response_sides = annotate_sides(base_sides)
    response_payload = {
        "sport": sport,
        "sides": response_sides,
        "events_fetched": result["events_fetched"],
        "events_with_both_books": result["events_with_both_books"],
        "api_requests_remaining": result.get("api_requests_remaining"),
        "scanned_at": scanned_at,
    }
    persist_payload = {
        "sport": sport,
        "sides": base_sides,
        "events_fetched": result["events_fetched"],
        "events_with_both_books": result["events_with_both_books"],
        "api_requests_remaining": result.get("api_requests_remaining"),
        "scanned_at": scanned_at,
    }
    ops_status_payload = {
        "sport": sport,
        "events_fetched": result.get("events_fetched"),
        "events_with_both_books": result.get("events_with_both_books"),
        "total_sides": len(base_sides or []),
        "api_requests_remaining": result.get("api_requests_remaining"),
    }
    return {
        "base_sides": base_sides,
        "response_payload": response_payload,
        "persist_payload": persist_payload,
        "ops_status_payload": ops_status_payload,
    }


def build_all_sports_manual_scan_outputs(
    *,
    all_sides: list[dict[str, Any]],
    total_events: int,
    total_with_both: int,
    min_remaining: str | None,
    scanned_at: str | None,
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    response_sides = annotate_sides(all_sides)
    response_payload = {
        "sport": "all",
        "sides": response_sides,
        "events_fetched": total_events,
        "events_with_both_books": total_with_both,
        "api_requests_remaining": min_remaining,
        "scanned_at": scanned_at,
    }
    persist_payload = {
        "sport": "all",
        "sides": all_sides,
        "events_fetched": total_events,
        "events_with_both_books": total_with_both,
        "api_requests_remaining": min_remaining,
        "scanned_at": scanned_at,
    }
    ops_status_payload = {
        "sport": "all",
        "events_fetched": total_events,
        "events_with_both_books": total_with_both,
        "total_sides": len(all_sides),
        "api_requests_remaining": min_remaining,
    }
    return {
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
    persist_latest_scan: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    set_last_manual_scan_status(
        {
            "captured_at": captured_at,
            **bundle["ops_status_payload"],
        }
    )
    persist_payload = bundle["persist_payload"]
    schedule_piggyback(persist_payload["sides"])
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
    total_events = 0
    total_with_both = 0
    min_remaining: str | None = None
    oldest_fetched: float | None = None

    for sport in sports_to_scan:
        try:
            result = await get_cached_or_scan(sport)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                continue
            raise

        all_sides.extend(result["sides"])
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

    return {
        "all_sides": all_sides,
        "total_events": total_events,
        "total_with_both": total_with_both,
        "min_remaining": min_remaining,
        "oldest_fetched": oldest_fetched,
    }


async def run_single_sport_manual_scan(
    *,
    sport: str,
    get_cached_or_scan: Callable[[str], Awaitable[dict[str, Any]]],
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    result = await get_cached_or_scan(sport)
    scanned_at = scanned_at_from_fetched_timestamp(result.get("fetched_at"))
    return build_single_sport_manual_scan_outputs(
        result=result,
        sport=sport,
        scanned_at=scanned_at,
        annotate_sides=annotate_sides,
    )


async def run_all_sports_manual_scan(
    *,
    environment: str,
    supported_sports: list[str],
    get_cached_or_scan: Callable[[str], Awaitable[dict[str, Any]]],
    annotate_sides: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    sports_to_scan = manual_scan_sports_for_env(environment=environment, supported_sports=supported_sports)
    aggregate = await aggregate_manual_scan_all_sports(
        sports_to_scan=sports_to_scan,
        get_cached_or_scan=get_cached_or_scan,
    )
    scanned_at = scanned_at_from_fetched_timestamp(aggregate["oldest_fetched"])
    return build_all_sports_manual_scan_outputs(
        all_sides=aggregate["all_sides"],
        total_events=aggregate["total_events"],
        total_with_both=aggregate["total_with_both"],
        min_remaining=aggregate["min_remaining"],
        scanned_at=scanned_at,
        annotate_sides=annotate_sides,
    )
