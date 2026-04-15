from __future__ import annotations

import os


PLAYER_PROP_SUPPORTED_SPORTS = [
    "basketball_nba",
    "baseball_mlb",
]
PLAYER_PROP_INCLUDE_SHADOW_MARKETS_ENV = "PLAYER_PROP_INCLUDE_SHADOW_MARKETS"
PLAYER_PROP_INCLUDE_ALTERNATE_MARKETS_ENV = "PLAYER_PROP_INCLUDE_ALTERNATE_MARKETS"

PLAYER_PROP_MARKET_SPORTS: dict[str, tuple[str, ...]] = {
    "player_points": ("basketball_nba",),
    "player_rebounds": ("basketball_nba",),
    "player_assists": ("basketball_nba",),
    "player_points_rebounds_assists": ("basketball_nba",),
    "player_threes": ("basketball_nba",),
    "pitcher_strikeouts": ("baseball_mlb",),
    "pitcher_strikeouts_alternate": ("baseball_mlb",),
    "batter_total_bases": ("baseball_mlb",),
    "batter_total_bases_alternate": ("baseball_mlb",),
    "batter_hits": ("baseball_mlb",),
    "batter_hits_alternate": ("baseball_mlb",),
    "batter_hits_runs_rbis": ("baseball_mlb",),
    "batter_home_runs": ("baseball_mlb",),
    "batter_strikeouts": ("baseball_mlb",),
    "batter_strikeouts_alternate": ("baseball_mlb",),
}

PLAYER_PROP_DEFAULT_MARKETS_BY_SPORT: dict[str, list[str]] = {
    "basketball_nba": [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_points_rebounds_assists",
        "player_threes",
    ],
    "baseball_mlb": [
        "pitcher_strikeouts",
        "batter_total_bases",
        "batter_hits",
        "batter_hits_runs_rbis",
        "batter_strikeouts",
        "batter_home_runs",
    ],
}

PLAYER_PROP_SHADOW_MARKETS_BY_SPORT: dict[str, list[str]] = {
    "basketball_nba": [],
    "baseball_mlb": [],
}

PLAYER_PROP_ALTERNATE_MARKETS_BY_SPORT: dict[str, list[str]] = {
    "basketball_nba": [],
    "baseball_mlb": [
        "pitcher_strikeouts_alternate",
        "batter_total_bases_alternate",
        "batter_hits_alternate",
        "batter_strikeouts_alternate",
    ],
}

PLAYER_PROP_ALL_MARKETS = list(PLAYER_PROP_MARKET_SPORTS.keys())


def _normalized_env_tokens(raw: str | None) -> set[str]:
    return {
        str(token or "").strip().lower()
        for token in str(raw or "").split(",")
        if str(token or "").strip()
    }


def _dedupe_markets(markets: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for market in markets:
        normalized = str(market or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def get_supported_player_prop_sports() -> list[str]:
    return list(PLAYER_PROP_SUPPORTED_SPORTS)


def get_supported_player_prop_markets(sport: str | None = None) -> list[str]:
    normalized_sport = str(sport or "").strip().lower()
    if not normalized_sport:
        return list(PLAYER_PROP_ALL_MARKETS)
    return [
        market_key
        for market_key, sports in PLAYER_PROP_MARKET_SPORTS.items()
        if normalized_sport in sports
    ]


def get_player_prop_default_markets(sport: str | None = None) -> list[str]:
    normalized_sport = str(sport or "").strip().lower()
    if not normalized_sport:
        normalized_sport = "basketball_nba"
    defaults = PLAYER_PROP_DEFAULT_MARKETS_BY_SPORT.get(normalized_sport)
    if defaults:
        return list(defaults)
    return get_supported_player_prop_markets(normalized_sport)


def get_player_prop_shadow_markets(sport: str | None = None) -> list[str]:
    normalized_sport = str(sport or "").strip().lower()
    if not normalized_sport:
        return []
    return list(PLAYER_PROP_SHADOW_MARKETS_BY_SPORT.get(normalized_sport) or [])


def get_player_prop_alternate_markets(sport: str | None = None) -> list[str]:
    normalized_sport = str(sport or "").strip().lower()
    if not normalized_sport:
        return []
    return list(PLAYER_PROP_ALTERNATE_MARKETS_BY_SPORT.get(normalized_sport) or [])


def _get_enabled_optional_player_prop_markets(
    *,
    sport: str | None,
    markets: list[str],
    env_var: str,
) -> list[str]:
    normalized_sport = str(sport or "").strip().lower()
    if not markets:
        return []

    requested_tokens = _normalized_env_tokens(os.getenv(env_var, ""))
    if not requested_tokens:
        return []

    if requested_tokens & {"1", "true", "yes", "all"}:
        return list(markets)
    if normalized_sport and normalized_sport in requested_tokens:
        return list(markets)

    return [market for market in markets if market in requested_tokens]


def get_enabled_player_prop_shadow_markets(sport: str | None = None) -> list[str]:
    return _get_enabled_optional_player_prop_markets(
        sport=sport,
        markets=get_player_prop_shadow_markets(sport),
        env_var=PLAYER_PROP_INCLUDE_SHADOW_MARKETS_ENV,
    )


def get_enabled_player_prop_alternate_markets(sport: str | None = None) -> list[str]:
    return _get_enabled_optional_player_prop_markets(
        sport=sport,
        markets=get_player_prop_alternate_markets(sport),
        env_var=PLAYER_PROP_INCLUDE_ALTERNATE_MARKETS_ENV,
    )


def get_player_prop_markets(sport: str | None = None) -> list[str]:
    raw = os.getenv("PLAYER_PROP_MARKETS", "").strip()
    defaults = _dedupe_markets(
        [
            *get_player_prop_default_markets(sport),
            *get_enabled_player_prop_shadow_markets(sport),
            *get_enabled_player_prop_alternate_markets(sport),
        ]
    )
    allowed_markets = {market: market for market in get_supported_player_prop_markets(sport)}
    if not raw:
        return defaults

    requested = [item.strip() for item in raw.split(",") if item.strip()]
    selected = [allowed_markets[item] for item in requested if item in allowed_markets]
    return _dedupe_markets(selected) or defaults
