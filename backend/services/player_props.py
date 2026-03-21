import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx

from calculations import american_to_decimal, kelly_fraction
from services.odds_api import (
    CACHE_TTL_SECONDS,
    ODDS_API_BASE,
    ODDS_API_KEY,
    SHARP_BOOK,
    TARGET_BOOKS,
    _append_odds_api_activity,
)
from services.shared_state import get_scan_cache, set_scan_cache


PLAYER_PROPS_SURFACE = "player_props"
PLAYER_PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
]

_props_cache: dict[str, dict] = {}
_props_locks: dict[str, asyncio.Lock] = {}


def _prop_cache_slot(sport: str) -> str:
    return f"{PLAYER_PROPS_SURFACE}:{sport}"


def _build_selection_key(*, event_id: str | None, market_key: str, player_name: str, side: str, line_value: float | None) -> str:
    line_token = "" if line_value is None else f":{line_value}"
    return "|".join(
        [
            str(event_id or "").strip().lower(),
            market_key.strip().lower(),
            player_name.strip().lower(),
            side.strip().lower(),
        ]
    ) + line_token


def _player_team_from_description(description: str | None) -> str | None:
    if not description:
        return None
    raw = str(description)
    if "(" in raw:
        prefix = raw.split("(")[-1].replace(")", "").strip()
        return prefix or None
    return None


def _normalize_prop_outcomes(outcomes: list[dict]) -> list[dict]:
    normalized: dict[tuple[str, float | None], dict[str, dict]] = {}
    for outcome in outcomes:
        name = str(outcome.get("name") or "").strip()
        if name.lower() not in {"over", "under"}:
            continue
        line_value = outcome.get("point")
        try:
            line_numeric = float(line_value) if line_value is not None else None
        except Exception:
            line_numeric = None
        description = str(outcome.get("description") or "").strip()
        player_name = description.split("(")[0].strip() if description else ""
        if not player_name:
            continue
        normalized.setdefault((player_name, line_numeric), {})[name.lower()] = outcome
    flattened: list[dict] = []
    for (_player_name, _line), pair in normalized.items():
        if "over" in pair and "under" in pair:
            flattened.extend([pair["over"], pair["under"]])
    return flattened


async def _fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str) -> tuple[dict, httpx.Response]:
    if not ODDS_API_KEY:
        raise ValueError("ODDS_API_KEY not set in environment")

    all_books = ",".join([SHARP_BOOK] + list(TARGET_BOOKS.keys()))
    url = f"{ODDS_API_BASE}/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,us2",
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "bookmakers": all_books,
    }

    started = time.monotonic()
    endpoint = f"/sports/{sport}/events/{event_id}/odds"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            duration_ms = (time.monotonic() - started) * 1000
            remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")
            _append_odds_api_activity(
                source=source,
                endpoint=endpoint,
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
            endpoint=endpoint,
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


def _extract_market(bookmakers: list[dict], book_key: str, market_key: str) -> tuple[list[dict] | None, str | None]:
    for bookmaker in bookmakers:
        if bookmaker.get("key") != book_key:
            continue
        deep_link = bookmaker.get("link") or bookmaker.get("url")
        for market in bookmaker.get("markets", []):
            if market.get("key") == market_key:
                return market.get("outcomes") or [], deep_link
    return None, None


def _parse_prop_sides(*, sport: str, event_payload: dict, target_markets: list[str]) -> list[dict]:
    bookmakers = event_payload.get("bookmakers") or []
    home = str(event_payload.get("home_team") or "")
    away = str(event_payload.get("away_team") or "")
    event_id = event_payload.get("id")
    commence_time = str(event_payload.get("commence_time") or "")
    event_name = f"{away} @ {home}".strip()
    sides: list[dict] = []

    for market_key in target_markets:
        sharp_outcomes, _ = _extract_market(bookmakers, SHARP_BOOK, market_key)
        if not sharp_outcomes:
            continue
        sharp_pair = _normalize_prop_outcomes(sharp_outcomes)
        if not sharp_pair:
            continue
        sharp_index: dict[tuple[str, float | None, str], dict] = {}
        for outcome in sharp_pair:
            player_name = str(outcome.get("description") or "").split("(")[0].strip()
            side = str(outcome.get("name") or "").strip().lower()
            point = outcome.get("point")
            try:
                line_value = float(point) if point is not None else None
            except Exception:
                line_value = None
            sharp_index[(player_name, line_value, side)] = outcome

        for book_key, book_display in TARGET_BOOKS.items():
            book_outcomes, deeplink = _extract_market(bookmakers, book_key, market_key)
            if not book_outcomes:
                continue
            normalized_book = _normalize_prop_outcomes(book_outcomes)
            if not normalized_book:
                continue
            for outcome in normalized_book:
                player_name = str(outcome.get("description") or "").split("(")[0].strip()
                side = str(outcome.get("name") or "").strip().lower()
                point = outcome.get("point")
                try:
                    line_value = float(point) if point is not None else None
                except Exception:
                    line_value = None
                opposite_side = "under" if side == "over" else "over"
                sharp_this = sharp_index.get((player_name, line_value, side))
                sharp_other = sharp_index.get((player_name, line_value, opposite_side))
                if not sharp_this or not sharp_other:
                    continue
                try:
                    sharp_this_decimal = american_to_decimal(float(sharp_this["price"]))
                    sharp_other_decimal = american_to_decimal(float(sharp_other["price"]))
                except Exception:
                    continue
                implied_total = (1 / sharp_this_decimal) + (1 / sharp_other_decimal)
                if implied_total <= 0:
                    continue
                true_prob = (1 / sharp_this_decimal) / implied_total
                book_odds = float(outcome["price"])
                book_decimal = american_to_decimal(book_odds)
                ev_percentage = round((true_prob * book_decimal - 1) * 100, 2)
                selection_key = _build_selection_key(
                    event_id=str(event_id or ""),
                    market_key=market_key,
                    player_name=player_name,
                    side=side,
                    line_value=line_value,
                )
                display_name = f"{player_name} {side.title()} {line_value:g}" if line_value is not None else f"{player_name} {side.title()}"
                sides.append(
                    {
                        "surface": PLAYER_PROPS_SURFACE,
                        "event_id": event_id,
                        "market_key": market_key,
                        "selection_key": selection_key,
                        "sportsbook": book_display,
                        "sportsbook_deeplink_url": deeplink,
                        "sport": sport,
                        "event": event_name,
                        "commence_time": commence_time,
                        "market": market_key,
                        "player_name": player_name,
                        "participant_id": None,
                        "team": _player_team_from_description(outcome.get("description")),
                        "opponent": away if _player_team_from_description(outcome.get("description")) == home else home,
                        "selection_side": side,
                        "line_value": line_value,
                        "display_name": display_name,
                        "pinnacle_odds": float(sharp_this["price"]),
                        "book_odds": book_odds,
                        "true_prob": round(true_prob, 4),
                        "base_kelly_fraction": round(kelly_fraction(true_prob, book_decimal), 6),
                        "book_decimal": round(book_decimal, 4),
                        "ev_percentage": ev_percentage,
                    }
                )
    sides.sort(key=lambda side: side["ev_percentage"], reverse=True)
    return sides


async def scan_player_props(sport: str, source: str = "manual_scan") -> dict:
    from services.odds_api import fetch_odds

    schedule_payload, _ = await fetch_odds(sport, source=f"{source}_props_schedule")
    events = schedule_payload if isinstance(schedule_payload, list) else []
    pregame_cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)

    all_sides: list[dict] = []
    events_with_any_book = 0
    remaining: str | None = None
    for event in events:
        commence = str(event.get("commence_time") or "")
        if commence:
            try:
                commence_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if commence_dt <= pregame_cutoff:
                    continue
            except Exception:
                pass
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            event_payload, resp = await _fetch_prop_market_for_event(
                sport=sport,
                event_id=event_id,
                markets=PLAYER_PROP_MARKETS,
                source=source,
            )
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                continue
            raise
        event_sides = _parse_prop_sides(sport=sport, event_payload=event_payload, target_markets=PLAYER_PROP_MARKETS)
        if event_sides:
            events_with_any_book += 1
            all_sides.extend(event_sides)
        remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining") or remaining

    return {
        "surface": PLAYER_PROPS_SURFACE,
        "sides": all_sides,
        "events_fetched": len(events),
        "events_with_both_books": events_with_any_book,
        "api_requests_remaining": remaining,
    }


async def get_cached_or_scan_player_props(sport: str, source: str = "unknown") -> dict:
    slot = _prop_cache_slot(sport)
    if sport not in _props_locks:
        _props_locks[sport] = asyncio.Lock()
    async with _props_locks[sport]:
        now = time.time()
        shared_entry = get_scan_cache(slot)
        if isinstance(shared_entry, dict):
            fetched_at = shared_entry.get("fetched_at")
            if isinstance(fetched_at, (int, float)) and (now - fetched_at) < CACHE_TTL_SECONDS:
                _props_cache[slot] = shared_entry
                return shared_entry

        if slot in _props_cache:
            entry = _props_cache[slot]
            if (now - entry["fetched_at"]) < CACHE_TTL_SECONDS:
                return entry

        result = await scan_player_props(sport, source=source)
        result["fetched_at"] = now
        _props_cache[slot] = result
        set_scan_cache(slot, result, CACHE_TTL_SECONDS)
        return result
