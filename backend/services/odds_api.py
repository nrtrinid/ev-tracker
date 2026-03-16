"""
Odds API Service — Phase 2: The Odds Engine

Fetches live odds from The Odds API, de-vigs Pinnacle lines to derive
true probabilities, and compares them against DraftKings payouts to
surface +EV moneyline bets.
"""

import asyncio
import os
import time
import httpx
from dotenv import load_dotenv
from calculations import american_to_decimal, kelly_fraction

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Server-side TTL cache: 5 minutes. First request after expiry pays the API call; others share cache.
CACHE_TTL_SECONDS = 5 * 60

_cache: dict[str, dict] = {}
_locks: dict[str, asyncio.Lock] = {}


async def get_cached_or_scan(sport: str) -> dict:
    """
    Return sides for this sport from cache if fresh (< CACHE_TTL_SECONDS),
    else call scan_all_sides and cache. Thread-safe per sport.
    Returned dict has: sides, events_fetched, events_with_both_books, api_requests_remaining, fetched_at (float).
    """
    if sport not in _locks:
        _locks[sport] = asyncio.Lock()
    async with _locks[sport]:
        now = time.time()
        if sport in _cache:
            entry = _cache[sport]
            if (now - entry["fetched_at"]) < CACHE_TTL_SECONDS:
                return entry
        result = await scan_all_sides(sport)
        result["fetched_at"] = now
        _cache[sport] = result
        return result


SUPPORTED_SPORTS = [
    "basketball_nba",
    "basketball_ncaab",
    "football_nfl",
    "football_ncaaf",
    "baseball_mlb",
    "icehockey_nhl",
    "mma_mixed_martial_arts",
    "soccer_usa_mls",
    "tennis_atp_us_open",
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


async def fetch_odds(sport: str = "basketball_nba") -> tuple[list[dict], httpx.Response]:
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

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json(), resp


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
    data, resp = await fetch_odds(sport)
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

        true_probs = devig_pinnacle(pin_home, pin_away)
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
            data, _ = await fetch_odds(sport_key)
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

        except Exception:
            # Never let a single sport failure break the entire job
            pass

    return total_updated


async def scan_all_sides(sport: str = "basketball_nba") -> dict:
    """
    Return ALL matched sides between Pinnacle and every target book with
    de-vigged true probabilities. Each side includes a sportsbook field.
    Unlike scan_for_ev, this doesn't filter to +EV only — the frontend
    applies promo-specific lens math.
    """
    data, resp = await fetch_odds(sport)
    events = data if isinstance(data, list) else []
    all_sides = []
    events_with_any_book = 0

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

        true_probs = devig_pinnacle(pin_home, pin_away)
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

        if had_any_book:
            events_with_any_book += 1

    remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")

    return {
        "sides": all_sides,
        "events_fetched": len(events),
        "events_with_both_books": events_with_any_book,
        "api_requests_remaining": remaining,
    }
