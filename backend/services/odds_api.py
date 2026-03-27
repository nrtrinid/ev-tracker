"""
Odds API Service — Phase 2: The Odds Engine

Fetches live odds from The Odds API, de-vigs Pinnacle lines to derive
true probabilities, and compares them against DraftKings payouts to
surface +EV moneyline bets.
"""

import asyncio
import os
import time
import re
import httpx
from collections import deque
import threading
from datetime import datetime, timezone, timedelta
from typing import Any
from dotenv import load_dotenv
from calculations import american_to_decimal, kelly_fraction
from services.sportsbook_deeplinks import resolve_sportsbook_deeplink
from services.shared_state import get_scan_cache, set_scan_cache

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Server-side TTL cache: 5 minutes. First request after expiry pays the API call; others share cache.
CACHE_TTL_SECONDS = 5 * 60

_cache: dict[str, dict] = {}
_locks: dict[str, asyncio.Lock] = {}
_LAST_AUTO_SETTLER_SUMMARY: dict | None = None

_ODDS_ACTIVITY_LOCK = threading.Lock()
_ODDS_ACTIVITY_MAX_ENTRIES = 500
_ODDS_ACTIVITY_MAX_RECENT = 50
_ODDS_ACTIVITY_EVENTS = deque(maxlen=_ODDS_ACTIVITY_MAX_ENTRIES)
_SCAN_ACTIVITY_MAX_ENTRIES = 300
_SCAN_ACTIVITY_MAX_RECENT = 18
_SCAN_ACTIVITY_EVENTS = deque(maxlen=_SCAN_ACTIVITY_MAX_ENTRIES)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _short_error_message(message: str | None) -> str | None:
    if not message:
        return None
    cleaned = str(message).strip().replace("\n", " ")
    return cleaned[:180]


def _parse_credits_used_last(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _append_odds_api_activity(
    *,
    source: str,
    endpoint: str,
    sport: str | None,
    cache_hit: bool,
    outbound_call_made: bool,
    status_code: int | None,
    duration_ms: float | None,
    api_requests_remaining: str | int | None,
    credits_used_last: int | None = None,
    error_type: str | None,
    error_message: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    event = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "source": source,
        "endpoint": endpoint,
        "sport": sport,
        "cache_hit": cache_hit,
        "outbound_call_made": outbound_call_made,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2) if isinstance(duration_ms, (int, float)) else None,
        "api_requests_remaining": api_requests_remaining,
        "credits_used_last": credits_used_last,
        "error_type": error_type,
        "error_message": _short_error_message(error_message),
        "_ts_epoch": now.timestamp(),
    }
    with _ODDS_ACTIVITY_LOCK:
        _ODDS_ACTIVITY_EVENTS.append(event)
    try:
        from services.ops_history import persist_odds_api_activity_event

        persist_odds_api_activity_event(
            activity_kind="raw_call",
            source=source,
            captured_at=event["timestamp"],
            endpoint=endpoint,
            sport=sport,
            cache_hit=cache_hit,
            outbound_call_made=outbound_call_made,
            status_code=status_code,
            duration_ms=event["duration_ms"],
            api_requests_remaining=api_requests_remaining,
            credits_used_last=credits_used_last,
            error_type=error_type,
            error_message=event["error_message"],
        )
    except Exception:
        pass


def append_scan_activity(
    *,
    scan_session_id: str,
    source: str,
    surface: str,
    scan_scope: str,
    requested_sport: str | None,
    sport: str | None,
    actor_label: str | None,
    run_id: str | None,
    cache_hit: bool,
    outbound_call_made: bool,
    duration_ms: float | None,
    events_fetched: int | None,
    events_with_both_books: int | None,
    sides_count: int | None,
    api_requests_remaining: str | int | None,
    status_code: int | None,
    error_type: str | None,
    error_message: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    event = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "activity_kind": "scan_detail",
        "scan_session_id": scan_session_id,
        "source": source,
        "surface": surface,
        "scan_scope": scan_scope,
        "requested_sport": requested_sport,
        "sport": sport,
        "actor_label": actor_label,
        "run_id": run_id,
        "cache_hit": cache_hit,
        "outbound_call_made": outbound_call_made,
        "duration_ms": round(duration_ms, 2) if isinstance(duration_ms, (int, float)) else None,
        "events_fetched": events_fetched,
        "events_with_both_books": events_with_both_books,
        "sides_count": sides_count,
        "api_requests_remaining": api_requests_remaining,
        "status_code": status_code,
        "error_type": error_type,
        "error_message": _short_error_message(error_message),
        "_ts_epoch": now.timestamp(),
    }
    with _ODDS_ACTIVITY_LOCK:
        _SCAN_ACTIVITY_EVENTS.append(event)
    try:
        from services.ops_history import persist_odds_api_activity_event

        persist_odds_api_activity_event(
            activity_kind="scan_detail",
            source=source,
            captured_at=event["timestamp"],
            scan_session_id=scan_session_id,
            surface=surface,
            scan_scope=scan_scope,
            requested_sport=requested_sport,
            sport=sport,
            actor_label=actor_label,
            run_id=run_id,
            cache_hit=cache_hit,
            outbound_call_made=outbound_call_made,
            duration_ms=event["duration_ms"],
            events_fetched=events_fetched,
            events_with_both_books=events_with_both_books,
            sides_count=sides_count,
            api_requests_remaining=api_requests_remaining,
            status_code=status_code,
            error_type=error_type,
            error_message=event["error_message"],
        )
    except Exception:
        pass


def _sanitize_activity_event(event: dict) -> dict:
    return {
        "activity_kind": "raw_call",
        "timestamp": event.get("timestamp"),
        "source": event.get("source"),
        "endpoint": event.get("endpoint"),
        "sport": event.get("sport"),
        "cache_hit": bool(event.get("cache_hit")),
        "outbound_call_made": bool(event.get("outbound_call_made")),
        "status_code": event.get("status_code"),
        "duration_ms": event.get("duration_ms"),
        "api_requests_remaining": event.get("api_requests_remaining"),
        "credits_used_last": event.get("credits_used_last"),
        "error_type": event.get("error_type"),
        "error_message": event.get("error_message"),
    }


def _sanitize_scan_activity_detail(event: dict) -> dict:
    return {
        "activity_kind": "scan_detail",
        "timestamp": event.get("timestamp"),
        "source": event.get("source"),
        "surface": event.get("surface"),
        "scan_scope": event.get("scan_scope"),
        "requested_sport": event.get("requested_sport"),
        "sport": event.get("sport"),
        "actor_label": event.get("actor_label"),
        "run_id": event.get("run_id"),
        "cache_hit": bool(event.get("cache_hit")),
        "outbound_call_made": bool(event.get("outbound_call_made")),
        "duration_ms": event.get("duration_ms"),
        "events_fetched": event.get("events_fetched"),
        "events_with_both_books": event.get("events_with_both_books"),
        "sides_count": event.get("sides_count"),
        "api_requests_remaining": event.get("api_requests_remaining"),
        "status_code": event.get("status_code"),
        "error_type": event.get("error_type"),
        "error_message": event.get("error_message"),
    }


def _is_activity_error(event: dict) -> bool:
    status_code = event.get("status_code")
    return bool(event.get("error_type")) or (isinstance(status_code, int) and status_code >= 400)


def _try_parse_remaining(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_grouped_scan_raw_call(event: dict) -> bool:
    source = str(event.get("source") or "").strip()
    endpoint = str(event.get("endpoint") or "").strip()
    sport = str(event.get("sport") or "").strip()
    if source not in {"manual_scan", "scheduled_scan", "ops_trigger_scan"}:
        return False
    if not endpoint or not sport:
        return False
    return endpoint == f"/sports/{sport}/odds"


def _build_recent_scan_sessions(events: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}

    for event in sorted(events, key=lambda item: item.get("_ts_epoch") or 0):
        session_id = str(event.get("scan_session_id") or "").strip()
        if not session_id:
            continue

        row = grouped.get(session_id)
        if row is None:
            row = {
                "activity_kind": "scan_session",
                "scan_session_id": session_id,
                "timestamp": event.get("timestamp"),
                "source": event.get("source"),
                "surface": event.get("surface"),
                "scan_scope": event.get("scan_scope"),
                "requested_sport": event.get("requested_sport"),
                "actor_label": event.get("actor_label"),
                "run_id": event.get("run_id"),
                "detail_count": 0,
                "live_call_count": 0,
                "cache_hit_count": 0,
                "other_count": 0,
                "total_events_fetched": 0,
                "total_events_with_both_books": 0,
                "total_sides": 0,
                "min_api_requests_remaining": None,
                "error_count": 0,
                "has_errors": False,
                "details": [],
                "_latest_ts_epoch": event.get("_ts_epoch") or 0,
                "_min_remaining_numeric": None,
            }
            grouped[session_id] = row

        row["timestamp"] = event.get("timestamp") or row.get("timestamp")
        row["_latest_ts_epoch"] = max(row.get("_latest_ts_epoch") or 0, event.get("_ts_epoch") or 0)
        row["detail_count"] += 1
        if event.get("cache_hit"):
            row["cache_hit_count"] += 1
        elif event.get("outbound_call_made"):
            row["live_call_count"] += 1
        else:
            row["other_count"] += 1

        row["total_events_fetched"] += int(event.get("events_fetched") or 0)
        row["total_events_with_both_books"] += int(event.get("events_with_both_books") or 0)
        row["total_sides"] += int(event.get("sides_count") or 0)

        remaining_numeric = _try_parse_remaining(event.get("api_requests_remaining"))
        if remaining_numeric is not None:
            current_min = row.get("_min_remaining_numeric")
            if current_min is None or remaining_numeric < current_min:
                row["_min_remaining_numeric"] = remaining_numeric
                row["min_api_requests_remaining"] = remaining_numeric
        elif row.get("min_api_requests_remaining") is None and event.get("api_requests_remaining") is not None:
            row["min_api_requests_remaining"] = event.get("api_requests_remaining")

        if _is_activity_error(event):
            row["error_count"] += 1
            row["has_errors"] = True

        row["details"].append(_sanitize_scan_activity_detail(event))

    ordered = sorted(grouped.values(), key=lambda item: item.get("_latest_ts_epoch") or 0, reverse=True)
    recent = ordered[:_SCAN_ACTIVITY_MAX_RECENT]
    for row in recent:
        row.pop("_latest_ts_epoch", None)
        row.pop("_min_remaining_numeric", None)
    return recent


def get_odds_api_activity_snapshot() -> dict:
    now_epoch = datetime.now(timezone.utc).timestamp()
    last_hour_cutoff = now_epoch - 3600

    with _ODDS_ACTIVITY_LOCK:
        events = list(_ODDS_ACTIVITY_EVENTS)
        scan_events = list(_SCAN_ACTIVITY_EVENTS)

    last_hour_events = [e for e in events if isinstance(e.get("_ts_epoch"), (int, float)) and e["_ts_epoch"] >= last_hour_cutoff]
    errors_last_hour = [e for e in last_hour_events if e.get("error_type") or (isinstance(e.get("status_code"), int) and e["status_code"] >= 400)]

    last_success = None
    last_error = None
    for event in reversed(events):
        status_code = event.get("status_code")
        is_error = bool(event.get("error_type")) or (isinstance(status_code, int) and status_code >= 400)
        if last_error is None and is_error:
            last_error = event.get("timestamp")
        if last_success is None and not is_error and bool(event.get("outbound_call_made")):
            last_success = event.get("timestamp")
        if last_success and last_error:
            break

    recent_calls: list[dict] = []
    for event in reversed(events):
        if _is_grouped_scan_raw_call(event):
            continue
        recent_calls.append(_sanitize_activity_event(event))
        if len(recent_calls) >= _ODDS_ACTIVITY_MAX_RECENT:
            break

    return {
        "summary": {
            "calls_last_hour": len(last_hour_events),
            "errors_last_hour": len(errors_last_hour),
            "last_success_at": last_success,
            "last_error_at": last_error,
        },
        "recent_scans": _build_recent_scan_sessions(scan_events),
        "recent_calls": recent_calls,
    }


async def get_cached_or_scan(sport: str, source: str = "unknown") -> dict:
    """
    Return sides for this sport from cache if fresh (< CACHE_TTL_SECONDS),
    else call scan_all_sides and cache. Thread-safe per sport.
    Returned dict has: sides, events_fetched, events_with_both_books, api_requests_remaining, fetched_at (float).
    """
    if sport not in _locks:
        _locks[sport] = asyncio.Lock()
    async with _locks[sport]:
        now = time.time()
        shared_entry = get_scan_cache(sport)
        if isinstance(shared_entry, dict):
            fetched_at = shared_entry.get("fetched_at")
            if isinstance(fetched_at, (int, float)) and (now - fetched_at) < CACHE_TTL_SECONDS:
                _cache[sport] = shared_entry
                _append_odds_api_activity(
                    source=source,
                    endpoint=f"/sports/{sport}/odds",
                    sport=sport,
                    cache_hit=True,
                    outbound_call_made=False,
                    status_code=200,
                    duration_ms=0.0,
                    api_requests_remaining=shared_entry.get("api_requests_remaining"),
                    error_type=None,
                    error_message=None,
                )
                return {**shared_entry, "cache_hit": True}

        if sport in _cache:
            entry = _cache[sport]
            if (now - entry["fetched_at"]) < CACHE_TTL_SECONDS:
                _append_odds_api_activity(
                    source=source,
                    endpoint=f"/sports/{sport}/odds",
                    sport=sport,
                    cache_hit=True,
                    outbound_call_made=False,
                    status_code=200,
                    duration_ms=0.0,
                    api_requests_remaining=entry.get("api_requests_remaining"),
                    error_type=None,
                    error_message=None,
                )
                return {**entry, "cache_hit": True}

        result = await scan_all_sides(sport, source=source)
        result["fetched_at"] = now
        _cache[sport] = result
        set_scan_cache(sport, result, CACHE_TTL_SECONDS)
        return {**result, "cache_hit": False}


SUPPORTED_SPORTS = [
    "basketball_nba",
    "basketball_ncaab",
    "baseball_mlb",
]

SHARP_BOOK = "pinnacle"

# Target books: API key → display name used in the frontend
TARGET_BOOKS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "espnbet": "ESPN Bet",
}


def devig_pinnacle(outcome_a_price: float, outcome_b_price: float) -> dict:
    """
    Remove the vig from Pinnacle's two-way moneyline to get true
    no-vig probabilities using the multiplicative (odds-ratio) method.

    Returns {"team_a": float, "team_b": float} — probabilities summing to 1.0.
    """
    dec_a = american_to_decimal(outcome_a_price)
    dec_b = american_to_decimal(outcome_b_price)

    implied_a = 1.0 / dec_a
    implied_b = 1.0 / dec_b
    overround = implied_a + implied_b

    # Multiplicative power method for more accurate de-vigging
    # Solves for k where (implied_a^k + implied_b^k) = 1
    # Approximation: divide each by the overround (additive method)
    # This is the standard industry approach for two-way markets
    true_prob_a = implied_a / overround
    true_prob_b = implied_b / overround

    return {"team_a": true_prob_a, "team_b": true_prob_b}


def devig_outcomes(outcome_prices: dict[str, float]) -> dict[str, float] | None:
    """
    De-vig a market with N outcomes (2-way or 3-way) using additive normalization.

    Args:
        outcome_prices: mapping of outcome name -> American odds

    Returns:
        mapping of outcome name -> true probability (sums to 1.0), or None if invalid
    """
    if not outcome_prices:
        return None

    implied: dict[str, float] = {}
    for name, price in outcome_prices.items():
        try:
            dec = american_to_decimal(float(price))
            if dec <= 1:
                return None
            implied[name] = 1.0 / dec
        except Exception:
            return None

    overround = sum(implied.values())
    if overround <= 0:
        return None

    return {name: (p / overround) for name, p in implied.items()}


def _find_draw_key(outcomes: dict[str, float], home: str, away: str) -> str | None:
    """
    For 3-way h2h markets, attempt to find the draw/tie outcome key.
    """
    if not outcomes:
        return None

    lower_to_key = {k.lower(): k for k in outcomes.keys()}
    for candidate in ("draw", "tie", "x"):
        if candidate in lower_to_key:
            k = lower_to_key[candidate]
            if k not in (home, away):
                return k

    extras = [k for k in outcomes.keys() if k not in (home, away)]
    return extras[0] if len(extras) == 1 else None


def calculate_edge(true_prob: float, book_american_odds: float) -> dict:
    """
    Compare the true no-vig probability against a target book's offered odds
    to determine the EV edge.

    Returns:
        ev_percentage: the edge as a percentage (e.g. 3.5 means +3.5% EV)
        book_implied_prob: what the book's odds imply
        true_prob: the de-vigged sharp probability
        book_decimal: book's decimal odds
    """
    book_decimal = american_to_decimal(book_american_odds)
    book_implied_prob = 1.0 / book_decimal

    ev_raw = (true_prob * book_decimal) - 1.0
    ev_percentage = round(ev_raw * 100, 2)

    return {
        "ev_percentage": ev_percentage,
        "book_implied_prob": round(book_implied_prob, 4),
        "true_prob": round(true_prob, 4),
        "book_decimal": round(book_decimal, 4),
    }


async def fetch_odds(
    sport: str = "basketball_nba",
    *,
    source: str = "unknown",
    endpoint: str | None = None,
    markets: str = "h2h",
    regions: str = "us,us2",
    bookmakers: str | None = None,
) -> tuple[list[dict], httpx.Response]:
    """
    Hit The Odds API and return raw event data with odds
    from Pinnacle and all target books.
    """
    if not ODDS_API_KEY:
        raise ValueError("ODDS_API_KEY not set in environment")

    all_books = bookmakers or ",".join([SHARP_BOOK] + list(TARGET_BOOKS.keys()))
    url = f"{ODDS_API_BASE}/sports/{sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": all_books,
        "includeLinks": "true",
        "includeSids": "true",
    }

    started = time.monotonic()
    endpoint_value = endpoint or f"/sports/{sport}/odds"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            duration_ms = (time.monotonic() - started) * 1000
            remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")
            credits_used_last = _parse_credits_used_last(resp.headers.get("x-requests-last"))
            _append_odds_api_activity(
                source=source,
                endpoint=endpoint_value,
                sport=sport,
                cache_hit=False,
                outbound_call_made=True,
                status_code=resp.status_code,
                duration_ms=duration_ms,
                api_requests_remaining=remaining,
                credits_used_last=credits_used_last,
                error_type=None,
                error_message=None,
            )
            return resp.json(), resp
    except httpx.HTTPStatusError as e:
        duration_ms = (time.monotonic() - started) * 1000
        status_code = e.response.status_code if e.response is not None else None
        remaining = None
        credits_used_last = None
        if e.response is not None:
            remaining = e.response.headers.get("x-requests-remaining") or e.response.headers.get("x-request-remaining")
            credits_used_last = _parse_credits_used_last(e.response.headers.get("x-requests-last"))
        _append_odds_api_activity(
            source=source,
            endpoint=endpoint_value,
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=status_code,
            duration_ms=duration_ms,
            api_requests_remaining=remaining,
            credits_used_last=credits_used_last,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise
    except Exception as e:
        duration_ms = (time.monotonic() - started) * 1000
        _append_odds_api_activity(
            source=source,
            endpoint=endpoint_value,
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=None,
            duration_ms=duration_ms,
            api_requests_remaining=None,
            credits_used_last=None,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise


def _extract_totals_market(bookmakers: list[dict], book_key: str) -> dict | None:
    for bm in bookmakers:
        if bm.get("key") != book_key:
            continue
        for market in bm.get("markets", []):
            if market.get("key") != "totals":
                continue
            outcomes = market.get("outcomes") or []
            over = next((o for o in outcomes if str(o.get("name") or "").strip().lower() == "over"), None)
            under = next((o for o in outcomes if str(o.get("name") or "").strip().lower() == "under"), None)
            if not over or not under:
                return None
            try:
                point_over = float(over.get("point"))
                point_under = float(under.get("point"))
            except Exception:
                return None
            # Require the total points to match (avoids mixing alt totals).
            if point_over != point_under:
                return None
            try:
                over_price = float(over.get("price"))
                under_price = float(under.get("price"))
            except Exception:
                return None
            return {
                "total": point_over,
                "over_odds": over_price,
                "under_odds": under_price,
            }
    return None


def _extract_spreads_market(bookmakers: list[dict], book_key: str, home_team: str, away_team: str) -> dict | None:
    for bm in bookmakers:
        if bm.get("key") != book_key:
            continue
        for market in bm.get("markets", []):
            if market.get("key") != "spreads":
                continue
            outcomes = market.get("outcomes") or []
            home = next((o for o in outcomes if str(o.get("name") or "").strip() == home_team), None)
            away = next((o for o in outcomes if str(o.get("name") or "").strip() == away_team), None)
            if not home or not away:
                return None
            try:
                home_spread = float(home.get("point"))
                away_spread = float(away.get("point"))
                home_price = float(home.get("price"))
                away_price = float(away.get("price"))
            except Exception:
                return None
            # Typical spread market has mirrored points (+x / -x). Accept tiny float noise.
            if abs(home_spread + away_spread) > 0.01:
                return None
            return {
                "home_spread": home_spread,
                "away_spread": away_spread,
                "home_odds": home_price,
                "away_odds": away_price,
            }
    return None


async def fetch_nba_totals_slate(*, source: str) -> dict:
    """Broad NBA totals fetch used for daily-board event selection + context."""
    # Use the same book set as straight-bets scans (Pinnacle + target books).
    all_books = ",".join([SHARP_BOOK] + list(TARGET_BOOKS.keys()))
    data, resp = await fetch_odds(
        "basketball_nba",
        source=source,
        markets="totals",
        regions="us,us2",
        bookmakers=all_books,
        endpoint="/sports/basketball_nba/odds?markets=totals",
    )
    events = data if isinstance(data, list) else []
    remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")

    games: list[dict] = []
    for event in events:
        event_id = str(event.get("id") or "").strip() or None
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        commence = str(event.get("commence_time") or "").strip()
        if not home or not away or not commence:
            continue

        offers: list[dict] = []
        for book_key, book_display in {SHARP_BOOK: "Pinnacle", **TARGET_BOOKS}.items():
            market = _extract_totals_market(event.get("bookmakers", []), book_key)
            if not market:
                continue
            offers.append(
                {
                    "sportsbook": book_display,
                    "total": market["total"],
                    "over_odds": market["over_odds"],
                    "under_odds": market["under_odds"],
                }
            )

        if not offers:
            continue

        games.append(
            {
                "event_id": event_id,
                "sport": "basketball_nba",
                "event": f"{away} @ {home}",
                "away_team": away,
                "home_team": home,
                "commence_time": commence,
                "totals_offers": offers,
            }
        )

    return {
        "sport": "basketball_nba",
        "games": games,
        "events_fetched": len(events),
        "api_requests_remaining": remaining,
    }


async def fetch_featured_lines_slate(*, sport: str, source: str) -> dict:
    """Sport-level featured game lines fetch for board context."""
    all_books = ",".join([SHARP_BOOK] + list(TARGET_BOOKS.keys()))
    data, resp = await fetch_odds(
        sport,
        source=source,
        markets="h2h,spreads,totals",
        regions="us,us2",
        bookmakers=all_books,
        endpoint=f"/sports/{sport}/odds?markets=h2h,spreads,totals",
    )
    events = data if isinstance(data, list) else []
    remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")

    games: list[dict] = []
    for event in events:
        event_id = str(event.get("id") or "").strip() or None
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        commence = str(event.get("commence_time") or "").strip()
        if not home or not away or not commence:
            continue

        h2h_offers: list[dict] = []
        spreads_offers: list[dict] = []
        totals_offers: list[dict] = []
        for book_key, book_display in {SHARP_BOOK: "Pinnacle", **TARGET_BOOKS}.items():
            h2h_market = _extract_h2h_bookmaker_market(event.get("bookmakers", []), book_key)
            if h2h_market:
                h2h_outcomes = h2h_market.get("outcomes") or {}
                home_ml = h2h_outcomes.get(home)
                away_ml = h2h_outcomes.get(away)
                if home_ml is not None and away_ml is not None:
                    h2h_offers.append(
                        {
                            "sportsbook": book_display,
                            "home_odds": float(home_ml),
                            "away_odds": float(away_ml),
                        }
                    )

            spreads_market = _extract_spreads_market(event.get("bookmakers", []), book_key, home, away)
            if spreads_market:
                spreads_offers.append({"sportsbook": book_display, **spreads_market})

            totals_market = _extract_totals_market(event.get("bookmakers", []), book_key)
            if totals_market:
                totals_offers.append({"sportsbook": book_display, **totals_market})

        if not h2h_offers and not spreads_offers and not totals_offers:
            continue

        games.append(
            {
                "event_id": event_id,
                "sport": sport,
                "event": f"{away} @ {home}",
                "away_team": away,
                "home_team": home,
                "commence_time": commence,
                "h2h_offers": h2h_offers,
                "spreads_offers": spreads_offers,
                "totals_offers": totals_offers,
            }
        )

    return {
        "sport": sport,
        "games": games,
        "events_fetched": len(events),
        "api_requests_remaining": remaining,
    }


async def fetch_events(
    sport: str = "basketball_nba",
    *,
    source: str = "unknown",
) -> tuple[list[dict], httpx.Response]:
    """
    Fetch the upcoming events list for a sport.

    This endpoint returns event ids without market odds and is the cheapest
    source of truth for mapping ESPN schedule entries to Odds API event ids.
    """
    if not ODDS_API_KEY:
        raise ValueError("ODDS_API_KEY not set in environment")

    url = f"{ODDS_API_BASE}/sports/{sport}/events"
    started = time.monotonic()
    endpoint_value = f"/sports/{sport}/events"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params={"apiKey": ODDS_API_KEY})
            resp.raise_for_status()
            duration_ms = (time.monotonic() - started) * 1000
            remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")
            credits_used_last = _parse_credits_used_last(resp.headers.get("x-requests-last"))
            _append_odds_api_activity(
                source=source,
                endpoint=endpoint_value,
                sport=sport,
                cache_hit=False,
                outbound_call_made=True,
                status_code=resp.status_code,
                duration_ms=duration_ms,
                api_requests_remaining=remaining,
                credits_used_last=credits_used_last,
                error_type=None,
                error_message=None,
            )
            data = resp.json()
            return (data if isinstance(data, list) else []), resp
    except httpx.HTTPStatusError as e:
        duration_ms = (time.monotonic() - started) * 1000
        status_code = e.response.status_code if e.response is not None else None
        remaining = None
        credits_used_last = None
        if e.response is not None:
            remaining = e.response.headers.get("x-requests-remaining") or e.response.headers.get("x-request-remaining")
            credits_used_last = _parse_credits_used_last(e.response.headers.get("x-requests-last"))
        _append_odds_api_activity(
            source=source,
            endpoint=endpoint_value,
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=status_code,
            duration_ms=duration_ms,
            api_requests_remaining=remaining,
            credits_used_last=credits_used_last,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise
    except Exception as e:
        duration_ms = (time.monotonic() - started) * 1000
        _append_odds_api_activity(
            source=source,
            endpoint=endpoint_value,
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=None,
            duration_ms=duration_ms,
            api_requests_remaining=None,
            credits_used_last=None,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise


def _extract_h2h_bookmaker_market(bookmakers: list[dict], book_key: str) -> dict | None:
    for bm in bookmakers:
        if bm["key"] == book_key:
            event_link = bm.get("link") or bm.get("url")
            for market in bm.get("markets", []):
                if market["key"] == "h2h":
                    outcomes = market.get("outcomes") or []
                    return {
                        "outcomes": {o["name"]: o["price"] for o in outcomes},
                        "selection_links": {
                            o["name"]: o.get("link") or o.get("url")
                            for o in outcomes
                        },
                        "market_link": market.get("link") or market.get("url"),
                        "event_link": event_link,
                    }
    return None


def _extract_bookmaker_meta(bookmakers: list[dict], book_key: str) -> tuple[dict | None, str | None]:
    """Pull h2h outcomes + optional bookmaker deep link for a bookmaker key."""
    market = _extract_h2h_bookmaker_market(bookmakers, book_key)
    if market:
        return market["outcomes"], market["event_link"]
    return None, None


def _extract_outcomes(bookmakers: list[dict], book_key: str) -> dict | None:
    outcomes, _deep_link = _extract_bookmaker_meta(bookmakers, book_key)
    return outcomes


async def scan_for_ev(sport: str = "basketball_nba") -> dict:
    """
    Full pipeline: fetch → de-vig → compare → return +EV bets and metadata.
    Scans across all TARGET_BOOKS.
    """
    data, resp = await fetch_odds(sport, source="scan_for_ev")
    events = data if isinstance(data, list) else []
    ev_bets = []
    events_with_pinnacle = 0

    for event in events:
        home = event["home_team"]
        away = event["away_team"]
        commence = event.get("commence_time", "")

        pin_outcomes = _extract_outcomes(event.get("bookmakers", []), SHARP_BOOK)
        if not pin_outcomes:
            continue

        pin_home = pin_outcomes.get(home)
        pin_away = pin_outcomes.get(away)
        if None in (pin_home, pin_away):
            continue
        draw_key = _find_draw_key(pin_outcomes, home, away)
        if draw_key:
            true_probs_n = devig_outcomes({home: pin_home, away: pin_away, draw_key: pin_outcomes[draw_key]})
            if not true_probs_n:
                continue
            true_probs = {"team_a": true_probs_n[home], "team_b": true_probs_n[away]}
            true_prob_draw = true_probs_n[draw_key]
        else:
            true_probs = devig_pinnacle(pin_home, pin_away)
            true_prob_draw = None
        had_any_book = False

        for book_key, book_display in TARGET_BOOKS.items():
            book_market = _extract_h2h_bookmaker_market(event.get("bookmakers", []), book_key)
            if not book_market:
                continue
            book_outcomes = book_market["outcomes"]

            book_home = book_outcomes.get(home)
            book_away = book_outcomes.get(away)
            if None in (book_home, book_away):
                continue

            had_any_book = True

            home_edge = calculate_edge(true_probs["team_a"], book_home)
            if home_edge["ev_percentage"] > 0:
                ev_bets.append({
                    "sportsbook": book_display,
                    "sport": event.get("sport_key", sport),
                    "event": f"{away} @ {home}",
                    "commence_time": commence,
                    "team": home,
                    "pinnacle_odds": pin_home,
                    "book_odds": book_home,
                    "true_prob": home_edge["true_prob"],
                    "base_kelly_fraction": round(kelly_fraction(home_edge["true_prob"], home_edge["book_decimal"]), 6),
                    "ev_percentage": home_edge["ev_percentage"],
                    "book_decimal": home_edge["book_decimal"],
                })

            away_edge = calculate_edge(true_probs["team_b"], book_away)
            if away_edge["ev_percentage"] > 0:
                ev_bets.append({
                    "sportsbook": book_display,
                    "sport": event.get("sport_key", sport),
                    "event": f"{away} @ {home}",
                    "commence_time": commence,
                    "team": away,
                    "pinnacle_odds": pin_away,
                    "book_odds": book_away,
                    "true_prob": away_edge["true_prob"],
                    "base_kelly_fraction": round(kelly_fraction(away_edge["true_prob"], away_edge["book_decimal"]), 6),
                    "ev_percentage": away_edge["ev_percentage"],
                    "book_decimal": away_edge["book_decimal"],
                })

            if true_prob_draw is not None:
                book_draw_key = _find_draw_key(book_outcomes, home, away)
                if book_draw_key and book_draw_key in book_outcomes:
                    draw_edge = calculate_edge(true_prob_draw, book_outcomes[book_draw_key])
                    if draw_edge["ev_percentage"] > 0:
                        ev_bets.append({
                            "sportsbook": book_display,
                            "sport": event.get("sport_key", sport),
                            "event": f"{away} @ {home}",
                            "commence_time": commence,
                            "team": book_draw_key,
                            "pinnacle_odds": pin_outcomes[draw_key],
                            "book_odds": book_outcomes[book_draw_key],
                            "true_prob": draw_edge["true_prob"],
                            "base_kelly_fraction": round(kelly_fraction(draw_edge["true_prob"], draw_edge["book_decimal"]), 6),
                            "ev_percentage": draw_edge["ev_percentage"],
                            "book_decimal": draw_edge["book_decimal"],
                        })

        if had_any_book:
            events_with_pinnacle += 1

    ev_bets.sort(key=lambda b: b["ev_percentage"], reverse=True)

    remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")

    return {
        "opportunities": ev_bets,
        "events_fetched": len(events),
        "events_with_both_books": events_with_pinnacle,
        "api_requests_remaining": remaining,
    }


def update_clv_snapshots(sides: list[dict], db) -> int:
    """
    Piggyback reference update for pending bets.

    Fresh scan snapshots update `latest_pinnacle_odds` for matching pending bets.
    `pinnacle_odds_at_close` is only populated when the fresh snapshot is inside
    the close window handled by the shared CLV-tracking helper.
    """
    from services.clv_tracking import update_bet_reference_snapshots

    counts = update_bet_reference_snapshots(db, sides=sides, allow_close=True)
    return counts["latest_updated"]


async def fetch_clv_for_pending_bets(db) -> int:
    """
    Layer 3 — Daily safety-net job. Called by APScheduler.

    Finds all pending bets with CLV tracking enabled, groups them by sport key,
    and makes one fat fetch_odds call per active sport. Updates pinnacle_odds_at_close
    for all matched bets. Returns total bets updated.
    """
    # Find pending bets with CLV tracking grouped by sport key
    result = (
        db.table("bets")
        .select("clv_sport_key")
        .eq("result", "pending")
        .not_.is_("clv_sport_key", "null")
        .execute()
    )

    if not result.data:
        return 0

    sport_keys = list({row["clv_sport_key"] for row in result.data if row.get("clv_sport_key")})

    if not sport_keys:
        return 0

    total_updated = 0

    for sport_key in sport_keys:
        try:
            data, _ = await fetch_odds(sport_key, source="clv_daily")
            events = data if isinstance(data, list) else []

            sides = []
            for event in events:
                home = event["home_team"]
                away = event["away_team"]
                ct = event.get("commence_time", "")

                pin_outcomes = _extract_outcomes(event.get("bookmakers", []), SHARP_BOOK)
                if not pin_outcomes:
                    continue

                pin_home = pin_outcomes.get(home)
                pin_away = pin_outcomes.get(away)
                if None in (pin_home, pin_away):
                    continue

                sides.append({"commence_time": ct, "team": home, "pinnacle_odds": pin_home})
                sides.append({"commence_time": ct, "team": away, "pinnacle_odds": pin_away})
                event_id = str(event.get("id") or "").strip()
                if event_id:
                    sides[-2]["event_id"] = event_id
                    sides[-1]["event_id"] = event_id

            updated = update_clv_snapshots(sides, db)
            total_updated += updated

        except Exception as e:
            # Never let a single sport failure break the entire job
            print(f"[CLV daily job] Error processing sport '{sport_key}': {e}")

    return total_updated


async def run_jit_clv_snatcher(db) -> int:
    """
    JIT CLV Snatcher — runs every 15 minutes via APScheduler.

    Finds pending bets whose game is starting within the next 20 minutes and
    whose closing Pinnacle line has not yet been captured. The IS NULL check on
    pinnacle_odds_at_close acts as an idempotency lock — once written, the row
    is never touched again by this job.

    One fetch_odds call per unique sport_key (1 API token each).
    Returns the number of bets updated.
    """
    from datetime import datetime, timezone, timedelta
    from services.clv_tracking import (
        CLOSE_WINDOW_MINUTES,
        has_valid_close_snapshot,
        update_bet_reference_snapshots,
        update_scan_opportunity_reference_snapshots,
    )
    from services.research_opportunities import is_missing_scan_opportunities_error
    from services.player_props import (
        _fetch_prop_market_for_event,
        _parse_prop_sides,
        get_player_prop_min_reference_bookmakers,
    )

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(minutes=CLOSE_WINDOW_MINUTES)
    now_iso = now.isoformat()
    window_end_iso = window_end.isoformat()

    bet_result = (
        db.table("bets")
        .select("id,clv_sport_key,commence_time,pinnacle_odds_at_close,clv_updated_at")
        .eq("result", "pending")
        .not_.is_("clv_sport_key", "null")
        .gt("commence_time", now_iso)
        .lte("commence_time", window_end_iso)
        .execute()
    )
    try:
        opportunity_result = (
            db.table("scan_opportunities")
            .select("id,sport,surface,event_id,source_market_key,commence_time,reference_odds_at_close,close_captured_at")
            .gt("commence_time", now_iso)
            .lte("commence_time", window_end_iso)
            .execute()
        )
    except Exception as e:
        if is_missing_scan_opportunities_error(e):
            opportunity_result = type("EmptyResult", (), {"data": []})()
        else:
            raise

    bet_candidates = [
        row for row in (bet_result.data or [])
        if row.get("pinnacle_odds_at_close") is None
        or not has_valid_close_snapshot(row.get("commence_time"), row.get("clv_updated_at"))
    ]
    opportunity_candidates = [
        row for row in (opportunity_result.data or [])
        if row.get("reference_odds_at_close") is None
        or not has_valid_close_snapshot(row.get("commence_time"), row.get("close_captured_at"))
    ]

    if not bet_candidates and not opportunity_candidates:
        return 0

    straight_sport_keys = {
        str(row.get("clv_sport_key") or "").strip()
        for row in bet_candidates
        if row.get("clv_sport_key")
    }
    prop_fetch_plan: dict[str, dict[str, set[str]]] = {}
    for row in opportunity_candidates:
        sport = str(row.get("sport") or "").strip()
        if not sport:
            continue
        surface = str(row.get("surface") or "straight_bets").strip().lower()
        if surface == "player_props":
            event_id = str(row.get("event_id") or "").strip()
            market_key = str(row.get("source_market_key") or "").strip()
            if not event_id or not market_key:
                continue
            prop_fetch_plan.setdefault(sport, {}).setdefault(event_id, set()).add(market_key)
            continue
        straight_sport_keys.add(sport)

    sport_keys = sorted(straight_sport_keys | set(prop_fetch_plan.keys()))

    total_close_updated = 0

    for sport_key in sport_keys:
        try:
            sides: list[dict[str, Any]] = []
            if sport_key in straight_sport_keys:
                data, _ = await fetch_odds(sport_key, source="jit_clv")
                events = data if isinstance(data, list) else []
                for event in events:
                    home = event["home_team"]
                    away = event["away_team"]
                    ct = event.get("commence_time", "")
                    event_id = str(event.get("id") or "").strip()
                    pin_outcomes = _extract_outcomes(event.get("bookmakers", []), SHARP_BOOK)
                    if not pin_outcomes:
                        continue
                    pin_home = pin_outcomes.get(home)
                    pin_away = pin_outcomes.get(away)
                    if pin_home is not None:
                        side = {"surface": "straight_bets", "sport": sport_key, "commence_time": ct, "team": home, "pinnacle_odds": pin_home}
                        if event_id:
                            side["event_id"] = event_id
                        sides.append(side)
                    if pin_away is not None:
                        side = {"surface": "straight_bets", "sport": sport_key, "commence_time": ct, "team": away, "pinnacle_odds": pin_away}
                        if event_id:
                            side["event_id"] = event_id
                        sides.append(side)

            if sport_key in prop_fetch_plan:
                min_reference_bookmakers = get_player_prop_min_reference_bookmakers()
                for event_id, markets in prop_fetch_plan[sport_key].items():
                    try:
                        event_payload, _ = await _fetch_prop_market_for_event(
                            sport=sport_key,
                            event_id=event_id,
                            markets=sorted(markets),
                            source="jit_clv_props",
                        )
                    except Exception:
                        continue
                    prop_sides = _parse_prop_sides(
                        sport=sport_key,
                        event_payload=event_payload,
                        target_markets=sorted(markets),
                        player_context_lookup=None,
                        min_reference_bookmakers=min_reference_bookmakers,
                    )
                    sides.extend(prop_sides)

            if not sides:
                continue

            bet_updates = update_bet_reference_snapshots(db, sides=sides, allow_close=True, now=now)
            opportunity_updates = update_scan_opportunity_reference_snapshots(
                db,
                sides=sides,
                allow_close=True,
                now=now,
            )
            total_close_updated += bet_updates["close_updated"] + opportunity_updates["close_updated"]

        except Exception as e:
            print(f"[JIT CLV] Error processing sport '{sport_key}': {e}")

    return total_close_updated


async def fetch_scores(sport: str, source: str = "auto_settle") -> list[dict]:
    """
    Fetch completed game scores from The Odds API.

    daysFrom=2 returns games completed in the last 2 days — wide enough to
    catch overnight finishes and any games that ran into extra time.
    Costs 1 API token per sport call.
    """
    if not ODDS_API_KEY:
        raise ValueError("ODDS_API_KEY not set in environment")

    url = f"{ODDS_API_BASE}/sports/{sport}/scores"
    params = {
        "apiKey": ODDS_API_KEY,
        "daysFrom": 2,
        "dateFormat": "iso",
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            duration_ms = (time.monotonic() - started) * 1000
            remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")
            credits_used_last = _parse_credits_used_last(resp.headers.get("x-requests-last"))
            _append_odds_api_activity(
                source=source,
                endpoint=f"/sports/{sport}/scores",
                sport=sport,
                cache_hit=False,
                outbound_call_made=True,
                status_code=resp.status_code,
                duration_ms=duration_ms,
                api_requests_remaining=remaining,
                credits_used_last=credits_used_last,
                error_type=None,
                error_message=None,
            )
            data = resp.json()
            return data if isinstance(data, list) else []
    except httpx.HTTPStatusError as e:
        duration_ms = (time.monotonic() - started) * 1000
        status_code = e.response.status_code if e.response is not None else None
        remaining = None
        credits_used_last = None
        if e.response is not None:
            remaining = e.response.headers.get("x-requests-remaining") or e.response.headers.get("x-request-remaining")
            credits_used_last = _parse_credits_used_last(e.response.headers.get("x-requests-last"))
        _append_odds_api_activity(
            source=source,
            endpoint=f"/sports/{sport}/scores",
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=status_code,
            duration_ms=duration_ms,
            api_requests_remaining=remaining,
            credits_used_last=credits_used_last,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise
    except Exception as e:
        duration_ms = (time.monotonic() - started) * 1000
        _append_odds_api_activity(
            source=source,
            endpoint=f"/sports/{sport}/scores",
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=None,
            duration_ms=duration_ms,
            api_requests_remaining=None,
            credits_used_last=None,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise


def _grade_ml(clv_team: str, home_team: str, away_team: str, scores: list[dict]) -> str | None:
    """
    Grade a moneyline bet given the completed game scores.

    scores is the 'scores' list from The Odds API event object, e.g.:
        [{"name": "Los Angeles Lakers", "score": "118"},
         {"name": "Boston Celtics",     "score": "120"}]

    Returns 'win', 'loss', or 'push', or None if the score data is unusable.
    """
    score_map: dict[str, float] = {}
    score_map_norm: dict[str, float] = {}
    for s in scores or []:
        try:
            team_name = str(s["name"])
            score_val = float(s["score"])
            score_map[team_name] = score_val
            score_map_norm[_canonical_team_name(team_name)] = score_val
        except (KeyError, ValueError, TypeError):
            pass

    clv_team_norm = _canonical_team_name(clv_team)
    home_norm = _canonical_team_name(home_team)
    away_norm = _canonical_team_name(away_team)

    if clv_team_norm == home_norm:
        opponent = away_team
    elif clv_team_norm == away_norm:
        opponent = home_team
    else:
        return None

    bet_score = score_map.get(clv_team)
    if bet_score is None:
        bet_score = score_map_norm.get(_canonical_team_name(clv_team))

    opp_score = score_map.get(opponent)
    if opp_score is None:
        opp_score = score_map_norm.get(_canonical_team_name(opponent))

    if bet_score is None or opp_score is None:
        return None

    if bet_score > opp_score:
        return "win"
    if bet_score < opp_score:
        return "loss"
    return "push"


def _canonical_team_name(name: str | None) -> str:
    if not name:
        return ""
    lowered = str(name).strip().lower()
    return re.sub(r"[^a-z0-9]+", "", lowered)


def _parse_utc_iso(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    raw = str(timestamp).strip()
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


def _commence_times_match(event_commence_time: str | None, bet_commence_time: str | None) -> bool:
    # Fast path for exact string equality.
    if event_commence_time == bet_commence_time:
        return True

    event_dt = _parse_utc_iso(event_commence_time)
    bet_dt = _parse_utc_iso(bet_commence_time)
    if event_dt is None or bet_dt is None:
        return False

    # The Odds API score commence_time can drift by seconds from stored scanner values.
    return abs((event_dt - bet_dt).total_seconds()) <= 90


def _select_completed_event_for_bet(bet: dict, completed_events: list[dict]) -> tuple[dict | None, str]:
    """
    Deterministic settlement match to prevent accidental auto-grading.

    We auto-grade when there is exactly one completed event matching.
    Preferred match path:
    - clv_event_id equals event.id
    Fallback match path:
    - commence_time equality after UTC normalization (with small seconds tolerance)
    - clv_team equals home_team or away_team (canonicalized)
    """
    clv_event_id = str(bet.get("clv_event_id") or "").strip()
    if clv_event_id:
        id_candidates = [
            event for event in completed_events
            if str(event.get("id") or "").strip() == clv_event_id
        ]
        if len(id_candidates) == 1:
            return id_candidates[0], "matched"
        if len(id_candidates) > 1:
            return None, "ambiguous_match"

    clv_team = bet.get("clv_team")
    commence_time = bet.get("commence_time")
    if not clv_team:
        return None, "missing_clv_team"
    if not commence_time:
        return None, "missing_commence_time"

    target_team = _canonical_team_name(clv_team)
    candidates: list[dict] = []
    for event in completed_events:
        if not _commence_times_match(event.get("commence_time"), commence_time):
            continue

        home = _canonical_team_name(event.get("home_team"))
        away = _canonical_team_name(event.get("away_team"))
        if target_team in (home, away):
            candidates.append(event)

    if not candidates:
        return None, "no_match"
    if len(candidates) > 1:
        return None, "ambiguous_match"
    return candidates[0], "matched"


async def run_auto_settler(db, source: str = "auto_settle") -> int:
    """
    Auto-Settler — runs once daily (APScheduler) or via ops trigger.

    Grades pending bets: moneyline (The Odds API /scores), NBA player props
    (ESPN boxscore), and parlays (per-leg ML + NBA props, combined result).
    """
    from datetime import datetime, timezone

    from services.prop_settler import (
        collect_sport_keys_from_parlays,
        create_prop_settle_telemetry,
        is_standalone_prop_bet,
        settle_parlays,
        settle_standalone_props,
    )

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    try:
        result = (
            db.table("bets")
            .select(
                "id,market,surface,clv_sport_key,clv_team,commence_time,clv_event_id,"
                "participant_name,source_market_key,line_value,selection_side"
            )
            .eq("result", "pending")
            .not_.is_("clv_sport_key", "null")
            .lt("commence_time", now_iso)
            .execute()
        )
    except Exception as e:
        # Backward compatibility: if migration for clv_event_id is not applied yet,
        # settle using legacy fields only.
        if "clv_event_id" not in str(e):
            raise
        result = (
            db.table("bets")
            .select("id,market,surface,clv_sport_key,clv_team,commence_time")
            .eq("result", "pending")
            .not_.is_("clv_sport_key", "null")
            .lt("commence_time", now_iso)
            .execute()
        )

    standalone_bets = list(result.data or [])

    try:
        parlay_result = (
            db.table("bets")
            .select("id,selection_meta")
            .eq("result", "pending")
            .eq("market", "Parlay")
            .execute()
        )
        parlay_bets = list(parlay_result.data or [])
    except Exception:
        parlay_bets = []

    if not standalone_bets and not parlay_bets:
        return 0

    sport_keys: set[str] = set()
    for bet in standalone_bets:
        sk = bet.get("clv_sport_key")
        if sk:
            sport_keys.add(str(sk))
    sport_keys.update(collect_sport_keys_from_parlays(parlay_bets))

    completed_by_sport: dict[str, list[dict]] = {}
    fetch_errors: list[dict] = []
    for sport_key in sorted(sport_keys):
        try:
            events = await fetch_scores(sport_key, source=source)
            completed_by_sport[sport_key] = [event for event in events if event.get("completed")]
        except Exception as e:
            print(f"[Auto-Settler] Error fetching scores for '{sport_key}': {e}")
            completed_by_sport[sport_key] = []
            fetch_errors.append({"sport_key": sport_key, "error": f"{type(e).__name__}: {e}"})

    sport_bets: dict[str, list[dict]] = {}
    for bet in standalone_bets:
        sk = bet.get("clv_sport_key")
        if sk:
            sport_bets.setdefault(str(sk), []).append(bet)

    total_settled = 0
    settled_at = now.isoformat()
    sport_summaries: list[dict] = []
    aggregate_skipped = {
        "missing_clv_team": 0,
        "missing_commence_time": 0,
        "no_match": 0,
        "ambiguous_match": 0,
        "missing_scores": 0,
        "db_update_failed": 0,
    }

    for sport_key, bets in sport_bets.items():
        try:
            completed_events = completed_by_sport.get(sport_key, [])
            skipped_reasons: dict[str, int] = {
                "missing_clv_team": 0,
                "missing_commence_time": 0,
                "no_match": 0,
                "ambiguous_match": 0,
                "missing_scores": 0,
                "db_update_failed": 0,
            }

            for bet in bets:
                market = (bet.get("market") or "").strip().upper()
                clv_team = bet.get("clv_team")

                if market != "ML":
                    if is_standalone_prop_bet(bet):
                        continue
                    print(
                        f"[Auto-Settler] Skipping bet {bet['id']} — "
                        f"market '{market}' requires manual grading."
                    )
                    continue

                if not clv_team:
                    continue

                event, reason = _select_completed_event_for_bet(bet, completed_events)
                if event is None:
                    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                    continue

                grade = _grade_ml(
                    clv_team,
                    str(event.get("home_team", "")),
                    str(event.get("away_team", "")),
                    event.get("scores") or [],
                )

                if grade is None:
                    skipped_reasons["missing_scores"] += 1
                    continue

                try:
                    db.table("bets").update({
                        "result": grade,
                        "settled_at": settled_at,
                    }).eq("id", bet["id"]).execute()
                    total_settled += 1
                except Exception as e:
                    skipped_reasons["db_update_failed"] += 1
                    print(f"[Auto-Settler] Failed updating bet {bet.get('id')}: {e}")

            if any(v > 0 for v in skipped_reasons.values()):
                print(
                    "[Auto-Settler] Sport summary "
                    f"sport={sport_key} skipped={skipped_reasons} completed_events={len(completed_events)}"
                )

            for key, value in skipped_reasons.items():
                aggregate_skipped[key] = aggregate_skipped.get(key, 0) + value

            sport_summaries.append(
                {
                    "sport_key": sport_key,
                    "bets_considered": len(bets),
                    "completed_events": len(completed_events),
                    "skipped": skipped_reasons,
                }
            )

        except Exception as e:
            print(f"[Auto-Settler] Error processing sport '{sport_key}': {e}")
            sport_summaries.append(
                {
                    "sport_key": sport_key,
                    "bets_considered": len(bets),
                    "completed_events": None,
                    "error": f"{type(e).__name__}: {e}",
                }
            )

    prop_candidates = [b for b in standalone_bets if is_standalone_prop_bet(b)]
    prop_telemetry = create_prop_settle_telemetry()
    props_settled, props_skipped = await settle_standalone_props(
        db,
        prop_candidates,
        completed_by_sport,
        settled_at,
        source=source,
        now=now,
        telemetry=prop_telemetry,
    )

    parlays_settled, parlay_skipped = await settle_parlays(
        db,
        parlay_bets,
        completed_by_sport,
        settled_at,
        now=now,
        source=source,
        telemetry=prop_telemetry,
    )

    combined_total = total_settled + props_settled + parlays_settled

    global _LAST_AUTO_SETTLER_SUMMARY
    _LAST_AUTO_SETTLER_SUMMARY = {
        "captured_at": settled_at,
        "sports": sport_summaries,
        "total_settled": combined_total,
        "ml_settled": total_settled,
        "props_settled": props_settled,
        "parlays_settled": parlays_settled,
        "skipped_totals": aggregate_skipped,
        "props_skipped": props_skipped,
        "parlay_skipped": parlay_skipped,
        "score_fetch_errors": fetch_errors,
        "prop_settle_telemetry": prop_telemetry,
    }

    return combined_total


def get_last_auto_settler_summary() -> dict | None:
    return _LAST_AUTO_SETTLER_SUMMARY


async def scan_all_sides(sport: str = "basketball_nba", source: str = "unknown") -> dict:
    """
    Return ALL matched sides between Pinnacle and every target book with
    de-vigged true probabilities. Each side includes a sportsbook field.
    Unlike scan_for_ev, this doesn't filter to +EV only — the frontend
    applies promo-specific lens math.
    """
    data, resp = await fetch_odds(sport, source=source)
    events = data if isinstance(data, list) else []
    all_sides = []
    events_with_any_book = 0
    # Pregame-only filter: skip events that are started or starting imminently.
    # Small buffer avoids false edges from books updating out-of-sync near kickoff.
    pregame_cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)

    for event in events:
        home = event["home_team"]
        away = event["away_team"]
        commence = event.get("commence_time", "")
        if commence:
          try:
              # The Odds API returns ISO like "2026-03-19T01:30:00Z"
              commence_dt = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
              if commence_dt <= pregame_cutoff:
                  continue
          except Exception:
              # If commence_time is missing/invalid, keep the event rather than dropping silently.
              pass

        pin_outcomes = _extract_outcomes(event.get("bookmakers", []), SHARP_BOOK)
        if not pin_outcomes:
            continue

        pin_home = pin_outcomes.get(home)
        pin_away = pin_outcomes.get(away)
        if None in (pin_home, pin_away):
            continue
        draw_key = _find_draw_key(pin_outcomes, home, away)
        if draw_key:
            true_probs_n = devig_outcomes({home: pin_home, away: pin_away, draw_key: pin_outcomes[draw_key]})
            if not true_probs_n:
                continue
            true_probs = {"team_a": true_probs_n[home], "team_b": true_probs_n[away]}
            true_prob_draw = true_probs_n[draw_key]
        else:
            true_probs = devig_pinnacle(pin_home, pin_away)
            true_prob_draw = None
        had_any_book = False

        for book_key, book_display in TARGET_BOOKS.items():
            book_market = _extract_h2h_bookmaker_market(event.get("bookmakers", []), book_key)
            if not book_market:
                continue
            book_outcomes = book_market["outcomes"]

            book_home = book_outcomes.get(home)
            book_away = book_outcomes.get(away)
            if None in (book_home, book_away):
                continue

            had_any_book = True

            home_edge = calculate_edge(true_probs["team_a"], book_home)
            away_edge = calculate_edge(true_probs["team_b"], book_away)
            home_link, home_link_level = resolve_sportsbook_deeplink(
                sportsbook=book_display,
                selection_link=book_market["selection_links"].get(home),
                market_link=book_market["market_link"],
                event_link=book_market["event_link"],
            )
            away_link, away_link_level = resolve_sportsbook_deeplink(
                sportsbook=book_display,
                selection_link=book_market["selection_links"].get(away),
                market_link=book_market["market_link"],
                event_link=book_market["event_link"],
            )

            all_sides.append({
                "event_id": event.get("id"),
                "sportsbook": book_display,
                "sportsbook_deeplink_url": home_link,
                "sportsbook_deeplink_level": home_link_level,
                "sport": event.get("sport_key", sport),
                "event": f"{away} @ {home}",
                "commence_time": commence,
                "team": home,
                "pinnacle_odds": pin_home,
                "book_odds": book_home,
                "true_prob": home_edge["true_prob"],
                "base_kelly_fraction": round(kelly_fraction(home_edge["true_prob"], home_edge["book_decimal"]), 6),
                "book_decimal": home_edge["book_decimal"],
                "ev_percentage": home_edge["ev_percentage"],
            })

            all_sides.append({
                "event_id": event.get("id"),
                "sportsbook": book_display,
                "sportsbook_deeplink_url": away_link,
                "sportsbook_deeplink_level": away_link_level,
                "sport": event.get("sport_key", sport),
                "event": f"{away} @ {home}",
                "commence_time": commence,
                "team": away,
                "pinnacle_odds": pin_away,
                "book_odds": book_away,
                "true_prob": away_edge["true_prob"],
                "base_kelly_fraction": round(kelly_fraction(away_edge["true_prob"], away_edge["book_decimal"]), 6),
                "book_decimal": away_edge["book_decimal"],
                "ev_percentage": away_edge["ev_percentage"],
            })

            if true_prob_draw is not None:
                book_draw_key = _find_draw_key(book_outcomes, home, away)
                if book_draw_key and book_draw_key in book_outcomes:
                    draw_edge = calculate_edge(true_prob_draw, book_outcomes[book_draw_key])
                    draw_link, draw_link_level = resolve_sportsbook_deeplink(
                        sportsbook=book_display,
                        selection_link=book_market["selection_links"].get(book_draw_key),
                        market_link=book_market["market_link"],
                        event_link=book_market["event_link"],
                    )
                    all_sides.append({
                        "event_id": event.get("id"),
                        "sportsbook": book_display,
                        "sportsbook_deeplink_url": draw_link,
                        "sportsbook_deeplink_level": draw_link_level,
                        "sport": event.get("sport_key", sport),
                        "event": f"{away} @ {home}",
                        "commence_time": commence,
                        "team": book_draw_key,
                        "pinnacle_odds": pin_outcomes[draw_key],
                        "book_odds": book_outcomes[book_draw_key],
                        "true_prob": draw_edge["true_prob"],
                        "base_kelly_fraction": round(kelly_fraction(draw_edge["true_prob"], draw_edge["book_decimal"]), 6),
                        "book_decimal": draw_edge["book_decimal"],
                        "ev_percentage": draw_edge["ev_percentage"],
                    })

        if had_any_book:
            events_with_any_book += 1

    remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")

    return {
        "sides": all_sides,
        "events_fetched": len(events),
        "events_with_both_books": events_with_any_book,
        "api_requests_remaining": remaining,
    }
