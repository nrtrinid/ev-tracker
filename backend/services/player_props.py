import asyncio
import logging
import os
import time
from statistics import median
from datetime import datetime, timedelta, timezone

import httpx

from calculations import american_to_decimal, decimal_to_american, kelly_fraction
from services.espn_scoreboard import (
    build_matchup_player_lookup,
    extract_national_tv_matchups,
    fetch_nba_scoreboard_window,
)
from services.odds_api import (
    CACHE_TTL_SECONDS,
    ODDS_API_BASE,
    ODDS_API_KEY,
    _append_odds_api_activity,
    fetch_events,
)
from services.shared_state import get_scan_cache, set_scan_cache


PLAYER_PROPS_SURFACE = "player_props"
PLAYER_PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
]
PLAYER_PROP_BOOKS = {
    "bovada": "Bovada",
    "betonlineag": "BetOnline.ag",
    "draftkings": "DraftKings",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "fanduel": "FanDuel",
}
PLAYER_PROP_REFERENCE_SOURCE = "market_median"
PLAYER_PROP_MIN_SOLID_REFERENCE_BOOKMAKERS = 2
PLAYER_PROP_MIN_REFERENCE_BOOKMAKERS_ENV = "PLAYER_PROP_MIN_REFERENCE_BOOKMAKERS"

_props_cache: dict[str, dict] = {}
_props_locks: dict[str, asyncio.Lock] = {}
logger = logging.getLogger("ev_tracker")


def get_player_prop_markets() -> list[str]:
    raw = os.getenv("PLAYER_PROP_MARKETS", "").strip()
    if not raw:
        return PLAYER_PROP_MARKETS

    requested = [item.strip() for item in raw.split(",") if item.strip()]
    allowed = {market: market for market in PLAYER_PROP_MARKETS}
    selected = [allowed[item] for item in requested if item in allowed]
    return selected or PLAYER_PROP_MARKETS


def get_player_prop_min_reference_bookmakers() -> int:
    raw = os.getenv(PLAYER_PROP_MIN_REFERENCE_BOOKMAKERS_ENV, "").strip()
    if not raw:
        return PLAYER_PROP_MIN_SOLID_REFERENCE_BOOKMAKERS

    try:
        parsed = int(raw)
    except ValueError:
        return PLAYER_PROP_MIN_SOLID_REFERENCE_BOOKMAKERS

    max_reference_books = max(1, len(PLAYER_PROP_BOOKS) - 1)
    return max(1, min(parsed, max_reference_books))


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


def _canonical_team_name(name: str | None) -> str:
    if not name:
        return ""
    lowered = str(name).strip().lower().replace("los angeles", "la")
    return "".join(ch for ch in lowered if ch.isalnum())


def _canonical_player_name(name: str | None) -> str:
    if not name:
        return ""
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum())


def _extract_player_name(description: str | None) -> str:
    return str(description or "").split("(")[0].strip()


def _to_line_numeric(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except Exception:
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

    all_books = ",".join(PLAYER_PROP_BOOKS.keys())
    url = f"{ODDS_API_BASE}/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
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


def _devig_pair_probabilities(over_outcome: dict, under_outcome: dict) -> dict[str, float] | None:
    try:
        over_decimal = american_to_decimal(float(over_outcome["price"]))
        under_decimal = american_to_decimal(float(under_outcome["price"]))
    except Exception:
        return None

    implied_over = 1 / over_decimal
    implied_under = 1 / under_decimal
    implied_total = implied_over + implied_under
    if implied_total <= 0:
        return None

    return {
        "over": implied_over / implied_total,
        "under": implied_under / implied_total,
    }


def _reference_american_from_true_prob(true_prob: float) -> int | None:
    if true_prob <= 0 or true_prob >= 1:
        return None
    fair_decimal = 1 / true_prob
    if fair_decimal <= 1:
        return None
    return decimal_to_american(fair_decimal)


def _normalize_player_team(token: str | None, *, home_team: str, away_team: str) -> str | None:
    token_key = _canonical_team_name(token)
    if not token_key:
        return None

    for team_name in (home_team, away_team):
        team_key = _canonical_team_name(team_name)
        if token_key == team_key or token_key in team_key or team_key in token_key:
            return team_name
    return None


def _resolve_player_context(
    *,
    player_name: str,
    description: str | None,
    player_context_lookup: dict[str, dict[str, str | None]] | None,
    home_team: str,
    away_team: str,
) -> tuple[str | None, str | None]:
    explicit_team = _normalize_player_team(
        _player_team_from_description(description),
        home_team=home_team,
        away_team=away_team,
    )
    player_context = (player_context_lookup or {}).get(_canonical_player_name(player_name)) or {}
    inferred_team = _normalize_player_team(
        player_context.get("team"),
        home_team=home_team,
        away_team=away_team,
    )
    participant_id = player_context.get("participant_id")
    return explicit_team or inferred_team, participant_id


def _confidence_label_for_reference_count(reference_count: int) -> str:
    if reference_count >= 4:
        return "elite"
    if reference_count >= 3:
        return "high"
    if reference_count >= PLAYER_PROP_MIN_SOLID_REFERENCE_BOOKMAKERS:
        return "solid"
    return "thin"


def _match_curated_events(national_tv_games: list[dict], odds_events: list[dict]) -> list[dict]:
    return [
        detail["odds_event"]
        for detail in _build_curated_event_match_details(national_tv_games, odds_events)
        if isinstance(detail.get("odds_event"), dict)
    ]


def _build_curated_event_match_details(curated_games: list[dict], odds_events: list[dict]) -> list[dict]:
    odds_index: dict[tuple[str, str], dict] = {}
    for event in odds_events:
        home_team = str(event.get("home_team") or "").strip()
        away_team = str(event.get("away_team") or "").strip()
        key = (_canonical_team_name(away_team), _canonical_team_name(home_team))
        if all(key) and key not in odds_index:
            odds_index[key] = event

    details: list[dict] = []
    for game in curated_games:
        key = (str(game.get("away_team_key") or ""), str(game.get("home_team_key") or ""))
        event = odds_index.get(key)
        details.append(
            {
                "scoreboard_event_id": str(game.get("event_id") or "").strip() or None,
                "away_team": str(game.get("away_team") or "").strip(),
                "away_team_id": str(game.get("away_team_id") or "").strip() or None,
                "home_team": str(game.get("home_team") or "").strip(),
                "home_team_id": str(game.get("home_team_id") or "").strip() or None,
                "selection_reason": str(game.get("selection_reason") or "unknown"),
                "broadcasts": [str(item) for item in (game.get("broadcasts") or []) if item],
                "matched": bool(event),
                "odds_event_id": str(event.get("id") or "").strip() or None if event else None,
                "commence_time": str(event.get("commence_time") or "").strip() or None if event else None,
                "odds_event": event,
            }
        )
    return details


def _build_prop_side_candidates(
    *,
    sport: str,
    event_payload: dict,
    target_markets: list[str],
    player_context_lookup: dict[str, dict[str, str | None]] | None = None,
) -> list[dict]:
    bookmakers = event_payload.get("bookmakers") or []
    home = str(event_payload.get("home_team") or "")
    away = str(event_payload.get("away_team") or "")
    event_id = event_payload.get("id")
    commence_time = str(event_payload.get("commence_time") or "")
    event_name = f"{away} @ {home}".strip()
    candidates: list[dict] = []

    for market_key in target_markets:
        selection_pairs_by_book: dict[str, dict[tuple[str, float | None], dict[str, dict]]] = {}
        deeplink_by_book: dict[str, str | None] = {}

        for book_key in PLAYER_PROP_BOOKS.keys():
            book_outcomes, deeplink = _extract_market(bookmakers, book_key, market_key)
            if not book_outcomes:
                continue
            normalized_book = _normalize_prop_outcomes(book_outcomes)
            if not normalized_book:
                continue

            selections: dict[tuple[str, float | None], dict[str, dict]] = {}
            for outcome in normalized_book:
                player_name = _extract_player_name(outcome.get("description"))
                if not player_name:
                    continue
                line_value = _to_line_numeric(outcome.get("point"))
                side = str(outcome.get("name") or "").strip().lower()
                selections.setdefault((player_name, line_value), {})[side] = outcome

            valid_selections = {
                key: pair for key, pair in selections.items()
                if "over" in pair and "under" in pair
            }
            if not valid_selections:
                continue

            selection_pairs_by_book[book_key] = valid_selections
            deeplink_by_book[book_key] = deeplink

        for book_key, book_display in PLAYER_PROP_BOOKS.items():
            book_pairs = selection_pairs_by_book.get(book_key)
            if not book_pairs:
                continue
            deeplink = deeplink_by_book.get(book_key)

            for (player_name, line_value), book_pair in book_pairs.items():
                for side in ("over", "under"):
                    outcome = book_pair.get(side)
                    if not outcome:
                        continue

                    reference_probs: list[float] = []
                    reference_bookmakers: list[str] = []
                    for reference_book_key, reference_pairs in selection_pairs_by_book.items():
                        if reference_book_key == book_key:
                            continue
                        reference_pair = reference_pairs.get((player_name, line_value))
                        if not reference_pair:
                            continue
                        true_probs = _devig_pair_probabilities(reference_pair["over"], reference_pair["under"])
                        if not true_probs:
                            continue
                        reference_probs.append(true_probs[side])
                        reference_bookmakers.append(reference_book_key)

                    if not reference_probs:
                        continue

                    reference_count = len(reference_bookmakers)
                    true_prob = float(median(reference_probs))
                    reference_odds = _reference_american_from_true_prob(true_prob)
                    if reference_odds is None:
                        continue

                    try:
                        book_odds = float(outcome["price"])
                    except Exception:
                        continue

                    book_decimal = american_to_decimal(book_odds)
                    ev_percentage = round((true_prob * book_decimal - 1) * 100, 2)
                    selection_key = _build_selection_key(
                        event_id=str(event_id or ""),
                        market_key=market_key,
                        player_name=player_name,
                        side=side,
                        line_value=line_value,
                    )
                    display_name = (
                        f"{player_name} {side.title()} {line_value:g}"
                        if line_value is not None
                        else f"{player_name} {side.title()}"
                    )
                    player_team, participant_id = _resolve_player_context(
                        player_name=player_name,
                        description=outcome.get("description"),
                        player_context_lookup=player_context_lookup,
                        home_team=home,
                        away_team=away,
                    )
                    opponent = None
                    if player_team == home:
                        opponent = away
                    elif player_team == away:
                        opponent = home
                    candidates.append(
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
                            "participant_id": participant_id,
                            "team": player_team,
                            "opponent": opponent,
                            "selection_side": side,
                            "line_value": line_value,
                            "display_name": display_name,
                            "reference_odds": float(reference_odds),
                            "reference_source": PLAYER_PROP_REFERENCE_SOURCE,
                            "reference_bookmakers": reference_bookmakers,
                            "reference_bookmaker_count": reference_count,
                            "confidence_label": _confidence_label_for_reference_count(reference_count),
                            "book_odds": book_odds,
                            "true_prob": round(true_prob, 4),
                            "base_kelly_fraction": round(kelly_fraction(true_prob, book_decimal), 6),
                            "book_decimal": round(book_decimal, 4),
                            "ev_percentage": ev_percentage,
                        }
                    )
    return candidates


def _apply_reference_quality_gate(
    candidates: list[dict],
    *,
    min_reference_bookmakers: int,
) -> list[dict]:
    filtered = [
        side for side in candidates
        if int(side.get("reference_bookmaker_count") or 0) >= min_reference_bookmakers
    ]
    filtered.sort(
        key=lambda side: (
            side.get("reference_bookmaker_count", 0) >= PLAYER_PROP_MIN_SOLID_REFERENCE_BOOKMAKERS,
            side.get("reference_bookmaker_count", 0),
            side["ev_percentage"],
            side["true_prob"],
        ),
        reverse=True,
    )
    return filtered


def _parse_prop_sides(
    *,
    sport: str,
    event_payload: dict,
    target_markets: list[str],
    player_context_lookup: dict[str, dict[str, str | None]] | None = None,
    min_reference_bookmakers: int | None = None,
) -> list[dict]:
    candidates = _build_prop_side_candidates(
        sport=sport,
        event_payload=event_payload,
        target_markets=target_markets,
        player_context_lookup=player_context_lookup,
    )
    return _apply_reference_quality_gate(
        candidates,
        min_reference_bookmakers=min_reference_bookmakers or get_player_prop_min_reference_bookmakers(),
    )


async def scan_player_props(sport: str, source: str = "manual_scan") -> dict:
    target_markets = get_player_prop_markets()
    min_reference_bookmakers = get_player_prop_min_reference_bookmakers()
    scoreboard_payload = await fetch_nba_scoreboard_window()
    scoreboard_events = scoreboard_payload.get("events") if isinstance(scoreboard_payload, dict) else []
    scoreboard_count = len(scoreboard_events) if isinstance(scoreboard_events, list) else 0
    curated_games = extract_national_tv_matchups(scoreboard_payload, max_games=3)
    selection_reasons = [str(game.get("selection_reason") or "unknown") for game in curated_games]
    logger.info(
        "player_props.scan.scoreboard sport=%s source=%s scoreboard_events=%s curated_games=%s selection_reasons=%s",
        sport,
        source,
        scoreboard_count,
        len(curated_games),
        ",".join(selection_reasons) if selection_reasons else "none",
    )
    if not curated_games:
        logger.info(
            "player_props.scan.no_curated_games sport=%s source=%s reason=no_scoreboard_matchups",
            sport,
            source,
        )
        return {
            "surface": PLAYER_PROPS_SURFACE,
            "sides": [],
            "events_fetched": 0,
            "events_with_both_books": 0,
            "api_requests_remaining": None,
            "diagnostics": {
                "scan_mode": "curated_sniper",
                "scoreboard_event_count": scoreboard_count,
                "odds_event_count": 0,
                "curated_games": [],
                "matched_event_count": 0,
                "unmatched_game_count": 0,
                "events_fetched": 0,
                "events_skipped_pregame": 0,
                "events_with_results": 0,
                "candidate_sides_count": 0,
                "quality_gate_filtered_count": 0,
                "quality_gate_min_reference_bookmakers": min_reference_bookmakers,
                "sides_count": 0,
                "markets_requested": target_markets,
            },
        }

    events_payload, events_resp = await fetch_events(sport, source=f"{source}_props_events")
    events = events_payload if isinstance(events_payload, list) else []
    match_details = _build_curated_event_match_details(curated_games, events)
    matched_events = [
        detail["odds_event"]
        for detail in match_details
        if isinstance(detail.get("odds_event"), dict)
    ]
    match_details_by_event_id = {
        str(detail.get("odds_event_id") or ""): detail
        for detail in match_details
        if detail.get("odds_event_id")
    }
    logger.info(
        "player_props.scan.matched_events sport=%s source=%s odds_events=%s matched_events=%s",
        sport,
        source,
        len(events),
        len(matched_events),
    )
    pregame_cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)

    all_sides: list[dict] = []
    events_with_any_book = 0
    remaining: str | None = events_resp.headers.get("x-requests-remaining") or events_resp.headers.get("x-request-remaining")
    events_fetched = 0
    skipped_pregame = 0
    candidate_sides_count = 0
    quality_gate_filtered_count = 0
    for event in matched_events:
        commence = str(event.get("commence_time") or "")
        if commence:
            try:
                commence_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if commence_dt <= pregame_cutoff:
                    skipped_pregame += 1
                    continue
            except Exception:
                pass
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            events_fetched += 1
            event_payload, resp = await _fetch_prop_market_for_event(
                sport=sport,
                event_id=event_id,
                markets=target_markets,
                source=source,
            )
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                continue
            raise
        match_detail = match_details_by_event_id.get(event_id) or {}
        player_context_lookup: dict[str, dict[str, str | None]] = {}
        try:
            player_context_lookup = await build_matchup_player_lookup(
                home_team_id=match_detail.get("home_team_id"),
                home_team_name=match_detail.get("home_team"),
                away_team_id=match_detail.get("away_team_id"),
                away_team_name=match_detail.get("away_team"),
            )
        except Exception:
            player_context_lookup = {}
        event_candidates = _build_prop_side_candidates(
            sport=sport,
            event_payload=event_payload,
            target_markets=target_markets,
            player_context_lookup=player_context_lookup,
        )
        candidate_sides_count += len(event_candidates)
        event_sides = _apply_reference_quality_gate(
            event_candidates,
            min_reference_bookmakers=min_reference_bookmakers,
        )
        quality_gate_filtered_count += max(0, len(event_candidates) - len(event_sides))
        if event_sides:
            events_with_any_book += 1
            all_sides.extend(event_sides)
        remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining") or remaining

    logger.info(
        "player_props.scan.completed sport=%s source=%s matched_events=%s events_fetched=%s events_with_results=%s candidate_sides=%s quality_gate_filtered=%s min_reference_books=%s sides=%s skipped_pregame=%s api_requests_remaining=%s",
        sport,
        source,
        len(matched_events),
        events_fetched,
        events_with_any_book,
        candidate_sides_count,
        quality_gate_filtered_count,
        min_reference_bookmakers,
        len(all_sides),
        skipped_pregame,
        remaining,
    )

    diagnostics = {
        "scan_mode": "curated_sniper",
        "scoreboard_event_count": scoreboard_count,
        "odds_event_count": len(events),
        "curated_games": [
            {
                "event_id": detail.get("scoreboard_event_id"),
                "away_team": detail.get("away_team") or "",
                "home_team": detail.get("home_team") or "",
                "selection_reason": detail.get("selection_reason") or "unknown",
                "broadcasts": detail.get("broadcasts") or [],
                "odds_event_id": detail.get("odds_event_id"),
                "commence_time": detail.get("commence_time"),
                "matched": bool(detail.get("matched")),
            }
            for detail in match_details
        ],
        "matched_event_count": len(matched_events),
        "unmatched_game_count": sum(1 for detail in match_details if not detail.get("matched")),
        "events_fetched": events_fetched,
        "events_skipped_pregame": skipped_pregame,
        "events_with_results": events_with_any_book,
        "candidate_sides_count": candidate_sides_count,
        "quality_gate_filtered_count": quality_gate_filtered_count,
        "quality_gate_min_reference_bookmakers": min_reference_bookmakers,
        "sides_count": len(all_sides),
        "markets_requested": target_markets,
    }

    return {
        "surface": PLAYER_PROPS_SURFACE,
        "sides": all_sides,
        "events_fetched": events_fetched,
        "events_with_both_books": events_with_any_book,
        "api_requests_remaining": remaining,
        "diagnostics": diagnostics,
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
