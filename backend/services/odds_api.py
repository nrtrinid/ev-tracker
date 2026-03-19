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
from dotenv import load_dotenv
from calculations import american_to_decimal, kelly_fraction
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _short_error_message(message: str | None) -> str | None:
    if not message:
        return None
    cleaned = str(message).strip().replace("\n", " ")
    return cleaned[:180]


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
        "error_type": error_type,
        "error_message": _short_error_message(error_message),
        "_ts_epoch": now.timestamp(),
    }
    with _ODDS_ACTIVITY_LOCK:
        _ODDS_ACTIVITY_EVENTS.append(event)


def _sanitize_activity_event(event: dict) -> dict:
    return {
        "timestamp": event.get("timestamp"),
        "source": event.get("source"),
        "endpoint": event.get("endpoint"),
        "sport": event.get("sport"),
        "cache_hit": bool(event.get("cache_hit")),
        "outbound_call_made": bool(event.get("outbound_call_made")),
        "status_code": event.get("status_code"),
        "duration_ms": event.get("duration_ms"),
        "api_requests_remaining": event.get("api_requests_remaining"),
        "error_type": event.get("error_type"),
        "error_message": event.get("error_message"),
    }


def get_odds_api_activity_snapshot() -> dict:
    now_epoch = datetime.now(timezone.utc).timestamp()
    last_hour_cutoff = now_epoch - 3600

    with _ODDS_ACTIVITY_LOCK:
        events = list(_ODDS_ACTIVITY_EVENTS)

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

    recent_calls = [_sanitize_activity_event(e) for e in list(reversed(events[-_ODDS_ACTIVITY_MAX_RECENT:]))]

    return {
        "summary": {
            "calls_last_hour": len(last_hour_events),
            "errors_last_hour": len(errors_last_hour),
            "last_success_at": last_success,
            "last_error_at": last_error,
        },
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
                return shared_entry

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
                return entry

        result = await scan_all_sides(sport, source=source)
        result["fetched_at"] = now
        _cache[sport] = result
        set_scan_cache(sport, result, CACHE_TTL_SECONDS)
        return result


SUPPORTED_SPORTS = [
    "basketball_nba",
    "basketball_ncaab",
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
) -> tuple[list[dict], httpx.Response]:
    """
    Hit The Odds API and return raw event data with odds
    from Pinnacle and all target books.
    """
    if not ODDS_API_KEY:
        raise ValueError("ODDS_API_KEY not set in environment")

    all_books = ",".join([SHARP_BOOK] + list(TARGET_BOOKS.keys()))
    url = f"{ODDS_API_BASE}/sports/{sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,us2",
        "markets": "h2h",
        "oddsFormat": "american",
        "bookmakers": all_books,
    }

    started = time.monotonic()
    endpoint_value = endpoint or f"/sports/{sport}/odds"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            duration_ms = (time.monotonic() - started) * 1000
            remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")
            _append_odds_api_activity(
                source=source,
                endpoint=endpoint_value,
                sport=sport,
                cache_hit=False,
                outbound_call_made=True,
                status_code=resp.status_code,
                duration_ms=duration_ms,
                api_requests_remaining=remaining,
                error_type=None,
                error_message=None,
            )
            return resp.json(), resp
    except httpx.HTTPStatusError as e:
        duration_ms = (time.monotonic() - started) * 1000
        status_code = e.response.status_code if e.response is not None else None
        remaining = None
        if e.response is not None:
            remaining = e.response.headers.get("x-requests-remaining") or e.response.headers.get("x-request-remaining")
        _append_odds_api_activity(
            source=source,
            endpoint=endpoint_value,
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=status_code,
            duration_ms=duration_ms,
            api_requests_remaining=remaining,
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
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise


def _extract_outcomes(bookmakers: list[dict], book_key: str) -> dict | None:
    """Pull the h2h outcomes dict for a given bookmaker from the event data."""
    for bm in bookmakers:
        if bm["key"] == book_key:
            for market in bm.get("markets", []):
                if market["key"] == "h2h":
                    return {o["name"]: o["price"] for o in market["outcomes"]}
    return None


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
            book_outcomes = _extract_outcomes(event.get("bookmakers", []), book_key)
            if not book_outcomes:
                continue

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
    Layer 2 — Piggyback CLV update. Zero extra API calls.

    After any scan returns, this is called synchronously before responding.
    It builds a lookup of (commence_time, team) → pinnacle_odds from the fresh
    scan data, then finds every pending bet with CLV tracking enabled and writes
    the latest Pinnacle line to pinnacle_odds_at_close.

    Args:
        sides: The `sides` list from scan_all_sides / get_cached_or_scan.
        db:    Supabase client (service role).

    Returns:
        Number of bet rows updated.
    """
    from datetime import datetime, timezone

    if not sides:
        return 0

    # Build a fast lookup: (commence_time, team) -> pinnacle_odds
    snapshot: dict[tuple[str, str], float] = {}
    for side in sides:
        ct = side.get("commence_time", "")
        team = side.get("team", "")
        if ct and team:
            snapshot[(ct, team)] = side["pinnacle_odds"]

    if not snapshot:
        return 0

    # Fetch all pending bets that have CLV tracking data
    result = (
        db.table("bets")
        .select("id,clv_team,commence_time")
        .eq("result", "pending")
        .not_.is_("clv_team", "null")
        .execute()
    )

    if not result.data:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    updated = 0

    for bet in result.data:
        team = bet.get("clv_team")
        ct = bet.get("commence_time")
        if not team or not ct:
            continue

        pinnacle_close = snapshot.get((ct, team))
        if pinnacle_close is None:
            continue

        db.table("bets").update({
            "pinnacle_odds_at_close": pinnacle_close,
            "clv_updated_at": now,
        }).eq("id", bet["id"]).execute()
        updated += 1

    return updated


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

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(minutes=20)
    now_iso = now.isoformat()
    window_end_iso = window_end.isoformat()

    result = (
        db.table("bets")
        .select("id,clv_sport_key,clv_team,commence_time")
        .eq("result", "pending")
        .is_("pinnacle_odds_at_close", "null")
        .not_.is_("clv_sport_key", "null")
        .gt("commence_time", now_iso)
        .lte("commence_time", window_end_iso)
        .execute()
    )

    if not result.data:
        return 0

    sport_bets: dict[str, list[dict]] = {}
    for bet in result.data:
        sk = bet.get("clv_sport_key")
        if sk:
            sport_bets.setdefault(sk, []).append(bet)

    total_updated = 0
    settled_at = datetime.now(timezone.utc).isoformat()

    for sport_key, bets in sport_bets.items():
        try:
            data, _ = await fetch_odds(sport_key, source="jit_clv")
            events = data if isinstance(data, list) else []

            snapshot: dict[tuple[str, str], float] = {}
            for event in events:
                home = event["home_team"]
                away = event["away_team"]
                ct = event.get("commence_time", "")
                pin_outcomes = _extract_outcomes(event.get("bookmakers", []), SHARP_BOOK)
                if not pin_outcomes:
                    continue
                pin_home = pin_outcomes.get(home)
                pin_away = pin_outcomes.get(away)
                if pin_home:
                    snapshot[(ct, home)] = pin_home
                if pin_away:
                    snapshot[(ct, away)] = pin_away

            for bet in bets:
                key = (bet.get("commence_time", ""), bet.get("clv_team", ""))
                close_odds = snapshot.get(key)
                if close_odds is not None:
                    db.table("bets").update({
                        "pinnacle_odds_at_close": close_odds,
                        "clv_updated_at": settled_at,
                    }).eq("id", bet["id"]).execute()
                    total_updated += 1

        except Exception as e:
            print(f"[JIT CLV] Error processing sport '{sport_key}': {e}")

    return total_updated


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
            _append_odds_api_activity(
                source=source,
                endpoint=f"/sports/{sport}/scores",
                sport=sport,
                cache_hit=False,
                outbound_call_made=True,
                status_code=resp.status_code,
                duration_ms=duration_ms,
                api_requests_remaining=remaining,
                error_type=None,
                error_message=None,
            )
            data = resp.json()
            return data if isinstance(data, list) else []
    except httpx.HTTPStatusError as e:
        duration_ms = (time.monotonic() - started) * 1000
        status_code = e.response.status_code if e.response is not None else None
        remaining = None
        if e.response is not None:
            remaining = e.response.headers.get("x-requests-remaining") or e.response.headers.get("x-request-remaining")
        _append_odds_api_activity(
            source=source,
            endpoint=f"/sports/{sport}/scores",
            sport=sport,
            cache_hit=False,
            outbound_call_made=True,
            status_code=status_code,
            duration_ms=duration_ms,
            api_requests_remaining=remaining,
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


def _select_completed_event_for_bet(bet: dict, completed_events: list[dict]) -> tuple[dict | None, str]:
    """
    Deterministic settlement match to prevent accidental auto-grading.

    We only auto-grade when there is exactly one completed event matching:
    - exact commence_time equality
    - clv_team equals home_team or away_team (canonicalized)
    """
    clv_team = bet.get("clv_team")
    commence_time = bet.get("commence_time")
    if not clv_team:
        return None, "missing_clv_team"
    if not commence_time:
        return None, "missing_commence_time"

    target_team = _canonical_team_name(clv_team)
    candidates: list[dict] = []
    for event in completed_events:
        if event.get("commence_time") != commence_time:
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
    Auto-Settler — runs once daily at 4:00 AM UTC via APScheduler.

    Grades pending ML bets for games that have already started (commence_time
    in the past). Groups by sport_key, fetches scores once per sport (1 token),
    and updates result + settled_at for every completed game found.

    Non-ML markets (Spread, Total, SGP, Prop, Futures) are skipped — the schema
    does not store the bet line needed for algorithmic grading of those markets.
    Returns the number of bets settled.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    result = (
        db.table("bets")
        .select("id,market,clv_sport_key,clv_team,commence_time")
        .eq("result", "pending")
        .not_.is_("clv_sport_key", "null")
        .lt("commence_time", now_iso)
        .execute()
    )

    if not result.data:
        return 0

    sport_bets: dict[str, list[dict]] = {}
    for bet in result.data:
        sk = bet.get("clv_sport_key")
        if sk:
            sport_bets.setdefault(sk, []).append(bet)

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
            events = await fetch_scores(sport_key, source=source)

            completed_events = [event for event in events if event.get("completed")]
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

    global _LAST_AUTO_SETTLER_SUMMARY
    _LAST_AUTO_SETTLER_SUMMARY = {
        "captured_at": settled_at,
        "sports": sport_summaries,
        "total_settled": total_settled,
        "skipped_totals": aggregate_skipped,
    }

    return total_settled


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
            book_outcomes = _extract_outcomes(event.get("bookmakers", []), book_key)
            if not book_outcomes:
                continue

            book_home = book_outcomes.get(home)
            book_away = book_outcomes.get(away)
            if None in (book_home, book_away):
                continue

            had_any_book = True

            home_edge = calculate_edge(true_probs["team_a"], book_home)
            away_edge = calculate_edge(true_probs["team_b"], book_away)

            all_sides.append({
                "sportsbook": book_display,
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
                "sportsbook": book_display,
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
                    all_sides.append({
                        "sportsbook": book_display,
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
