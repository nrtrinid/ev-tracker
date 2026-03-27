import logging
import asyncio
import time
from typing import Any

import httpx


PRIZEPICKS_API_URL = "https://api.prizepicks.com/projections"
PRIZEPICKS_NBA_LEAGUE_ID = 7
PRIZEPICKS_STANDARD_ODDS_TYPE = "standard"
PRIZEPICKS_SUPPORTED_MARKETS: dict[str, str] = {
    "Points": "player_points",
    "Rebounds": "player_rebounds",
    "Assists": "player_assists",
    "3-PT Made": "player_threes",
}

logger = logging.getLogger("ev_tracker")
_prizepicks_board_cache: dict[str, Any] = {"fetched_at": 0.0, "board": []}
PRIZEPICKS_BOARD_CACHE_TTL_SECONDS = 300


def _included_key(item_type: str | None, item_id: str | None) -> str:
    return f"{str(item_type or '').strip()}:{str(item_id or '').strip()}"


def _build_included_index(included: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in included:
        if not isinstance(item, dict):
            continue
        key = _included_key(item.get("type"), item.get("id"))
        if key != ":":
            index[key] = item
    return index


def _resolve_related(
    included_index: dict[str, dict[str, Any]],
    relationships: dict[str, Any],
    relationship_key: str,
) -> dict[str, Any] | None:
    relation = relationships.get(relationship_key)
    if not isinstance(relation, dict):
        return None
    relation_data = relation.get("data")
    if not isinstance(relation_data, dict):
        return None
    return included_index.get(_included_key(relation_data.get("type"), relation_data.get("id")))


def _canonical_token(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _team_full_name(team_item: dict[str, Any] | None) -> str | None:
    if not isinstance(team_item, dict):
        return None
    attributes = team_item.get("attributes")
    if not isinstance(attributes, dict):
        return None
    market = str(attributes.get("market") or "").strip()
    name = str(attributes.get("name") or "").strip()
    full_name = f"{market} {name}".strip()
    return full_name or str(attributes.get("abbreviation") or "").strip() or None


def _normalize_prizepicks_projection(
    projection: dict[str, Any],
    included_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(projection, dict):
        return None

    attributes = projection.get("attributes")
    relationships = projection.get("relationships")
    if not isinstance(attributes, dict) or not isinstance(relationships, dict):
        return None

    if str(attributes.get("odds_type") or "").strip().lower() != PRIZEPICKS_STANDARD_ODDS_TYPE:
        return None
    if str(attributes.get("projection_type") or "").strip() != "Single Stat":
        return None

    stat_type = _resolve_related(included_index, relationships, "stat_type")
    stat_attributes = stat_type.get("attributes") if isinstance(stat_type, dict) else None
    stat_name = str((stat_attributes or {}).get("name") or "").strip()
    market_key = PRIZEPICKS_SUPPORTED_MARKETS.get(stat_name)
    if not market_key:
        return None

    player = _resolve_related(included_index, relationships, "new_player")
    player_attributes = player.get("attributes") if isinstance(player, dict) else None
    if not isinstance(player_attributes, dict):
        return None

    if bool(player_attributes.get("combo")):
        return None

    player_name = str(player_attributes.get("display_name") or player_attributes.get("name") or "").strip()
    if not player_name:
        return None

    game = _resolve_related(included_index, relationships, "game")
    game_attributes = game.get("attributes") if isinstance(game, dict) else None
    game_relationships = game.get("relationships") if isinstance(game, dict) else None
    if not isinstance(game_attributes, dict) or not isinstance(game_relationships, dict):
        return None

    home_team_item = _resolve_related(included_index, game_relationships, "home_team_data")
    away_team_item = _resolve_related(included_index, game_relationships, "away_team_data")
    home_team = _team_full_name(home_team_item)
    away_team = _team_full_name(away_team_item)
    if not home_team or not away_team:
        return None

    player_team_data = _resolve_related(included_index, player.get("relationships") or {}, "team_data") if isinstance(player, dict) else None
    player_team_name = (
        str(player_attributes.get("team_name") or "").strip()
        or _team_full_name(player_team_data)
        or None
    )
    player_team_abbreviation = str(player_attributes.get("team") or "").strip() or None

    home_abbreviation = str(((home_team_item or {}).get("attributes") or {}).get("abbreviation") or "").strip()
    away_abbreviation = str(((away_team_item or {}).get("attributes") or {}).get("abbreviation") or "").strip()

    player_team = player_team_name
    opponent = None
    if player_team_abbreviation and player_team_abbreviation == home_abbreviation:
        player_team = home_team
        opponent = away_team
    elif player_team_abbreviation and player_team_abbreviation == away_abbreviation:
        player_team = away_team
        opponent = home_team
    elif _canonical_token(player_team_name) == _canonical_token(home_team):
        player_team = home_team
        opponent = away_team
    elif _canonical_token(player_team_name) == _canonical_token(away_team):
        player_team = away_team
        opponent = home_team

    try:
        line_value = float(attributes.get("line_score"))
    except (TypeError, ValueError):
        return None

    commence_time = (
        str(game_attributes.get("start_time") or "").strip()
        or str(attributes.get("start_time") or "").strip()
    )
    event_name = f"{away_team} @ {home_team}"

    return {
        "projection_id": str(projection.get("id") or "").strip() or None,
        "player_name": player_name,
        "participant_id": str(player_attributes.get("ppid") or player.get("id") or "").strip() or None,
        "team": player_team,
        "opponent": opponent,
        "team_key": _canonical_token(player_team),
        "player_key": _canonical_token(player_name),
        "market_key": market_key,
        "market": market_key,
        "line_value": line_value,
        "event": event_name,
        "event_key": f"{_canonical_token(away_team)}|{_canonical_token(home_team)}",
        "event_id": str(game_attributes.get("external_game_id") or game.get("id") or "").strip() or None,
        "commence_time": commence_time,
        "home_team": home_team,
        "away_team": away_team,
        "status": str(attributes.get("status") or game_attributes.get("status") or "").strip() or None,
    }


async def fetch_prizepicks_nba_board() -> list[dict[str, Any]]:
    params = {
        "league_id": PRIZEPICKS_NBA_LEAGUE_ID,
        "per_page": 250,
        "single_stat": "true",
    }
    now = time.time()
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            from services.http_client import request_with_retries

            response = await request_with_retries("GET", PRIZEPICKS_API_URL, params=params, timeout=20.0, retries=1)
            response.raise_for_status()
            payload = response.json()
            break
        except Exception as exc:
            last_error = exc
            if attempt == 1:
                cached_board = _prizepicks_board_cache.get("board")
                cached_at = float(_prizepicks_board_cache.get("fetched_at") or 0.0)
                if isinstance(cached_board, list) and cached_board and (now - cached_at) < PRIZEPICKS_BOARD_CACHE_TTL_SECONDS:
                    logger.warning(
                        "prizepicks.fetch.cache_fallback error_class=%s error=%s age_seconds=%.2f board_items=%s",
                        type(exc).__name__,
                        exc,
                        now - cached_at,
                        len(cached_board),
                    )
                    return cached_board
                raise
            await asyncio.sleep(0.4)
    else:
        raise last_error or RuntimeError("PrizePicks board fetch failed")

    data = payload.get("data")
    included = payload.get("included")
    if not isinstance(data, list) or not isinstance(included, list):
        logger.warning("prizepicks.fetch.invalid_payload")
        return []

    included_index = _build_included_index(included)
    normalized: list[dict[str, Any]] = []
    for projection in data:
        normalized_projection = _normalize_prizepicks_projection(projection, included_index)
        if normalized_projection:
            normalized.append(normalized_projection)
    _prizepicks_board_cache["fetched_at"] = now
    _prizepicks_board_cache["board"] = normalized
    return normalized
