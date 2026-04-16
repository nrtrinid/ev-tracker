import asyncio
import json
import logging
import math
import os
import time
from statistics import median
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from calculations import american_to_decimal, decimal_to_american, kelly_fraction
from services.player_prop_weights import get_player_prop_weight_overrides
from services.player_prop_markets import (
    PLAYER_PROP_ALL_MARKETS,
    get_player_prop_markets,
    get_supported_player_prop_sports,
)
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
    _parse_credits_used_last,
    fetch_events,
)
from services.sportsbook_deeplinks import resolve_sportsbook_deeplink
from services.shared_state import get_scan_cache, set_scan_cache
from services.team_aliases import canonical_short_name, canonical_team_token, build_short_event_label


PLAYER_PROPS_SURFACE = "player_props"
PLAYER_PROP_MARKETS = list(PLAYER_PROP_ALL_MARKETS)
PLAYER_PROP_BOOKS = {
    "bovada": "Bovada",
    "betonlineag": "BetOnline.ag",
    "draftkings": "DraftKings",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "fanduel": "FanDuel",
}
PLAYER_PROP_REFERENCE_SOURCE = "market_weighted_consensus"
PLAYER_PROP_V2_REFERENCE_SOURCE = "market_logit_consensus_v2"
PLAYER_PROP_MODEL_V1_LIVE = "props_v1_live"
PLAYER_PROP_MODEL_V2_LIVE = "props_v2_live"
PLAYER_PROP_MODEL_V2_SHADOW = "props_v2_shadow"
PLAYER_PROP_ACTIVE_MODEL_ENV = "PLAYER_PROP_ACTIVE_MODEL"
PLAYER_PROP_SHADOW_MODEL_ENV = "PLAYER_PROP_SHADOW_MODEL"
PLAYER_PROP_DEFAULT_STRAIGHT_MODEL = "straight_h2h_live"

# Trust weights for weighted consensus probability estimation.
# Higher weight = sharper / more trusted for true-probability anchoring.
# betonlineag: sharpest book in the set, high-trust probability anchor.
# bovada: decent line-setter, above pure follower level.
# All other books default to 1.0 (follower / recreational sportsbook).
PLAYER_PROP_REFERENCE_BOOK_WEIGHTS: dict[str, float] = {
    "betonlineag": 3.0,
    "bovada": 1.5,
}
PLAYER_PROP_YES_NO_MARKETS: set[str] = {
    "batter_home_runs",
}
# Default surfaced-prop trust gate:
# 3 reference books gives us enough market confirmation to avoid thin two-book
# consensus artifacts without starving the slate as aggressively as a 4-book gate.
PLAYER_PROP_MIN_SOLID_REFERENCE_BOOKMAKERS = 3
PLAYER_PROP_MIN_REFERENCE_BOOKMAKERS_ENV = "PLAYER_PROP_MIN_REFERENCE_BOOKMAKERS"
PLAYER_PROP_MIN_PICKEM_REFERENCE_BOOKMAKERS = 2
PLAYER_PROP_MIN_PICKEM_REFERENCE_BOOKMAKERS_ENV = "PLAYER_PROP_PICKEM_MIN_REFERENCE_BOOKMAKERS"
PLAYER_PROP_MIN_CLV_REFERENCE_BOOKMAKERS = 1
PLAYER_PROP_MIN_CLV_REFERENCE_BOOKMAKERS_ENV = "PLAYER_PROP_CLV_MIN_REFERENCE_BOOKMAKERS"
PLAYER_PROP_FALLBACK_MAX_EVENTS = 3
PLAYER_PROP_CACHE_VERSION = "v2"

_props_cache: dict[str, dict] = {}
_props_locks: dict[str, asyncio.Lock] = {}
logger = logging.getLogger("ev_tracker")


def get_player_prop_active_model_key() -> str:
    raw = str(os.getenv(PLAYER_PROP_ACTIVE_MODEL_ENV) or "").strip().lower()
    if raw in {PLAYER_PROP_MODEL_V1_LIVE, PLAYER_PROP_MODEL_V2_LIVE}:
        return raw
    return PLAYER_PROP_MODEL_V1_LIVE


def get_player_prop_shadow_model_key(active_model_key: str | None = None) -> str | None:
    normalized_active = (active_model_key or get_player_prop_active_model_key()).strip().lower()
    raw = str(os.getenv(PLAYER_PROP_SHADOW_MODEL_ENV) or "").strip().lower()
    if raw in {"", "off", "none", "disabled"}:
        return PLAYER_PROP_MODEL_V2_SHADOW if normalized_active == PLAYER_PROP_MODEL_V1_LIVE else None
    if raw == normalized_active:
        return None
    if raw == PLAYER_PROP_MODEL_V2_SHADOW:
        return raw
    return None


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


def get_player_prop_pickem_min_reference_bookmakers() -> int:
    raw = os.getenv(PLAYER_PROP_MIN_PICKEM_REFERENCE_BOOKMAKERS_ENV, "").strip()
    if not raw:
        return PLAYER_PROP_MIN_PICKEM_REFERENCE_BOOKMAKERS

    try:
        parsed = int(raw)
    except ValueError:
        return PLAYER_PROP_MIN_PICKEM_REFERENCE_BOOKMAKERS

    max_reference_books = max(1, len(PLAYER_PROP_BOOKS) - 1)
    return max(1, min(parsed, max_reference_books))


def get_player_prop_clv_min_reference_bookmakers() -> int:
    raw = os.getenv(PLAYER_PROP_MIN_CLV_REFERENCE_BOOKMAKERS_ENV, "").strip()
    if not raw:
        return PLAYER_PROP_MIN_CLV_REFERENCE_BOOKMAKERS

    try:
        parsed = int(raw)
    except ValueError:
        return PLAYER_PROP_MIN_CLV_REFERENCE_BOOKMAKERS

    max_reference_books = max(1, len(PLAYER_PROP_BOOKS) - 1)
    return max(1, min(parsed, max_reference_books))


def _resolve_scan_player_prop_markets(sport: str | None = None) -> list[str]:
    """Support older no-arg monkeypatches while allowing sport-specific defaults."""
    try:
        return get_player_prop_markets(sport)
    except TypeError:
        return get_player_prop_markets()


def _prop_cache_slot(sport: str) -> str:
    return f"{PLAYER_PROPS_SURFACE}:{PLAYER_PROP_CACHE_VERSION}:{sport}"


def _should_bypass_prop_cache(source: str | None) -> bool:
    normalized = str(source or "").strip().lower()
    return normalized == "manual_scan"


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


def _prop_market_display_suffix(market_key: str) -> str:
    """Short market tag for display_name (e.g. PTS, REB, 3PM). Matches app prop chip labels."""
    key = (market_key or "").strip().lower()
    known: dict[str, str] = {
        "player_points": "PTS",
        "player_rebounds": "REB",
        "player_assists": "AST",
        "player_points_rebounds_assists": "PTS/REB/AST",
        "player_threes": "3PM",
        "pitcher_strikeouts": "Pitcher Ks",
        "pitcher_strikeouts_alternate": "Pitcher Ks Alt",
        "batter_total_bases": "TB",
        "batter_total_bases_alternate": "TB ALT",
        "batter_hits": "Hits",
        "batter_hits_alternate": "Hits Alt",
        "batter_hits_runs_rbis": "H+R+RBI",
        "batter_home_runs": "HR",
        "batter_strikeouts": "Batter Ks",
        "batter_strikeouts_alternate": "Batter Ks Alt",
    }
    if key in known:
        return known[key]
    stripped = key.removeprefix("player_").replace("_", " ").strip()
    return stripped.upper() if stripped else ""


def _build_prop_display_name(
    *,
    player_name: str,
    side: str,
    line_value: float | None,
    market_key: str,
) -> str:
    if line_value is not None:
        base = f"{player_name} {side.title()} {line_value:g}"
    else:
        base = f"{player_name} {side.title()}"
    suffix = _prop_market_display_suffix(market_key)
    return f"{base} {suffix}".strip() if suffix else base


def _player_team_from_description(description: str | None) -> str | None:
    if not description:
        return None
    raw = str(description)
    if "(" in raw:
        prefix = raw.split("(")[-1].replace(")", "").strip()
        return prefix or None
    return None


def _canonical_team_name(name: str | None, *, sport: str | None = None) -> str:
    return canonical_team_token(sport, name)


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


def _normalize_prop_outcome_side(name: str, *, market_key: str | None = None) -> str | None:
    normalized_name = str(name or "").strip().lower()
    if normalized_name in {"over", "under"}:
        return normalized_name
    normalized_market = str(market_key or "").strip().lower()
    if normalized_market in PLAYER_PROP_YES_NO_MARKETS:
        if normalized_name == "yes":
            return "over"
        if normalized_name == "no":
            return "under"
    return None


def _normalize_prop_outcomes(outcomes: list[dict], *, market_key: str | None = None) -> list[dict]:
    normalized_market = str(market_key or "").strip().lower()
    normalized: dict[tuple[str, float | None], dict[str, dict]] = {}
    for outcome in outcomes:
        name = str(outcome.get("name") or "").strip()
        side = _normalize_prop_outcome_side(name, market_key=normalized_market)
        if side not in {"over", "under"}:
            continue
        line_value = outcome.get("point")
        try:
            line_numeric = float(line_value) if line_value is not None else None
        except Exception:
            line_numeric = None
        if line_numeric is None and normalized_market in PLAYER_PROP_YES_NO_MARKETS:
            line_numeric = 0.5
        description = str(outcome.get("description") or "").strip()
        player_name = description.split("(")[0].strip() if description else ""
        if not player_name:
            continue
        normalized_outcome = dict(outcome)
        normalized_outcome["name"] = side.title()
        if line_numeric is not None:
            normalized_outcome["point"] = line_numeric
        normalized.setdefault((player_name, line_numeric), {})[side] = normalized_outcome
    flattened: list[dict] = []
    for (_player_name, _line), pair in normalized.items():
        if "over" in pair and "under" in pair:
            flattened.extend([pair["over"], pair["under"]])
    return flattened


async def _fetch_prop_market_for_event(*, sport: str, event_id: str, markets: list[str], source: str) -> tuple[dict, httpx.Response]:
    if not ODDS_API_KEY:
        raise ValueError("ODDS_API_KEY not set in environment")

    url = f"{ODDS_API_BASE}/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "includeLinks": "true",
        "includeSids": "true",
    }

    started = time.monotonic()
    endpoint = f"/sports/{sport}/events/{event_id}/odds"
    try:
        from services.http_client import request_with_retries

        resp = await request_with_retries("GET", url, params=params, retries=2)
        resp.raise_for_status()
        duration_ms = (time.monotonic() - started) * 1000
        remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining")
        credits_used_last = _parse_credits_used_last(resp.headers.get("x-requests-last"))
        _append_odds_api_activity(
            source=source,
            endpoint=endpoint,
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
            endpoint=endpoint,
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


def _extract_market_meta(bookmakers: list[dict], book_key: str, market_key: str) -> dict | None:
    for bookmaker in bookmakers:
        if bookmaker.get("key") != book_key:
            continue
        event_link = bookmaker.get("link") or bookmaker.get("url")
        for market in bookmaker.get("markets", []):
            if market.get("key") == market_key:
                return {
                    "outcomes": market.get("outcomes") or [],
                    "market_link": market.get("link") or market.get("url"),
                    "event_link": event_link,
                }
    return None


def _build_prop_market_book_pairs(
    *,
    bookmakers: list[dict],
    target_markets: list[str],
) -> tuple[dict[str, dict[str, dict[tuple[str, float | None], dict[str, dict]]]], dict[str, dict[str, dict[str, str | None]]]]:
    selection_pairs_by_market_book: dict[str, dict[str, dict[tuple[str, float | None], dict[str, dict]]]] = {}
    deeplink_context_by_market_book: dict[str, dict[str, dict[str, str | None]]] = {}

    for market_key in target_markets:
        for book_key in PLAYER_PROP_BOOKS.keys():
            book_market = _extract_market_meta(bookmakers, book_key, market_key)
            if not book_market:
                continue
            normalized_book = _normalize_prop_outcomes(book_market["outcomes"], market_key=market_key)
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

            selection_pairs_by_market_book.setdefault(market_key, {})[book_key] = valid_selections
            deeplink_context_by_market_book.setdefault(market_key, {})[book_key] = {
                "market_link": book_market["market_link"],
                "event_link": book_market["event_link"],
            }

    return selection_pairs_by_market_book, deeplink_context_by_market_book


def _empty_prop_market_event_counts(target_markets: list[str]) -> dict[str, int]:
    return {
        str(market).strip(): 0
        for market in target_markets
        if str(market).strip()
    }


def _collect_prop_market_presence(
    *,
    bookmakers: list[dict],
    target_markets: list[str],
) -> dict[str, Any]:
    target_market_set = {
        str(market).strip()
        for market in target_markets
        if str(market).strip()
    }
    provider_market_books: dict[str, set[str]] = {}
    supported_market_books: dict[str, set[str]] = {}

    for bookmaker in bookmakers:
        if not isinstance(bookmaker, dict):
            continue
        book_key = str(bookmaker.get("key") or "").strip().lower()
        supported_book = book_key in PLAYER_PROP_BOOKS
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, dict):
                continue
            market_key = str(market.get("key") or "").strip()
            if market_key not in target_market_set:
                continue
            normalized_outcomes = _normalize_prop_outcomes(
                market.get("outcomes") or [],
                market_key=market_key,
            )
            if not normalized_outcomes:
                continue
            provider_market_books.setdefault(market_key, set()).add(book_key or "unknown")
            if supported_book:
                supported_market_books.setdefault(market_key, set()).add(book_key)

    provider_markets = sorted(provider_market_books.keys())
    supported_markets = sorted(supported_market_books.keys())
    return {
        "provider_markets": provider_markets,
        "supported_book_markets": supported_markets,
        "has_provider_markets": bool(provider_markets),
        "has_supported_book_markets": bool(supported_markets),
        "provider_bookmaker_counts_by_market": {
            market: len(books)
            for market, books in provider_market_books.items()
        },
        "supported_bookmaker_counts_by_market": {
            market: len(books)
            for market, books in supported_market_books.items()
        },
    }


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


def _weighted_consensus_prob(
    reference_probs: list[float],
    reference_bookmakers: list[str],
    *,
    outlier_threshold: float = 0.12,
) -> float:
    """Weighted consensus probability that favours sharper books.

    Steps:
    1. Compute an unweighted median as the outlier anchor.
    2. Exclude any book whose de-vigged prob is further than *outlier_threshold*
       from the anchor (protects against stale or mis-posted lines).
    3. Return a weighted mean of in-band probs using PLAYER_PROP_REFERENCE_BOOK_WEIGHTS
       (betonlineag→3×, bovada→1.5×, others→1×).

    Falls back to the unweighted median when all probs are outliers or the
    in-band weight sum is zero.
    """
    if not reference_probs:
        raise ValueError("reference_probs must be non-empty")
    if len(reference_probs) == 1:
        return reference_probs[0]

    anchor = float(median(reference_probs))

    in_band_probs: list[float] = []
    in_band_weights: list[float] = []
    for prob, book_key in zip(reference_probs, reference_bookmakers):
        if abs(prob - anchor) <= outlier_threshold:
            in_band_probs.append(prob)
            in_band_weights.append(PLAYER_PROP_REFERENCE_BOOK_WEIGHTS.get(book_key, 1.0))

    if not in_band_probs:
        return anchor  # all probs were outliers — fall back to median

    total_weight = sum(in_band_weights)
    if total_weight <= 0:
        return anchor

    return sum(p * w for p, w in zip(in_band_probs, in_band_weights)) / total_weight


def _reference_american_from_true_prob(true_prob: float) -> int | None:
    if true_prob <= 0 or true_prob >= 1:
        return None
    fair_decimal = 1 / true_prob
    if fair_decimal <= 1:
        return None
    return decimal_to_american(fair_decimal)


def _reference_source_for_model_key(model_key: str) -> str:
    normalized = str(model_key or "").strip().lower()
    if normalized in {PLAYER_PROP_MODEL_V2_LIVE, PLAYER_PROP_MODEL_V2_SHADOW}:
        return PLAYER_PROP_V2_REFERENCE_SOURCE
    return PLAYER_PROP_REFERENCE_SOURCE


def _is_v2_player_prop_model(model_key: str) -> bool:
    normalized = str(model_key or "").strip().lower()
    return normalized in {PLAYER_PROP_MODEL_V2_LIVE, PLAYER_PROP_MODEL_V2_SHADOW}


def _clip_probability(value: float, *, epsilon: float = 1e-6) -> float:
    return min(max(float(value), epsilon), 1 - epsilon)


def _logit_probability(value: float) -> float:
    clipped = _clip_probability(value)
    return math.log(clipped / (1 - clipped))


def _inv_logit(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def _median_absolute_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    anchor = float(median(values))
    deviations = [abs(value - anchor) for value in values]
    return float(median(deviations)) if deviations else 0.0


def _player_probabilities_for_pair(pair: dict[str, dict], *, side: str) -> dict[str, float] | None:
    true_probs = _devig_pair_probabilities(pair["over"], pair["under"])
    if not true_probs:
        return None
    if side == "under":
        return {"side_prob": true_probs["under"], "over_prob": true_probs["over"]}
    return {"side_prob": true_probs["over"], "over_prob": true_probs["over"]}


def _book_line_pairs_for_player(
    selection_pairs_by_book: dict[str, dict[tuple[str, float | None], dict[str, dict]]],
    *,
    reference_book_key: str,
    player_name: str,
) -> list[tuple[float, dict[str, dict]]]:
    pairs = selection_pairs_by_book.get(reference_book_key) or {}
    values: list[tuple[float, dict[str, dict]]] = []
    for (candidate_player, line_value), pair in pairs.items():
        if candidate_player != player_name or line_value is None:
            continue
        values.append((float(line_value), pair))
    values.sort(key=lambda item: item[0])
    return values


def _interpolate_logit_probability(
    *,
    lower_line: float,
    lower_prob: float,
    upper_line: float,
    upper_prob: float,
    target_line: float,
) -> float | None:
    if upper_line <= lower_line:
        return None
    if target_line < lower_line or target_line > upper_line:
        return None
    if abs(target_line - lower_line) < 1e-9:
        return lower_prob
    if abs(target_line - upper_line) < 1e-9:
        return upper_prob
    lower_logit = _logit_probability(lower_prob)
    upper_logit = _logit_probability(upper_prob)
    ratio = (target_line - lower_line) / (upper_line - lower_line)
    return _inv_logit(lower_logit + (upper_logit - lower_logit) * ratio)


def _build_reference_estimates_for_side(
    *,
    selection_pairs_by_book: dict[str, dict[tuple[str, float | None], dict[str, dict]]],
    current_book_key: str,
    player_name: str,
    line_value: float | None,
    side: str,
    model_key: str,
) -> list[dict[str, Any]]:
    estimates: list[dict[str, Any]] = []
    allow_interpolation = _is_v2_player_prop_model(model_key) and line_value is not None

    for reference_book_key, reference_pairs in selection_pairs_by_book.items():
        if reference_book_key == current_book_key:
            continue
        exact_pair = reference_pairs.get((player_name, line_value))
        if exact_pair:
            probs = _player_probabilities_for_pair(exact_pair, side=side)
            if probs:
                estimates.append(
                    {
                        "book_key": reference_book_key,
                        "prob": probs["side_prob"],
                        "input_mode": "exact",
                        "source_line_value": line_value,
                        "lower_line_value": line_value,
                        "upper_line_value": line_value,
                    }
                )
            continue

        if not allow_interpolation:
            continue

        line_pairs = _book_line_pairs_for_player(
            selection_pairs_by_book,
            reference_book_key=reference_book_key,
            player_name=player_name,
        )
        if len(line_pairs) < 2:
            continue

        lower: tuple[float, dict[str, dict]] | None = None
        upper: tuple[float, dict[str, dict]] | None = None
        for candidate_line, pair in line_pairs:
            if candidate_line <= float(line_value):
                lower = (candidate_line, pair)
            if candidate_line >= float(line_value) and upper is None:
                upper = (candidate_line, pair)
        if lower is None or upper is None or abs(lower[0] - upper[0]) < 1e-9:
            continue

        lower_probs = _player_probabilities_for_pair(lower[1], side=side)
        upper_probs = _player_probabilities_for_pair(upper[1], side=side)
        if not lower_probs or not upper_probs:
            continue

        interpolated_prob = _interpolate_logit_probability(
            lower_line=lower[0],
            lower_prob=lower_probs["side_prob"],
            upper_line=upper[0],
            upper_prob=upper_probs["side_prob"],
            target_line=float(line_value),
        )
        if interpolated_prob is None:
            continue

        estimates.append(
            {
                "book_key": reference_book_key,
                "prob": interpolated_prob,
                "input_mode": "interpolated",
                "source_line_value": line_value,
                "lower_line_value": lower[0],
                "upper_line_value": upper[0],
            }
        )

    return estimates


def _book_weight_for_model(
    *,
    book_key: str,
    market_key: str,
    model_key: str,
    weight_overrides: dict[str, dict[str, float]] | None,
) -> float:
    if _is_v2_player_prop_model(model_key):
        override = None
        if isinstance(weight_overrides, dict):
            override = (
                (weight_overrides.get(str(market_key or "").strip()) or {}).get(book_key)
                if isinstance(weight_overrides.get(str(market_key or "").strip()), dict)
                else None
            )
        if override is not None:
            try:
                return max(float(override), 0.1)
            except Exception:
                pass
    return PLAYER_PROP_REFERENCE_BOOK_WEIGHTS.get(book_key, 1.0)


def _shrink_probability_toward_even(
    raw_prob: float,
    *,
    confidence_score: float | None,
) -> tuple[float, float]:
    score = confidence_score if confidence_score is not None else 0.0
    shrink_factor = max(0.0, min(0.30, (1.0 - score) * 0.30))
    shrunk_prob = 0.5 + ((raw_prob - 0.5) * (1.0 - shrink_factor))
    return _clip_probability(shrunk_prob), round(shrink_factor, 4)


def _reference_inputs_json(reference_estimates: list[dict[str, Any]]) -> str:
    payload = [
        {
            "book_key": str(estimate.get("book_key") or ""),
            "prob": round(float(estimate.get("prob") or 0.0), 6),
            "input_mode": str(estimate.get("input_mode") or "exact"),
            "source_line_value": estimate.get("source_line_value"),
            "lower_line_value": estimate.get("lower_line_value"),
            "upper_line_value": estimate.get("upper_line_value"),
        }
        for estimate in reference_estimates
    ]
    return json.dumps(payload, sort_keys=True)


def _aggregate_reference_estimates(
    *,
    reference_estimates: list[dict[str, Any]],
    model_key: str,
    market_key: str,
    weight_overrides: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any] | None:
    if not reference_estimates:
        return None

    reference_probs = [float(estimate["prob"]) for estimate in reference_estimates]
    reference_bookmakers = [str(estimate["book_key"]) for estimate in reference_estimates]
    exact_reference_count = sum(1 for estimate in reference_estimates if estimate.get("input_mode") == "exact")
    interpolated_reference_count = sum(1 for estimate in reference_estimates if estimate.get("input_mode") == "interpolated")

    if not _is_v2_player_prop_model(model_key):
        anchor = float(median(reference_probs))
        in_band_estimates = [
            estimate
            for estimate in reference_estimates
            if abs(float(estimate["prob"]) - anchor) <= 0.12
        ]
        true_prob = _weighted_consensus_prob(reference_probs, reference_bookmakers)
        return {
            "raw_true_prob": true_prob,
            "true_prob": true_prob,
            "shrink_factor": 0.0,
            "reference_probs": reference_probs,
            "reference_bookmakers": reference_bookmakers,
            "filtered_reference_count": len(in_band_estimates) if in_band_estimates else len(reference_estimates),
            "exact_reference_count": exact_reference_count,
            "interpolated_reference_count": interpolated_reference_count,
            "interpolation_mode": "exact",
            "reference_inputs_json": _reference_inputs_json(reference_estimates),
        }

    logits = [_logit_probability(prob) for prob in reference_probs]
    anchor = float(median(logits))
    mad = _median_absolute_deviation(logits)
    outlier_band = max(0.25, mad * 3.0)
    in_band_estimates = [
        estimate
        for estimate, logit_value in zip(reference_estimates, logits)
        if abs(logit_value - anchor) <= outlier_band
    ]
    if not in_band_estimates:
        in_band_estimates = list(reference_estimates)

    total_weight = 0.0
    weighted_logit_sum = 0.0
    for estimate in in_band_estimates:
        prob = _clip_probability(float(estimate["prob"]))
        weight = _book_weight_for_model(
            book_key=str(estimate.get("book_key") or ""),
            market_key=market_key,
            model_key=model_key,
            weight_overrides=weight_overrides,
        )
        total_weight += weight
        weighted_logit_sum += _logit_probability(prob) * weight
    if total_weight <= 0:
        return None

    raw_true_prob = _inv_logit(weighted_logit_sum / total_weight)
    interpolation_mode = "exact"
    if interpolated_reference_count > 0 and exact_reference_count > 0:
        interpolation_mode = "mixed"
    elif interpolated_reference_count > 0:
        interpolation_mode = "interpolated"

    return {
        "raw_true_prob": raw_true_prob,
        "true_prob": raw_true_prob,
        "shrink_factor": 0.0,
        "reference_probs": reference_probs,
        "reference_bookmakers": reference_bookmakers,
        "filtered_reference_count": len(in_band_estimates),
        "exact_reference_count": exact_reference_count,
        "interpolated_reference_count": interpolated_reference_count,
        "interpolation_mode": interpolation_mode,
        "reference_inputs_json": _reference_inputs_json(reference_estimates),
    }


def _normalize_player_team(token: str | None, *, home_team: str, away_team: str, sport: str | None) -> str | None:
    token_key = _canonical_team_name(token, sport=sport)
    if not token_key:
        return None

    for team_name in (home_team, away_team):
        team_key = _canonical_team_name(team_name, sport=sport)
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
    sport: str | None,
) -> tuple[str | None, str | None]:
    explicit_team = _normalize_player_team(
        _player_team_from_description(description),
        home_team=home_team,
        away_team=away_team,
        sport=sport,
    )
    player_context = (player_context_lookup or {}).get(_canonical_player_name(player_name)) or {}
    inferred_team = _normalize_player_team(
        player_context.get("team"),
        home_team=home_team,
        away_team=away_team,
        sport=sport,
    )
    participant_id = player_context.get("participant_id")
    return explicit_team or inferred_team, participant_id


def _confidence_label_for_reference_count(reference_count: int) -> str:
    """Legacy label based solely on book count. Kept for any callers not yet upgraded."""
    if reference_count >= 4:
        return "elite"
    if reference_count >= 3:
        return "high"
    if reference_count >= PLAYER_PROP_MIN_SOLID_REFERENCE_BOOKMAKERS:
        return "solid"
    return "thin"


def _compute_confidence(
    *,
    reference_bookmakers: list[str],
    reference_probs: list[float],
) -> tuple[str, float, float]:
    """Compute (confidence_label, confidence_score, prob_std).

    confidence_score (0–1) weighs three factors:
    - Book count:        0.25 per reference book, capped at 1.0
    - BetOnline anchor: +0.20 bonus when "betonlineag" is in the reference set
    - Dispersion:       penalty = min(prob_std × 4, 0.40) — punishes noisy consensus

    Label thresholds:  ≥0.75 → elite | ≥0.55 → high | ≥0.30 → solid | else → thin
    """
    n = len(reference_bookmakers)
    if n >= 2:
        mean_p = sum(reference_probs) / n
        prob_std = (sum((p - mean_p) ** 2 for p in reference_probs) / n) ** 0.5
    else:
        prob_std = 0.0

    base = min(n / 4.0, 1.0)
    anchor_bonus = 0.20 if "betonlineag" in reference_bookmakers else 0.0
    dispersion_penalty = min(prob_std * 4.0, 0.40)

    raw_score = base + anchor_bonus - dispersion_penalty
    confidence_score = round(max(0.0, min(1.0, raw_score)), 4)

    if confidence_score >= 0.75:
        label = "elite"
    elif confidence_score >= 0.55:
        label = "high"
    elif confidence_score >= 0.30:
        label = "solid"
    else:
        label = "thin"

    return label, confidence_score, round(prob_std, 4)


def _build_prop_model_evaluations_for_candidate(
    *,
    selection_pairs_by_book: dict[str, dict[tuple[str, float | None], dict[str, dict]]],
    current_book_key: str,
    market_key: str,
    player_name: str,
    line_value: float | None,
    side: str,
    book_odds: float,
    weight_overrides: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    book_decimal = american_to_decimal(book_odds)
    active_model_key = get_player_prop_active_model_key()
    shadow_model_key = get_player_prop_shadow_model_key(active_model_key)
    model_keys = [active_model_key]
    if shadow_model_key and shadow_model_key not in model_keys:
        model_keys.append(shadow_model_key)

    evaluations: list[dict[str, Any]] = []
    active_evaluation: dict[str, Any] | None = None

    for model_key in model_keys:
        reference_estimates = _build_reference_estimates_for_side(
            selection_pairs_by_book=selection_pairs_by_book,
            current_book_key=current_book_key,
            player_name=player_name,
            line_value=line_value,
            side=side,
            model_key=model_key,
        )
        if not reference_estimates:
            continue

        aggregation = _aggregate_reference_estimates(
            reference_estimates=reference_estimates,
            model_key=model_key,
            market_key=market_key,
            weight_overrides=weight_overrides,
        )
        if not aggregation:
            continue

        confidence_label, confidence_score, prob_std = _compute_confidence(
            reference_bookmakers=list(aggregation["reference_bookmakers"]),
            reference_probs=list(aggregation["reference_probs"]),
        )

        true_prob = float(aggregation["true_prob"])
        raw_true_prob = float(aggregation["raw_true_prob"])
        shrink_factor = 0.0
        if _is_v2_player_prop_model(model_key):
            true_prob, shrink_factor = _shrink_probability_toward_even(
                raw_true_prob,
                confidence_score=confidence_score,
            )

        reference_odds = _reference_american_from_true_prob(true_prob)
        if reference_odds is None:
            continue

        evaluation = {
            "model_key": model_key,
            "reference_source": _reference_source_for_model_key(model_key),
            "reference_odds": float(reference_odds),
            "true_prob": round(true_prob, 6),
            "raw_true_prob": round(raw_true_prob, 6),
            "reference_bookmakers": list(aggregation["reference_bookmakers"]),
            "reference_bookmaker_count": len(aggregation["reference_bookmakers"]),
            "filtered_reference_count": int(aggregation["filtered_reference_count"]),
            "exact_reference_count": int(aggregation["exact_reference_count"]),
            "interpolated_reference_count": int(aggregation["interpolated_reference_count"]),
            "interpolation_mode": str(aggregation["interpolation_mode"] or "exact"),
            "reference_inputs_json": aggregation["reference_inputs_json"],
            "confidence_label": confidence_label,
            "confidence_score": confidence_score,
            "prob_std": prob_std,
            "book_odds": float(book_odds),
            "book_decimal": round(book_decimal, 4),
            "ev_percentage": round((true_prob * book_decimal - 1) * 100, 2),
            "base_kelly_fraction": round(kelly_fraction(true_prob, book_decimal), 6),
            "shrink_factor": shrink_factor,
            "sportsbook_key": current_book_key,
            "market_key": market_key,
        }
        evaluations.append(evaluation)
        if model_key == active_model_key:
            active_evaluation = evaluation

    return active_evaluation, evaluations


def _american_price_quality(american: float | int | None) -> float | None:
    if american is None:
        return None
    try:
        return american_to_decimal(float(american))
    except Exception:
        return None


def _canonical_matchup_key(away_team: str | None, home_team: str | None, *, sport: str | None = None) -> str:
    return f"{_canonical_team_name(away_team, sport=sport)}|{_canonical_team_name(home_team, sport=sport)}"


def _parse_commence_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _pick_best_outcome_offer(offers: list[dict], price_key: str) -> dict | None:
    best_offer: dict | None = None
    best_quality: float | None = None
    for offer in offers:
        quality = _american_price_quality(offer.get(price_key))
        if quality is None:
            continue
        if best_quality is None or quality > best_quality:
            best_quality = quality
            best_offer = offer
    return best_offer


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
        key = (_canonical_team_name(away_team, sport="basketball_nba"), _canonical_team_name(home_team, sport="basketball_nba"))
        if all(key) and key not in odds_index:
            odds_index[key] = event

    details: list[dict] = []
    for game in curated_games:
        away_key_raw = str(game.get("away_team_key") or game.get("away_team") or "")
        home_key_raw = str(game.get("home_team_key") or game.get("home_team") or "")
        key = (
            _canonical_team_name(away_key_raw, sport="basketball_nba"),
            _canonical_team_name(home_key_raw, sport="basketball_nba"),
        )
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


def _selection_reason_rank(value: str | None) -> int:
    selection_reason = str(value or "").strip().lower()
    if selection_reason == "national_tv":
        return 0
    if selection_reason == "nba_tv":
        return 1
    if selection_reason == "scoreboard_fallback":
        return 2
    return 3


def _prioritize_curated_match_details(
    match_details: list[dict],
    *,
    pregame_cutoff: datetime,
    max_games: int = 3,
) -> list[dict]:
    ranked: list[tuple[tuple[int, int, int], dict]] = []
    for index, detail in enumerate(match_details):
        event = detail.get("odds_event")
        commence_dt = _parse_commence_time(detail.get("commence_time"))
        is_fetchable = bool(event) and (commence_dt is None or commence_dt > pregame_cutoff)
        if is_fetchable:
            bucket = 0
        elif event:
            bucket = 1
        else:
            bucket = 2
        rank = (
            bucket,
            _selection_reason_rank(detail.get("selection_reason")),
            index,
        )
        ranked.append((rank, detail))

    ranked.sort(key=lambda item: item[0])
    return [detail for _rank, detail in ranked[:max_games]]


def _select_fallback_odds_events(
    odds_events: list[dict],
    *,
    pregame_cutoff: datetime,
    max_events: int = PLAYER_PROP_FALLBACK_MAX_EVENTS,
) -> list[dict]:
    fetchable: list[dict] = []
    unknown_start: list[dict] = []
    for event in odds_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        commence_dt = _parse_commence_time(event.get("commence_time"))
        if commence_dt is None:
            unknown_start.append(event)
            continue
        if commence_dt > pregame_cutoff:
            fetchable.append(event)
    return (fetchable + unknown_start)[:max_events]


def _eligible_prop_event_ids_from_odds_events(
    odds_events: list[dict],
    *,
    pregame_cutoff: datetime,
) -> list[str]:
    event_ids: list[str] = []
    for event in odds_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        commence_dt = _parse_commence_time(event.get("commence_time"))
        if commence_dt is not None and commence_dt <= pregame_cutoff:
            continue
        event_ids.append(event_id)
    return event_ids


def _build_prop_side_candidates(
    *,
    sport: str,
    event_payload: dict,
    target_markets: list[str],
    player_context_lookup: dict[str, dict[str, str | None]] | None = None,
    weight_overrides: dict[str, dict[str, float]] | None = None,
) -> list[dict]:
    bookmakers = event_payload.get("bookmakers") or []
    home = str(event_payload.get("home_team") or "")
    away = str(event_payload.get("away_team") or "")
    event_id = event_payload.get("id")
    commence_time = str(event_payload.get("commence_time") or "")
    event_name = f"{away} @ {home}".strip()
    candidates: list[dict] = []
    selection_pairs_by_market_book, deeplink_context_by_market_book = _build_prop_market_book_pairs(
        bookmakers=bookmakers,
        target_markets=target_markets,
    )

    for market_key in target_markets:
        selection_pairs_by_book = selection_pairs_by_market_book.get(market_key, {})
        deeplink_context_by_book = deeplink_context_by_market_book.get(market_key, {})

        for book_key, book_display in PLAYER_PROP_BOOKS.items():
            book_pairs = selection_pairs_by_book.get(book_key)
            if not book_pairs:
                continue
            deeplink_context = deeplink_context_by_book.get(book_key) or {}

            for (player_name, line_value), book_pair in book_pairs.items():
                for side in ("over", "under"):
                    outcome = book_pair.get(side)
                    if not outcome:
                        continue

                    try:
                        book_odds = float(outcome["price"])
                    except Exception:
                        continue

                    active_evaluation, model_evaluations = _build_prop_model_evaluations_for_candidate(
                        selection_pairs_by_book=selection_pairs_by_book,
                        current_book_key=book_key,
                        market_key=market_key,
                        player_name=player_name,
                        line_value=line_value,
                        side=side,
                        book_odds=book_odds,
                        weight_overrides=weight_overrides,
                    )
                    if not active_evaluation:
                        continue

                    selection_key = _build_selection_key(
                        event_id=str(event_id or ""),
                        market_key=market_key,
                        player_name=player_name,
                        side=side,
                        line_value=line_value,
                    )
                    display_name = _build_prop_display_name(
                        player_name=player_name,
                        side=side,
                        line_value=line_value,
                        market_key=market_key,
                    )
                    player_team, participant_id = _resolve_player_context(
                        player_name=player_name,
                        description=outcome.get("description"),
                        player_context_lookup=player_context_lookup,
                        home_team=home,
                        away_team=away,
                        sport=sport,
                    )
                    opponent = None
                    if player_team == home:
                        opponent = away
                    elif player_team == away:
                        opponent = home
                    deeplink, deeplink_level = resolve_sportsbook_deeplink(
                        sportsbook=book_display,
                        selection_link=outcome.get("link") or outcome.get("url"),
                        market_link=deeplink_context.get("market_link"),
                        event_link=deeplink_context.get("event_link"),
                    )
                    candidates.append(
                        {
                            "surface": PLAYER_PROPS_SURFACE,
                            "event_id": event_id,
                            "market_key": market_key,
                            "selection_key": selection_key,
                            "sportsbook": book_display,
                            "sportsbook_deeplink_url": deeplink,
                            "sportsbook_deeplink_level": deeplink_level,
                            "sport": sport,
                            "event": event_name,
                            "event_short": build_short_event_label(sport, away, home),
                            "commence_time": commence_time,
                            "market": market_key,
                            "player_name": player_name,
                            "participant_id": participant_id,
                            "team": player_team,
                            "team_short": canonical_short_name(sport, player_team) if player_team else None,
                            "opponent": opponent,
                            "opponent_short": canonical_short_name(sport, opponent) if opponent else None,
                            "selection_side": side,
                            "line_value": line_value,
                            "display_name": display_name,
                            "reference_odds": float(active_evaluation["reference_odds"]),
                            "reference_source": str(active_evaluation["reference_source"]),
                            "reference_bookmakers": list(active_evaluation["reference_bookmakers"]),
                            "reference_bookmaker_count": int(active_evaluation["reference_bookmaker_count"]),
                            "confidence_label": active_evaluation["confidence_label"],
                            "confidence_score": active_evaluation["confidence_score"],
                            "prob_std": active_evaluation["prob_std"],
                            "book_odds": book_odds,
                            "true_prob": round(float(active_evaluation["true_prob"]), 4),
                            "base_kelly_fraction": float(active_evaluation["base_kelly_fraction"]),
                            "book_decimal": float(active_evaluation["book_decimal"]),
                            "ev_percentage": float(active_evaluation["ev_percentage"]),
                            "active_model_key": str(active_evaluation["model_key"]),
                            "shadow_model_key": next(
                                (
                                    str(evaluation["model_key"])
                                    for evaluation in model_evaluations
                                    if str(evaluation.get("model_key") or "") != str(active_evaluation["model_key"])
                                ),
                                None,
                            ),
                            "interpolation_mode": str(active_evaluation.get("interpolation_mode") or "exact"),
                            "reference_inputs_json": active_evaluation.get("reference_inputs_json"),
                            "model_evaluations": model_evaluations,
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
            side.get("confidence_score", 0.0),
            side["ev_percentage"],
        ),
        reverse=True,
    )
    return filtered


def _build_pickem_cards_from_candidates(
    candidates: list[dict],
    *,
    min_reference_bookmakers: int,
) -> list[dict]:
    if not candidates:
        return []

    from services.player_prop_board import build_player_prop_board_item, build_player_prop_board_pickem_cards

    eligible_sides = _apply_reference_quality_gate(
        candidates,
        min_reference_bookmakers=min_reference_bookmakers,
    )
    if not eligible_sides:
        return []

    return build_player_prop_board_pickem_cards(
        [build_player_prop_board_item(side) for side in eligible_sides if isinstance(side, dict)]
    )


def _parse_prop_sides(
    *,
    sport: str,
    event_payload: dict,
    target_markets: list[str],
    player_context_lookup: dict[str, dict[str, str | None]] | None = None,
    min_reference_bookmakers: int | None = None,
    weight_overrides: dict[str, dict[str, float]] | None = None,
) -> list[dict]:
    candidates = _build_prop_side_candidates(
        sport=sport,
        event_payload=event_payload,
        target_markets=target_markets,
        player_context_lookup=player_context_lookup,
        weight_overrides=weight_overrides,
    )
    return _apply_reference_quality_gate(
        candidates,
        min_reference_bookmakers=min_reference_bookmakers or get_player_prop_min_reference_bookmakers(),
    )


def _build_exact_line_reference_index(
    *,
    event_payload: dict,
    target_markets: list[str],
    player_context_lookup: dict[str, dict[str, str | None]] | None = None,
) -> tuple[dict[tuple[str, str, str, float | None], dict], dict[tuple[str, str, float | None], dict]]:
    bookmakers = event_payload.get("bookmakers") or []
    sport = str(event_payload.get("sport_key") or "basketball_nba")
    home = str(event_payload.get("home_team") or "")
    away = str(event_payload.get("away_team") or "")
    event_id = str(event_payload.get("id") or "").strip() or None
    commence_time = str(event_payload.get("commence_time") or "")
    event_name = f"{away} @ {home}".strip()
    selection_pairs_by_market_book, deeplink_context_by_market_book = _build_prop_market_book_pairs(
        bookmakers=bookmakers,
        target_markets=target_markets,
    )

    raw_index: dict[tuple[str, str, str, float | None], dict] = {}
    fallback_index: dict[tuple[str, str, float | None], dict] = {}

    for market_key in target_markets:
        selection_pairs_by_book = selection_pairs_by_market_book.get(market_key, {})
        deeplink_context_by_book = deeplink_context_by_market_book.get(market_key, {})

        for book_key, selection_pairs in selection_pairs_by_book.items():
            book_display = PLAYER_PROP_BOOKS.get(book_key, book_key)
            deeplink_context = deeplink_context_by_book.get(book_key) or {}

            for (player_name, line_value), pair in selection_pairs.items():
                player_team, participant_id = _resolve_player_context(
                    player_name=player_name,
                    description=pair["over"].get("description"),
                    player_context_lookup=player_context_lookup,
                    home_team=home,
                    away_team=away,
                    sport=sport,
                )
                opponent = None
                if player_team == home:
                    opponent = away
                elif player_team == away:
                    opponent = home

                player_key = _canonical_player_name(player_name)
                team_key = _canonical_team_name(player_team, sport=sport)
                reference_key = (player_key, team_key, market_key, line_value)
                entry = raw_index.setdefault(
                    reference_key,
                    {
                        "event_id": event_id,
                        "sport": sport,
                        "event": event_name,
                        "event_short": build_short_event_label(sport, away, home),
                        "commence_time": commence_time,
                        "player_name": player_name,
                        "participant_id": participant_id,
                        "team": player_team,
                        "team_short": canonical_short_name(sport, player_team) if player_team else None,
                        "opponent": opponent,
                        "opponent_short": canonical_short_name(sport, opponent) if opponent else None,
                        "player_key": player_key,
                        "team_key": team_key,
                        "market_key": market_key,
                        "market": market_key,
                        "line_value": line_value,
                        "over_probs": [],
                        "over_prob_book_keys": [],
                        "under_probs": [],
                        "under_prob_book_keys": [],
                        "offers": [],
                    },
                )

                true_probs = _devig_pair_probabilities(pair["over"], pair["under"])
                if true_probs:
                    entry["over_probs"].append(true_probs["over"])
                    entry["over_prob_book_keys"].append(book_key)
                    entry["under_probs"].append(true_probs["under"])
                    entry["under_prob_book_keys"].append(book_key)

                over_deeplink, _ = resolve_sportsbook_deeplink(
                    sportsbook=book_display,
                    selection_link=pair["over"].get("link") or pair["over"].get("url"),
                    market_link=deeplink_context.get("market_link"),
                    event_link=deeplink_context.get("event_link"),
                )
                under_deeplink, _ = resolve_sportsbook_deeplink(
                    sportsbook=book_display,
                    selection_link=pair["under"].get("link") or pair["under"].get("url"),
                    market_link=deeplink_context.get("market_link"),
                    event_link=deeplink_context.get("event_link"),
                )

                entry["offers"].append(
                    {
                        "sportsbook": book_display,
                        "over_odds": pair["over"].get("price"),
                        "over_deeplink_url": over_deeplink,
                        "under_odds": pair["under"].get("price"),
                        "under_deeplink_url": under_deeplink,
                    }
                )

    reference_index: dict[tuple[str, str, str, float | None], dict] = {}
    for reference_key, entry in raw_index.items():
        offers = entry.get("offers") or []
        if not offers:
            continue
        over_probs = entry.get("over_probs") or []
        under_probs = entry.get("under_probs") or []
        if not over_probs or not under_probs:
            continue

        over_book_keys = entry.get("over_prob_book_keys") or []
        under_book_keys = entry.get("under_prob_book_keys") or []
        exact_line_bookmakers = [str(offer["sportsbook"]) for offer in offers if offer.get("sportsbook")]
        exact_line_bookmaker_count = len(exact_line_bookmakers)
        best_over_offer = _pick_best_outcome_offer(offers, "over_odds")
        best_under_offer = _pick_best_outcome_offer(offers, "under_odds")

        consensus_over_prob = _weighted_consensus_prob(over_probs, over_book_keys)
        consensus_under_prob = _weighted_consensus_prob(under_probs, under_book_keys)
        confidence_label, confidence_score, prob_std = _compute_confidence(
            reference_bookmakers=over_book_keys,
            reference_probs=over_probs,
        )

        finalized = {
            **entry,
            "exact_line_bookmakers": exact_line_bookmakers,
            "exact_line_bookmaker_count": exact_line_bookmaker_count,
            "consensus_over_prob": round(float(consensus_over_prob), 4),
            "consensus_under_prob": round(float(consensus_under_prob), 4),
            "confidence_label": confidence_label,
            "confidence_score": confidence_score,
            "prob_std": prob_std,
            "best_over_sportsbook": best_over_offer.get("sportsbook") if best_over_offer else None,
            "best_over_odds": float(best_over_offer["over_odds"]) if best_over_offer and best_over_offer.get("over_odds") is not None else None,
            "best_over_deeplink_url": best_over_offer.get("over_deeplink_url") if best_over_offer else None,
            "best_under_sportsbook": best_under_offer.get("sportsbook") if best_under_offer else None,
            "best_under_odds": float(best_under_offer["under_odds"]) if best_under_offer and best_under_offer.get("under_odds") is not None else None,
            "best_under_deeplink_url": best_under_offer.get("under_deeplink_url") if best_under_offer else None,
        }
        reference_index[reference_key] = finalized
        fallback_index.setdefault(
            (entry["player_key"], entry["market_key"], entry["line_value"]),
            finalized,
        )

    return reference_index, fallback_index


def _build_prizepicks_comparison_cards(
    *,
    event_payload: dict,
    target_markets: list[str],
    player_context_lookup: dict[str, dict[str, str | None]] | None = None,
    prizepicks_projections: list[dict] | None = None,
    min_reference_bookmakers: int,
) -> tuple[list[dict], dict[str, int]]:
    if not prizepicks_projections:
        return [], {"matched": 0, "unmatched": 0, "filtered": 0}

    reference_index, fallback_index = _build_exact_line_reference_index(
        event_payload=event_payload,
        target_markets=target_markets,
        player_context_lookup=player_context_lookup,
    )

    cards: list[dict] = []
    matched = 0
    unmatched = 0
    filtered = 0
    seen_keys: set[str] = set()

    for projection in prizepicks_projections:
        market_key = str(projection.get("market_key") or "").strip()
        if market_key not in target_markets:
            continue
        player_key = _canonical_player_name(projection.get("player_name"))
        team_key = _canonical_team_name(projection.get("team"))
        line_value = projection.get("line_value")

        reference = reference_index.get((player_key, team_key, market_key, line_value))
        if not reference:
            reference = fallback_index.get((player_key, market_key, line_value))

        if not reference:
            unmatched += 1
            continue

        if int(reference.get("exact_line_bookmaker_count") or 0) < min_reference_bookmakers:
            filtered += 1
            continue

        consensus_over_prob = float(reference["consensus_over_prob"])
        consensus_under_prob = float(reference["consensus_under_prob"])
        comparison_key = "|".join(
            [
                str(reference.get("event_id") or projection.get("event_id") or "").strip(),
                market_key,
                player_key,
                "" if line_value is None else str(line_value),
            ]
        )
        if comparison_key in seen_keys:
            continue
        seen_keys.add(comparison_key)

        cards.append(
            {
                "comparison_key": comparison_key,
                "event_id": reference.get("event_id") or projection.get("event_id"),
                "sport": str(reference.get("sport") or "basketball_nba"),
                "event": str(reference.get("event") or projection.get("event") or ""),
                "commence_time": str(reference.get("commence_time") or projection.get("commence_time") or ""),
                "player_name": str(reference.get("player_name") or projection.get("player_name") or ""),
                "participant_id": reference.get("participant_id") or projection.get("participant_id"),
                "team": reference.get("team") or projection.get("team"),
                "opponent": reference.get("opponent") or projection.get("opponent"),
                "market_key": market_key,
                "market": str(reference.get("market") or market_key),
                "prizepicks_line": float(line_value),
                "exact_line_bookmakers": list(reference.get("exact_line_bookmakers") or []),
                "exact_line_bookmaker_count": int(reference.get("exact_line_bookmaker_count") or 0),
                "consensus_over_prob": consensus_over_prob,
                "consensus_under_prob": consensus_under_prob,
                "consensus_side": "over" if consensus_over_prob >= consensus_under_prob else "under",
                "confidence_label": str(reference.get("confidence_label") or "thin"),
                "best_over_sportsbook": reference.get("best_over_sportsbook"),
                "best_over_odds": reference.get("best_over_odds"),
                "best_over_deeplink_url": reference.get("best_over_deeplink_url"),
                "best_under_sportsbook": reference.get("best_under_sportsbook"),
                "best_under_odds": reference.get("best_under_odds"),
                "best_under_deeplink_url": reference.get("best_under_deeplink_url"),
            }
        )
        matched += 1

    return cards, {"matched": matched, "unmatched": unmatched, "filtered": filtered}


async def scan_player_props(sport: str, source: str = "manual_scan") -> dict:
    normalized_sport = str(sport or "").strip().lower()
    if normalized_sport not in get_supported_player_prop_sports():
        raise ValueError(
            f"Unsupported player-prop sport '{sport}'. "
            f"Choose from: {', '.join(get_supported_player_prop_sports())}"
        )

    target_markets = _resolve_scan_player_prop_markets(normalized_sport)
    if normalized_sport != "basketball_nba":
        pregame_cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)
        events_payload, events_resp = await fetch_events(normalized_sport, source=f"{source}_props_events")
        odds_events = events_payload if isinstance(events_payload, list) else []
        event_ids = _eligible_prop_event_ids_from_odds_events(
            odds_events,
            pregame_cutoff=pregame_cutoff,
        )
        result = await scan_player_props_for_event_ids(
            sport=normalized_sport,
            event_ids=event_ids,
            markets=target_markets,
            source=source,
        )
        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
        fallback_reason = None
        if not odds_events:
            fallback_reason = "No Odds API events were available for this sport."
        elif not event_ids:
            fallback_reason = "No upcoming Odds API events were eligible for player-prop requests."
        result["diagnostics"] = {
            **diagnostics,
            "scan_mode": "full_slate",
            "scan_scope": "odds_events",
            "scoreboard_event_count": 0,
            "odds_event_count": len(odds_events),
            "curated_games": [],
            "matched_event_count": len(event_ids),
            "unmatched_game_count": 0,
            "fallback_reason": fallback_reason,
            "fallback_event_count": 0,
            "events_selected_count": len(event_ids),
            "markets_requested": target_markets,
            "sports_scanned": [normalized_sport],
        }
        result["api_requests_remaining"] = (
            result.get("api_requests_remaining")
            or events_resp.headers.get("x-requests-remaining")
            or events_resp.headers.get("x-request-remaining")
        )
        return result

    min_reference_bookmakers = get_player_prop_min_reference_bookmakers()
    pickem_min_reference_bookmakers = get_player_prop_pickem_min_reference_bookmakers()
    weight_overrides = get_player_prop_weight_overrides()
    scoreboard_payload = await fetch_nba_scoreboard_window()
    scoreboard_events = scoreboard_payload.get("events") if isinstance(scoreboard_payload, dict) else []
    scoreboard_count = len(scoreboard_events) if isinstance(scoreboard_events, list) else 0
    curated_candidates = extract_national_tv_matchups(scoreboard_payload, max_games=max(3, scoreboard_count or 0))
    curated_games = curated_candidates[:3]
    selection_reasons = [str(game.get("selection_reason") or "unknown") for game in curated_games]
    pregame_cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)
    logger.info(
        "player_props.scan.scoreboard sport=%s source=%s scoreboard_events=%s curated_candidates=%s curated_games=%s selection_reasons=%s",
        normalized_sport,
        source,
        scoreboard_count,
        len(curated_candidates),
        len(curated_games),
        ",".join(selection_reasons) if selection_reasons else "none",
    )
    if not curated_candidates:
        logger.info(
            "player_props.scan.no_curated_games sport=%s source=%s reason=no_scoreboard_matchups",
            normalized_sport,
            source,
        )
        return {
            "surface": PLAYER_PROPS_SURFACE,
            "sides": [],
            "pickem_cards": [],
            "prizepicks_cards": [],
            "events_fetched": 0,
            "events_with_both_books": 0,
            "api_requests_remaining": None,
            "diagnostics": {
                "scan_mode": "curated_sniper",
                "scan_scope": "curated",
                "scoreboard_event_count": scoreboard_count,
                "odds_event_count": 0,
                "curated_games": [],
                "matched_event_count": 0,
                "unmatched_game_count": 0,
                "fallback_reason": None,
                "fallback_event_count": 0,
                "events_fetched": 0,
                "events_skipped_pregame": 0,
                "events_with_results": 0,
                "candidate_sides_count": 0,
                "quality_gate_filtered_count": 0,
                "quality_gate_min_reference_bookmakers": min_reference_bookmakers,
                "pickem_quality_gate_min_reference_bookmakers": pickem_min_reference_bookmakers,
                "sides_count": 0,
                "pickem_cards_count": 0,
                "markets_requested": target_markets,
                "prizepicks_status": "disabled",
                "prizepicks_message": None,
                "prizepicks_board_items_count": 0,
                "prizepicks_exact_line_matches_count": 0,
                "prizepicks_unmatched_count": 0,
                "prizepicks_filtered_count": 0,
            },
        }

    events_payload, events_resp = await fetch_events(normalized_sport, source=f"{source}_props_events")
    events = events_payload if isinstance(events_payload, list) else []
    match_details = _build_curated_event_match_details(curated_candidates, events)
    match_details = _prioritize_curated_match_details(
        match_details,
        pregame_cutoff=pregame_cutoff,
        max_games=3,
    )
    matched_events = [
        detail["odds_event"]
        for detail in match_details
        if isinstance(detail.get("odds_event"), dict)
    ]
    scan_scope = "curated"
    fallback_reason: str | None = None
    fallback_event_count = 0
    events_to_scan = matched_events
    if not events_to_scan and events:
        scan_scope = "odds_fallback"
        fallback_reason = (
            "No curated scoreboard games matched the sportsbook event feed, "
            "so the scan widened to upcoming sportsbook events."
        )
        events_to_scan = _select_fallback_odds_events(
            events,
            pregame_cutoff=pregame_cutoff,
            max_events=PLAYER_PROP_FALLBACK_MAX_EVENTS,
        )
        fallback_event_count = len(events_to_scan)
        logger.info(
            "player_props.scan.curated_fallback sport=%s source=%s odds_events=%s fallback_events=%s",
            normalized_sport,
            source,
            len(events),
            fallback_event_count,
        )
    match_details_by_event_id = {
        str(detail.get("odds_event_id") or ""): detail
        for detail in match_details
        if detail.get("odds_event_id")
    }
    logger.info(
        "player_props.scan.matched_events sport=%s source=%s odds_events=%s matched_events=%s",
        normalized_sport,
        source,
        len(events),
        len(matched_events),
    )
    prizepicks_status = "disabled"
    prizepicks_message: str | None = None
    prizepicks_board_items_count = 0
    prizepicks_cards: list[dict] = []
    prizepicks_exact_line_matches_count = 0
    prizepicks_unmatched_count = 0
    prizepicks_filtered_count = 0

    all_sides: list[dict] = []
    events_with_any_book = 0
    events_with_provider_markets = 0
    events_with_supported_book_markets = 0
    events_provider_only = 0
    provider_market_event_counts = _empty_prop_market_event_counts(target_markets)
    supported_book_market_event_counts = _empty_prop_market_event_counts(target_markets)
    remaining: str | None = events_resp.headers.get("x-requests-remaining") or events_resp.headers.get("x-request-remaining")
    events_fetched = 0
    skipped_pregame = 0
    candidate_sides_count = 0
    quality_gate_filtered_count = 0
    pickem_candidates: list[dict] = []
    for event in events_to_scan:
        commence = str(event.get("commence_time") or "")
        if commence:
            commence_dt = _parse_commence_time(commence)
            if commence_dt is not None and commence_dt <= pregame_cutoff:
                skipped_pregame += 1
                continue
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            events_fetched += 1
            event_payload, resp = await _fetch_prop_market_for_event(
                sport=normalized_sport,
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
        market_presence = _collect_prop_market_presence(
            bookmakers=event_payload.get("bookmakers") or [],
            target_markets=target_markets,
        )
        if market_presence["has_provider_markets"]:
            events_with_provider_markets += 1
        if market_presence["has_supported_book_markets"]:
            events_with_supported_book_markets += 1
        if market_presence["has_provider_markets"] and not market_presence["has_supported_book_markets"]:
            events_provider_only += 1
        for market_key in market_presence["provider_markets"]:
            provider_market_event_counts[market_key] = provider_market_event_counts.get(market_key, 0) + 1
        for market_key in market_presence["supported_book_markets"]:
            supported_book_market_event_counts[market_key] = supported_book_market_event_counts.get(market_key, 0) + 1
        event_candidates = _build_prop_side_candidates(
            sport=normalized_sport,
            event_payload=event_payload,
            target_markets=target_markets,
            player_context_lookup=player_context_lookup,
            weight_overrides=weight_overrides,
        )
        candidate_sides_count += len(event_candidates)
        pickem_candidates.extend(event_candidates)
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
        "player_props.scan.completed sport=%s source=%s matched_events=%s events_fetched=%s provider_markets=%s supported_markets=%s events_with_results=%s candidate_sides=%s quality_gate_filtered=%s min_reference_books=%s sides=%s skipped_pregame=%s api_requests_remaining=%s",
        normalized_sport,
        source,
        len(matched_events),
        events_fetched,
        events_with_provider_markets,
        events_with_supported_book_markets,
        events_with_any_book,
        candidate_sides_count,
        quality_gate_filtered_count,
        min_reference_bookmakers,
        len(all_sides),
        skipped_pregame,
        remaining,
    )
    pickem_cards = _build_pickem_cards_from_candidates(
        pickem_candidates,
        min_reference_bookmakers=pickem_min_reference_bookmakers,
    )

    diagnostics = {
        "scan_mode": "curated_sniper",
        "scan_scope": scan_scope,
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
        "fallback_reason": fallback_reason,
        "fallback_event_count": fallback_event_count,
        "events_fetched": events_fetched,
        "events_skipped_pregame": skipped_pregame,
        "events_with_provider_markets": events_with_provider_markets,
        "events_with_supported_book_markets": events_with_supported_book_markets,
        "events_provider_only": events_provider_only,
        "events_with_results": events_with_any_book,
        "candidate_sides_count": candidate_sides_count,
        "quality_gate_filtered_count": quality_gate_filtered_count,
        "quality_gate_min_reference_bookmakers": min_reference_bookmakers,
        "pickem_quality_gate_min_reference_bookmakers": pickem_min_reference_bookmakers,
        "sides_count": len(all_sides),
        "pickem_cards_count": len(pickem_cards),
        "markets_requested": target_markets,
        "provider_market_event_counts": provider_market_event_counts,
        "supported_book_market_event_counts": supported_book_market_event_counts,
        "prizepicks_status": prizepicks_status,
        "prizepicks_message": prizepicks_message,
        "prizepicks_board_items_count": prizepicks_board_items_count,
        "prizepicks_exact_line_matches_count": prizepicks_exact_line_matches_count,
        "prizepicks_unmatched_count": prizepicks_unmatched_count,
        "prizepicks_filtered_count": prizepicks_filtered_count,
    }

    return {
        "surface": PLAYER_PROPS_SURFACE,
        "sides": all_sides,
        "pickem_cards": pickem_cards,
        "prizepicks_cards": prizepicks_cards,
        "events_fetched": events_fetched,
        "events_with_both_books": events_with_any_book,
        "api_requests_remaining": remaining,
        "diagnostics": diagnostics,
    }


async def scan_player_props_for_event_ids(
    *,
    sport: str,
    event_ids: list[str],
    markets: list[str],
    source: str,
) -> dict:
    """Scan player props for an explicit list of Odds API event ids.

    Used by the daily-board publisher (totals-driven selection), so it bypasses
    the ESPN-scoreboard curated matching logic entirely.
    """
    normalized_sport = str(sport or "").strip().lower()
    if normalized_sport not in get_supported_player_prop_sports():
        raise ValueError(
            f"Unsupported player-prop sport '{sport}'. "
            f"Choose from: {', '.join(get_supported_player_prop_sports())}"
        )
    if not event_ids:
        return {
            "surface": PLAYER_PROPS_SURFACE,
            "sides": [],
            "pickem_cards": [],
            "prizepicks_cards": [],
            "events_fetched": 0,
            "events_with_both_books": 0,
            "api_requests_remaining": None,
            "diagnostics": {
                "scan_mode": "selected_events",
                "scan_scope": "explicit_event_ids",
                "scoreboard_event_count": 0,
                "odds_event_count": 0,
                "curated_games": [],
                "matched_event_count": 0,
                "unmatched_game_count": 0,
                "fallback_reason": None,
                "fallback_event_count": 0,
                "events_fetched": 0,
                "events_skipped_pregame": 0,
                "events_with_provider_markets": 0,
                "events_with_supported_book_markets": 0,
                "events_provider_only": 0,
                "events_with_results": 0,
                "candidate_sides_count": 0,
                "quality_gate_filtered_count": 0,
                "quality_gate_min_reference_bookmakers": get_player_prop_min_reference_bookmakers(),
                "pickem_quality_gate_min_reference_bookmakers": get_player_prop_pickem_min_reference_bookmakers(),
                "sides_count": 0,
                "pickem_cards_count": 0,
                "markets_requested": markets,
                "provider_market_event_counts": _empty_prop_market_event_counts(markets),
                "supported_book_market_event_counts": _empty_prop_market_event_counts(markets),
                "prizepicks_status": "disabled",
                "prizepicks_message": None,
                "prizepicks_board_items_count": 0,
                "prizepicks_exact_line_matches_count": 0,
                "prizepicks_unmatched_count": 0,
                "prizepicks_filtered_count": 0,
            },
        }

    target_markets = markets or _resolve_scan_player_prop_markets(normalized_sport)
    min_reference_bookmakers = get_player_prop_min_reference_bookmakers()
    pickem_min_reference_bookmakers = get_player_prop_pickem_min_reference_bookmakers()
    weight_overrides = get_player_prop_weight_overrides()
    pregame_cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)

    all_sides: list[dict] = []
    events_with_any_book = 0
    events_with_provider_markets = 0
    events_with_supported_book_markets = 0
    events_provider_only = 0
    provider_market_event_counts = _empty_prop_market_event_counts(target_markets)
    supported_book_market_event_counts = _empty_prop_market_event_counts(target_markets)
    events_fetched = 0
    skipped_pregame = 0
    candidate_sides_count = 0
    quality_gate_filtered_count = 0
    pickem_candidates: list[dict] = []
    remaining: str | None = None

    for raw_event_id in event_ids:
        event_id = str(raw_event_id or "").strip()
        if not event_id:
            continue
        try:
            events_fetched += 1
            event_payload, resp = await _fetch_prop_market_for_event(
                sport=normalized_sport,
                event_id=event_id,
                markets=target_markets,
                source=source,
            )
            remaining = resp.headers.get("x-requests-remaining") or resp.headers.get("x-request-remaining") or remaining
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                continue
            raise

        commence = str(event_payload.get("commence_time") or "")
        if commence:
            commence_dt = _parse_commence_time(commence)
            if commence_dt is not None and commence_dt <= pregame_cutoff:
                skipped_pregame += 1
                continue

        market_presence = _collect_prop_market_presence(
            bookmakers=event_payload.get("bookmakers") or [],
            target_markets=target_markets,
        )
        if market_presence["has_provider_markets"]:
            events_with_provider_markets += 1
        if market_presence["has_supported_book_markets"]:
            events_with_supported_book_markets += 1
        if market_presence["has_provider_markets"] and not market_presence["has_supported_book_markets"]:
            events_provider_only += 1
        for market_key in market_presence["provider_markets"]:
            provider_market_event_counts[market_key] = provider_market_event_counts.get(market_key, 0) + 1
        for market_key in market_presence["supported_book_markets"]:
            supported_book_market_event_counts[market_key] = supported_book_market_event_counts.get(market_key, 0) + 1

        event_candidates = _build_prop_side_candidates(
            sport=normalized_sport,
            event_payload=event_payload,
            target_markets=target_markets,
            player_context_lookup=None,
            weight_overrides=weight_overrides,
        )
        candidate_sides_count += len(event_candidates)
        pickem_candidates.extend(event_candidates)
        event_sides = _apply_reference_quality_gate(
            event_candidates,
            min_reference_bookmakers=min_reference_bookmakers,
        )
        quality_gate_filtered_count += max(0, len(event_candidates) - len(event_sides))
        if event_sides:
            events_with_any_book += 1
            all_sides.extend(event_sides)
    pickem_cards = _build_pickem_cards_from_candidates(
        pickem_candidates,
        min_reference_bookmakers=pickem_min_reference_bookmakers,
    )

    diagnostics = {
        "scan_mode": "selected_events",
        "scan_scope": "explicit_event_ids",
        "scoreboard_event_count": 0,
        "odds_event_count": 0,
        "curated_games": [],
        "matched_event_count": 0,
        "unmatched_game_count": 0,
        "fallback_reason": None,
        "fallback_event_count": 0,
        "events_fetched": events_fetched,
        "events_skipped_pregame": skipped_pregame,
        "events_with_provider_markets": events_with_provider_markets,
        "events_with_supported_book_markets": events_with_supported_book_markets,
        "events_provider_only": events_provider_only,
        "events_with_results": events_with_any_book,
        "candidate_sides_count": candidate_sides_count,
        "quality_gate_filtered_count": quality_gate_filtered_count,
        "quality_gate_min_reference_bookmakers": min_reference_bookmakers,
        "pickem_quality_gate_min_reference_bookmakers": pickem_min_reference_bookmakers,
        "sides_count": len(all_sides),
        "pickem_cards_count": len(pickem_cards),
        "markets_requested": target_markets,
        "provider_market_event_counts": provider_market_event_counts,
        "supported_book_market_event_counts": supported_book_market_event_counts,
        "prizepicks_status": "disabled",
        "prizepicks_message": None,
        "prizepicks_board_items_count": 0,
        "prizepicks_exact_line_matches_count": 0,
        "prizepicks_unmatched_count": 0,
        "prizepicks_filtered_count": 0,
    }

    return {
        "surface": PLAYER_PROPS_SURFACE,
        "sides": all_sides,
        "pickem_cards": pickem_cards,
        "prizepicks_cards": [],
        "events_fetched": events_fetched,
        "events_with_both_books": events_with_any_book,
        "api_requests_remaining": remaining,
        "diagnostics": diagnostics,
    }


def _merge_api_requests_remaining(values: list[str | None]) -> str | None:
    remaining_values = [value for value in values if value is not None]
    if not remaining_values:
        return None

    numeric_values: list[int] = []
    for value in remaining_values:
        try:
            numeric_values.append(int(str(value)))
        except (TypeError, ValueError):
            return str(value)

    return str(min(numeric_values)) if numeric_values else None


def merge_player_prop_scan_results(
    *results_by_sport: tuple[str, dict],
    scan_mode: str = "multi_sport",
    scan_scope: str = "all_supported_sports",
) -> dict:
    all_sides: list[dict] = []
    all_pickem_cards: list[dict] = []
    all_prizepicks_cards: list[dict] = []
    diagnostics_by_sport: dict[str, dict] = {}
    sports_scanned: list[str] = []
    markets_requested: set[str] = set()
    events_fetched = 0
    events_with_both_books = 0
    events_skipped_pregame = 0
    events_with_results = 0
    events_with_provider_markets = 0
    events_with_supported_book_markets = 0
    events_provider_only = 0
    candidate_sides_count = 0
    quality_gate_filtered_count = 0
    scoreboard_event_count = 0
    odds_event_count = 0
    matched_event_count = 0
    unmatched_game_count = 0
    fallback_event_count = 0
    quality_gate_min_reference_bookmakers = 0
    pickem_quality_gate_min_reference_bookmakers = 0
    fallback_reason_parts: list[str] = []
    curated_games: list[dict] = []
    remaining_values: list[str | None] = []
    provider_market_event_counts: dict[str, int] = {}
    supported_book_market_event_counts: dict[str, int] = {}

    for sport_key, result in results_by_sport:
        sport = str(sport_key or "").strip().lower()
        if not sport or not isinstance(result, dict):
            continue
        sports_scanned.append(sport)
        all_sides.extend([side for side in (result.get("sides") or []) if isinstance(side, dict)])
        all_pickem_cards.extend([card for card in (result.get("pickem_cards") or []) if isinstance(card, dict)])
        all_prizepicks_cards.extend([card for card in (result.get("prizepicks_cards") or []) if isinstance(card, dict)])
        events_fetched += int(result.get("events_fetched") or 0)
        events_with_both_books += int(result.get("events_with_both_books") or 0)
        remaining_values.append(result.get("api_requests_remaining"))

        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
        diagnostics_by_sport[sport] = diagnostics
        markets_requested.update(
            str(market).strip()
            for market in (diagnostics.get("markets_requested") or [])
            if str(market).strip()
        )
        scoreboard_event_count += int(diagnostics.get("scoreboard_event_count") or 0)
        odds_event_count += int(diagnostics.get("odds_event_count") or 0)
        matched_event_count += int(diagnostics.get("matched_event_count") or 0)
        unmatched_game_count += int(diagnostics.get("unmatched_game_count") or 0)
        fallback_event_count += int(diagnostics.get("fallback_event_count") or 0)
        events_skipped_pregame += int(diagnostics.get("events_skipped_pregame") or 0)
        events_with_provider_markets += int(diagnostics.get("events_with_provider_markets") or 0)
        events_with_supported_book_markets += int(diagnostics.get("events_with_supported_book_markets") or 0)
        events_provider_only += int(diagnostics.get("events_provider_only") or 0)
        events_with_results += int(diagnostics.get("events_with_results") or 0)
        candidate_sides_count += int(diagnostics.get("candidate_sides_count") or 0)
        quality_gate_filtered_count += int(diagnostics.get("quality_gate_filtered_count") or 0)
        quality_gate_min_reference_bookmakers = max(
            quality_gate_min_reference_bookmakers,
            int(diagnostics.get("quality_gate_min_reference_bookmakers") or 0),
        )
        pickem_quality_gate_min_reference_bookmakers = max(
            pickem_quality_gate_min_reference_bookmakers,
            int(diagnostics.get("pickem_quality_gate_min_reference_bookmakers") or 0),
        )
        curated_games.extend(
            [game for game in (diagnostics.get("curated_games") or []) if isinstance(game, dict)]
        )
        for market, count in (diagnostics.get("provider_market_event_counts") or {}).items():
            normalized_market = str(market).strip()
            if not normalized_market:
                continue
            provider_market_event_counts[normalized_market] = (
                provider_market_event_counts.get(normalized_market, 0) + int(count or 0)
            )
        for market, count in (diagnostics.get("supported_book_market_event_counts") or {}).items():
            normalized_market = str(market).strip()
            if not normalized_market:
                continue
            supported_book_market_event_counts[normalized_market] = (
                supported_book_market_event_counts.get(normalized_market, 0) + int(count or 0)
            )
        reason = str(diagnostics.get("fallback_reason") or "").strip()
        if reason:
            fallback_reason_parts.append(f"{sport}: {reason}")

    merged_sport = sports_scanned[0] if len(sports_scanned) == 1 else "all"
    diagnostics = {
        "scan_mode": scan_mode,
        "scan_scope": scan_scope,
        "scoreboard_event_count": scoreboard_event_count,
        "odds_event_count": odds_event_count,
        "curated_games": curated_games,
        "matched_event_count": matched_event_count,
        "unmatched_game_count": unmatched_game_count,
        "fallback_reason": " | ".join(fallback_reason_parts) or None,
        "fallback_event_count": fallback_event_count,
        "events_fetched": events_fetched,
        "events_skipped_pregame": events_skipped_pregame,
        "events_with_provider_markets": events_with_provider_markets,
        "events_with_supported_book_markets": events_with_supported_book_markets,
        "events_provider_only": events_provider_only,
        "events_with_results": events_with_results,
        "candidate_sides_count": candidate_sides_count,
        "quality_gate_filtered_count": quality_gate_filtered_count,
        "quality_gate_min_reference_bookmakers": quality_gate_min_reference_bookmakers,
        "pickem_quality_gate_min_reference_bookmakers": pickem_quality_gate_min_reference_bookmakers,
        "sides_count": len(all_sides),
        "pickem_cards_count": len(all_pickem_cards),
        "markets_requested": sorted(markets_requested),
        "provider_market_event_counts": dict(sorted(provider_market_event_counts.items())),
        "supported_book_market_event_counts": dict(sorted(supported_book_market_event_counts.items())),
        "prizepicks_status": "disabled",
        "prizepicks_message": None,
        "prizepicks_board_items_count": len(all_prizepicks_cards),
        "prizepicks_exact_line_matches_count": 0,
        "prizepicks_unmatched_count": 0,
        "prizepicks_filtered_count": 0,
        "sports_scanned": sports_scanned,
        "by_sport": diagnostics_by_sport,
    }
    return {
        "surface": PLAYER_PROPS_SURFACE,
        "sport": merged_sport,
        "sides": all_sides,
        "pickem_cards": all_pickem_cards,
        "prizepicks_cards": all_prizepicks_cards,
        "events_fetched": events_fetched,
        "events_with_both_books": events_with_both_books,
        "api_requests_remaining": _merge_api_requests_remaining(remaining_values),
        "diagnostics": diagnostics,
    }


async def get_cached_or_scan_player_props(sport: str, source: str = "unknown") -> dict:
    normalized_sport = str(sport or "").strip().lower()
    if normalized_sport not in get_supported_player_prop_sports():
        raise ValueError(
            f"Unsupported player-prop sport '{sport}'. "
            f"Choose from: {', '.join(get_supported_player_prop_sports())}"
        )
    slot = _prop_cache_slot(normalized_sport)
    bypass_cache = _should_bypass_prop_cache(source)
    if normalized_sport not in _props_locks:
        _props_locks[normalized_sport] = asyncio.Lock()
    async with _props_locks[normalized_sport]:
        now = time.time()
        if not bypass_cache:
            shared_entry = get_scan_cache(slot)
            if isinstance(shared_entry, dict):
                fetched_at = shared_entry.get("fetched_at")
                if isinstance(fetched_at, (int, float)) and (now - fetched_at) < CACHE_TTL_SECONDS:
                    _props_cache[slot] = shared_entry
                    return {**shared_entry, "cache_hit": True}

            if slot in _props_cache:
                entry = _props_cache[slot]
                if (now - entry["fetched_at"]) < CACHE_TTL_SECONDS:
                    return {**entry, "cache_hit": True}

        result = await scan_player_props(normalized_sport, source=source)
        result["fetched_at"] = now
        _props_cache[slot] = result
        set_scan_cache(slot, result, CACHE_TTL_SECONDS)
        return {**result, "cache_hit": False}
