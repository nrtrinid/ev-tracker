"""
Auto-settlement for player props and parlays whose legs are ML + props.

Uses provider-first completed events for game matching plus sport-specific
boxscore providers:
- NBA: ESPN scoreboard + game summary
- MLB: MLB StatsAPI schedule + boxscore
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

_ESPN_RESOLVE_LOG_CAP = 80
_BOXSCORE_RESOLVE_LOG_CAP = 120

from services.espn_scoreboard import (
    _canonical_team_name,
    _extract_matchup,
    build_auto_settle_scoreboard_dates,
    build_scoreboard_date_window,
    fetch_nba_game_summary,
    fetch_nba_scoreboard_for_dates,
)
from services.http_client import request_with_retries

MLB_STATSAPI_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_STATSAPI_BOXSCORE_URL_TEMPLATE = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"

PROP_MARKET_TO_ESPN_STAT = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_points_rebounds_assists": "PTS_REB_AST",
    "player_threes": "3PM",
}
PROP_MARKET_TO_MLB_STAT = {
    "pitcher_strikeouts": "P_SO",
    "pitcher_strikeouts_alternate": "P_SO",
    "batter_total_bases": "B_TB",
    "batter_total_bases_alternate": "B_TB",
    "batter_hits": "B_H",
    "batter_hits_alternate": "B_H",
    "batter_hits_runs_rbis": "B_H_R_RBI",
    "batter_home_runs": "B_HR",
    "batter_strikeouts": "B_SO",
    "batter_strikeouts_alternate": "B_SO",
}

NBA_SPORT_KEY = "basketball_nba"
MLB_SPORT_KEY = "baseball_mlb"
SUPPORTED_PROP_BOX_SCORE_SPORTS = {NBA_SPORT_KEY, MLB_SPORT_KEY}
AUTO_SETTLE_PROP_MARKETS_BY_SPORT: dict[str, set[str]] = {
    NBA_SPORT_KEY: set(PROP_MARKET_TO_ESPN_STAT.keys()),
    MLB_SPORT_KEY: set(PROP_MARKET_TO_MLB_STAT.keys()),
}

# Reject ESPN matches whose listed start is too far from Odds API commence (postponements, wrong game).
_MAX_KICKOFF_DRIFT = timedelta(hours=72)


@dataclass
class EspnResolveResult:
    """Outcome of mapping an Odds API completed event to an ESPN game id."""

    espn_event_id: str | None
    odds_event_id: str | None = None
    matchup: str = ""
    score_matched: bool = False
    fallback_used: bool = False
    confidence_tier: str = "unresolved"
    date_delta_hours: float | None = None
    home_away_tiebreak_used: bool = False
    from_cache: bool = False


@dataclass
class BoxscoreResolveResult:
    """Outcome of mapping an Odds API completed event to a provider boxscore id."""

    provider: str
    provider_event_id: str | None
    odds_event_id: str | None = None
    matchup: str = ""
    score_matched: bool = False
    fallback_used: bool = False
    confidence_tier: str = "unresolved"
    date_delta_hours: float | None = None
    home_away_tiebreak_used: bool = False
    from_cache: bool = False


def get_auto_settle_supported_prop_markets(sport: str | None = None) -> set[str]:
    normalized_sport = str(sport or "").strip().lower()
    if not normalized_sport:
        return {
            market
            for markets in AUTO_SETTLE_PROP_MARKETS_BY_SPORT.values()
            for market in markets
        }
    return set(AUTO_SETTLE_PROP_MARKETS_BY_SPORT.get(normalized_sport) or set())


def is_auto_settle_supported_prop_market(sport: str | None, market_key: str | None) -> bool:
    normalized_sport = str(sport or "").strip().lower()
    normalized_market = str(market_key or "").strip()
    return bool(normalized_sport and normalized_market and normalized_market in get_auto_settle_supported_prop_markets(normalized_sport))


def create_prop_settle_telemetry() -> dict[str, Any]:
    return {
        "boxscore_resolve_log": [],
        "espn_resolve_log": [],
        "espn_resolve_score_verified": 0,
        "espn_resolve_matchup_plus_time": 0,
        "espn_resolve_fallback_time_only": 0,
        "props_espn_resolved": 0,
        "mlb_resolve_log": [],
        "mlb_resolve_score_verified": 0,
        "mlb_resolve_matchup_plus_time": 0,
        "mlb_resolve_fallback_time_only": 0,
        "props_mlb_resolved": 0,
        "props_player_match_exact": 0,
        "props_player_match_fuzzy": 0,
        "props_player_not_found": 0,
        "props_stat_missing": 0,
        "props_boxscore_fetch_failed": 0,
    }


def _telemetry_bump(telemetry: dict[str, Any] | None, key: str, delta: int = 1) -> None:
    if telemetry is None:
        return
    telemetry[key] = int(telemetry.get(key) or 0) + delta


def _telemetry_append_resolve_log(
    telemetry: dict[str, Any] | None,
    row: dict[str, Any],
) -> None:
    if telemetry is None:
        return
    log = telemetry.setdefault("espn_resolve_log", [])
    if len(log) < _ESPN_RESOLVE_LOG_CAP:
        log.append(row)


def _telemetry_append_boxscore_log(
    telemetry: dict[str, Any] | None,
    row: dict[str, Any],
) -> None:
    if telemetry is None:
        return
    log = telemetry.setdefault("boxscore_resolve_log", [])
    if len(log) < _BOXSCORE_RESOLVE_LOG_CAP:
        log.append(row)


def _record_espn_resolve_telemetry(
    telemetry: dict[str, Any] | None,
    result: EspnResolveResult,
    *,
    context: str,
    ref_id: str | None,
) -> None:
    if telemetry is None or not result.espn_event_id:
        return
    _telemetry_bump(telemetry, "props_espn_resolved")
    tier_key = {
        "score_verified": "espn_resolve_score_verified",
        "matchup_plus_time": "espn_resolve_matchup_plus_time",
        "fallback_time_only": "espn_resolve_fallback_time_only",
    }.get(result.confidence_tier)
    if tier_key:
        _telemetry_bump(telemetry, tier_key)
    _telemetry_append_boxscore_log(
        telemetry,
        {
            "provider": "espn",
            "context": context,
            "ref_id": ref_id,
            "odds_event_id": result.odds_event_id,
            "provider_event_id": result.espn_event_id,
            "matchup": result.matchup,
            "score_matched": result.score_matched,
            "fallback_used": result.fallback_used,
            "confidence_tier": result.confidence_tier,
            "date_delta_hours": result.date_delta_hours,
            "home_away_tiebreak_used": result.home_away_tiebreak_used,
            "from_cache": result.from_cache,
        },
    )
    _telemetry_append_resolve_log(
        telemetry,
        {
            "context": context,
            "ref_id": ref_id,
            "odds_event_id": result.odds_event_id,
            "espn_event_id": result.espn_event_id,
            "matchup": result.matchup,
            "score_matched": result.score_matched,
            "fallback_used": result.fallback_used,
            "confidence_tier": result.confidence_tier,
            "date_delta_hours": result.date_delta_hours,
            "home_away_tiebreak_used": result.home_away_tiebreak_used,
            "from_cache": result.from_cache,
        },
    )


def _record_mlb_resolve_telemetry(
    telemetry: dict[str, Any] | None,
    result: BoxscoreResolveResult,
    *,
    context: str,
    ref_id: str | None,
) -> None:
    if telemetry is None or not result.provider_event_id:
        return
    _telemetry_bump(telemetry, "props_mlb_resolved")
    tier_key = {
        "score_verified": "mlb_resolve_score_verified",
        "matchup_plus_time": "mlb_resolve_matchup_plus_time",
        "fallback_time_only": "mlb_resolve_fallback_time_only",
    }.get(result.confidence_tier)
    if tier_key:
        _telemetry_bump(telemetry, tier_key)
    row = {
        "provider": "mlb_statsapi",
        "context": context,
        "ref_id": ref_id,
        "odds_event_id": result.odds_event_id,
        "provider_event_id": result.provider_event_id,
        "matchup": result.matchup,
        "score_matched": result.score_matched,
        "fallback_used": result.fallback_used,
        "confidence_tier": result.confidence_tier,
        "date_delta_hours": result.date_delta_hours,
        "home_away_tiebreak_used": result.home_away_tiebreak_used,
        "from_cache": result.from_cache,
    }
    _telemetry_append_boxscore_log(telemetry, row)
    log = telemetry.setdefault("mlb_resolve_log", [])
    if len(log) < _BOXSCORE_RESOLVE_LOG_CAP:
        log.append(row)


def _log_espn_resolve_line(
    result: EspnResolveResult,
    *,
    context: str,
    ref_id: str | None,
) -> None:
    if not result.espn_event_id:
        return
    print(
        "[Auto-Settler:props:espn_resolve] "
        f"context={context} ref_id={ref_id} "
        f"odds_event_id={result.odds_event_id} espn_event_id={result.espn_event_id} "
        f"matchup={result.matchup!r} score_matched={result.score_matched} "
        f"fallback_used={result.fallback_used} confidence_tier={result.confidence_tier} "
        f"date_delta_hours={result.date_delta_hours} home_away_tiebreak_used="
        f"{result.home_away_tiebreak_used} from_cache={result.from_cache}"
    )


def _normalize_player_name(name: str | None) -> str:
    if not name:
        return ""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


# Trailing tokens removed so "Robert Williams" matches ESPN "Robert Williams III".
_GEN_SUFFIXES: tuple[str, ...] = (
    "iii",
    "ii",
    "iv",
    "viii",
    "vii",
    "vi",
    "ix",
    "xii",
    "xi",
    "jr",
    "sr",
    "sjr",
)


def _strip_generational_suffix(compact: str) -> str:
    """Remove Jr / Sr / II / III / … from alphanumeric compact names (longest first)."""
    s = (compact or "").lower()
    if not s:
        return ""
    while True:
        stripped = False
        for p in _GEN_SUFFIXES:
            lp = len(p)
            if len(s) > lp + 2 and s.endswith(p):
                s = s[:-lp]
                stripped = True
                break
        if not stripped:
            break
    return s


def _token_parts(raw: str | None) -> list[str]:
    """Split a display name into alphanumeric tokens (drops generational noise)."""
    if not raw:
        return []
    parts = re.split(r"[\s.\-\',]+", str(raw).strip())
    noise = {"jr", "sr", "ii", "iii", "iv", "v", "vi"}
    out: list[str] = []
    for p in parts:
        t = "".join(c for c in p.lower() if c.isalnum())
        if t and t not in noise:
            out.append(t)
    return out


def _string_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _match_player_stat_key(
    norm: str,
    raw_name: str | None,
    stat_map: dict[str, dict[str, float]],
) -> tuple[dict[str, float] | None, str]:
    """
    Map bet participant string to a normalized boxscore player row.

    Returns (player_stats, match_kind) where match_kind is exact|fuzzy|none.
    """
    if norm in stat_map:
        return stat_map[norm], "exact"

    ns = _strip_generational_suffix(norm)

    for k, v in stat_map.items():
        if _strip_generational_suffix(k) == ns and len(ns) >= 4:
            return v, "fuzzy"

    for k, v in stat_map.items():
        if k.endswith(norm) or norm.endswith(k):
            if len(k) >= 4 and len(norm) >= 4:
                return v, "fuzzy"

    parts = _token_parts(raw_name)
    if len(parts) >= 2 and len(parts[0]) == 1 and len(parts[-1]) >= 4:
        initial = parts[0][0]
        last = parts[-1]
        matches = [
            k
            for k in stat_map
            if k.endswith(last) and len(k) >= len(last) + 1 and k.startswith(initial)
        ]
        if len(matches) == 1:
            return stat_map[matches[0]], "fuzzy"

    candidates: list[tuple[float, str, dict[str, float]]] = []
    for k, v in stat_map.items():
        ks = _strip_generational_suffix(k)
        r = _string_similarity(ns, ks)
        if r >= 0.91 and min(len(ns), len(ks)) >= 6:
            candidates.append((r, k, v))
    if len(candidates) == 1:
        return candidates[0][2], "fuzzy"
    if len(candidates) > 1:
        candidates.sort(key=lambda x: -x[0])
        best_r, _, best_v = candidates[0]
        second_r = candidates[1][0]
        if best_r - second_r >= 0.02:
            return best_v, "fuzzy"

    return None, "none"


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


def _event_completed(event: dict[str, Any]) -> bool:
    competitions = event.get("competitions") or []
    if not isinstance(competitions, list) or not competitions:
        return False
    status = (competitions[0] or {}).get("status") or {}
    type_info = status.get("type") or {}
    return bool(type_info.get("completed"))


def _odds_final_scores_by_team_key(event: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in event.get("scores") or []:
        if not isinstance(row, dict):
            continue
        try:
            name = str(row.get("name") or "").strip()
            raw = row.get("score")
            if not name or raw is None:
                continue
            val = float(str(raw).strip())
            key = _canonical_team_name(name)
            if key:
                out[key] = val
        except (TypeError, ValueError):
            continue
    return out


def _espn_final_scores_by_team_key(event: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    competitions = event.get("competitions") or []
    if not isinstance(competitions, list) or not competitions:
        return out
    competitors = (competitions[0] or {}).get("competitors") or []
    if not isinstance(competitors, list):
        return out
    for c in competitors:
        if not isinstance(c, dict):
            continue
        team = c.get("team") or {}
        if not isinstance(team, dict):
            continue
        display = str(team.get("displayName") or "").strip()
        if not display:
            continue
        raw = c.get("score")
        if raw is None:
            continue
        try:
            val = float(str(raw).strip())
        except (TypeError, ValueError):
            continue
        key = _canonical_team_name(display)
        if key:
            out[key] = val
    return out


def _espn_home_away_matches_odds(
    espn_event: dict[str, Any],
    odds_home: str,
    odds_away: str,
) -> bool:
    """True if ESPN home/away team labels match Odds API home_team/away_team (canonical)."""
    matchup = _extract_matchup(espn_event)
    if not matchup:
        return False
    oh = _canonical_team_name(odds_home)
    oa = _canonical_team_name(odds_away)
    eh = str(matchup.get("home_team_key") or "")
    ea = str(matchup.get("away_team_key") or "")
    return bool(oh and oa and eh and ea and oh == eh and oa == ea)


def _scores_align_odds_espn(
    odds_event: dict[str, Any],
    espn_event: dict[str, Any],
    *,
    tolerance: float = 0.51,
) -> bool:
    """True if ESPN final scores match Odds API for both teams (when Odds has full scores)."""
    om = _odds_final_scores_by_team_key(odds_event)
    em = _espn_final_scores_by_team_key(espn_event)
    if len(om) < 2 or len(em) < 2:
        return True
    for k, v in om.items():
        if k not in em:
            return False
        if abs(float(em[k]) - float(v)) > tolerance:
            return False
    return True


def _parse_espn_event_datetime(event: dict[str, Any]) -> datetime | None:
    ds = str(event.get("date") or "").strip()
    if not ds:
        return None
    try:
        normalized = ds.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_mlb_schedule_date_window(now: datetime | None = None) -> list[str]:
    anchor = now or datetime.now(timezone.utc)
    anchor_date = anchor.date()
    return [
        (anchor_date - timedelta(days=1)).isoformat(),
        anchor_date.isoformat(),
        (anchor_date + timedelta(days=1)).isoformat(),
    ]


def build_auto_settle_mlb_schedule_dates(
    commence_anchor: datetime | None,
    *,
    now: datetime | None = None,
    days_around_commence: int = 4,
) -> list[str]:
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ordered: list[str] = []
    seen: set[str] = set()

    def _push(value: str) -> None:
        if value not in seen:
            seen.add(value)
            ordered.append(value)

    for value in build_mlb_schedule_date_window(anchor):
        _push(value)

    if commence_anchor is not None:
        commence_date = commence_anchor.astimezone(timezone.utc).date()
        for delta in range(-days_around_commence, days_around_commence + 1):
            _push((commence_date + timedelta(days=delta)).isoformat())

    return ordered


async def fetch_mlb_schedule_for_date(date_value: str) -> dict[str, Any]:
    resp = await request_with_retries(
        "GET",
        MLB_STATSAPI_SCHEDULE_URL,
        params={"sportId": 1, "date": date_value},
        timeout=15.0,
        retries=2,
    )
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


async def fetch_mlb_schedule_for_dates(date_strings: list[str]) -> dict[str, Any]:
    merged_games: list[dict[str, Any]] = []
    seen_game_pks: set[str] = set()

    for date_value in date_strings:
        payload = await fetch_mlb_schedule_for_date(date_value)
        dates = payload.get("dates") or []
        if not isinstance(dates, list):
            continue
        for date_block in dates:
            if not isinstance(date_block, dict):
                continue
            games = date_block.get("games") or []
            if not isinstance(games, list):
                continue
            for game in games:
                if not isinstance(game, dict):
                    continue
                game_pk = str(game.get("gamePk") or "").strip()
                if game_pk and game_pk in seen_game_pks:
                    continue
                if game_pk:
                    seen_game_pks.add(game_pk)
                merged_games.append(game)

    merged_games.sort(key=lambda game: str(game.get("gameDate") or ""))
    return {"games": merged_games}


async def fetch_mlb_game_boxscore(game_pk: str) -> dict[str, Any]:
    normalized_game_pk = str(game_pk or "").strip()
    if not normalized_game_pk:
        return {}
    resp = await request_with_retries(
        "GET",
        MLB_STATSAPI_BOXSCORE_URL_TEMPLATE.format(game_pk=normalized_game_pk),
        timeout=15.0,
        retries=2,
    )
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def _mlb_event_completed(game: dict[str, Any]) -> bool:
    status = game.get("status") or {}
    if not isinstance(status, dict):
        return False
    abstract = str(status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailedState") or "").strip().lower()
    coded = str(status.get("codedGameState") or status.get("statusCode") or "").strip().upper()
    return abstract == "final" or detailed == "final" or coded == "F"


def _mlb_extract_matchup(game: dict[str, Any]) -> dict[str, str] | None:
    teams = game.get("teams") or {}
    if not isinstance(teams, dict):
        return None
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    away_team = away.get("team") or {}
    home_team = home.get("team") or {}
    away_name = str(away_team.get("name") or "").strip()
    home_name = str(home_team.get("name") or "").strip()
    if not away_name or not home_name:
        return None
    return {
        "event_id": str(game.get("gamePk") or "").strip(),
        "home_team": home_name,
        "home_team_id": str(home_team.get("id") or "").strip(),
        "away_team": away_name,
        "away_team_id": str(away_team.get("id") or "").strip(),
        "home_team_key": _canonical_team_name(home_name, sport=MLB_SPORT_KEY),
        "away_team_key": _canonical_team_name(away_name, sport=MLB_SPORT_KEY),
    }


def _mlb_final_scores_by_team_key(game: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    matchup = _mlb_extract_matchup(game)
    if not matchup:
        return out
    teams = game.get("teams") or {}
    if not isinstance(teams, dict):
        return out
    for side, team_name in (("home", matchup["home_team"]), ("away", matchup["away_team"])):
        row = teams.get(side) or {}
        if not isinstance(row, dict):
            continue
        raw_score = row.get("score")
        if raw_score is None:
            continue
        try:
            val = float(str(raw_score).strip())
        except (TypeError, ValueError):
            continue
        key = _canonical_team_name(team_name, sport=MLB_SPORT_KEY)
        if key:
            out[key] = val
    return out


def _mlb_home_away_matches_odds(
    mlb_game: dict[str, Any],
    odds_home: str,
    odds_away: str,
) -> bool:
    matchup = _mlb_extract_matchup(mlb_game)
    if not matchup:
        return False
    oh = _canonical_team_name(odds_home, sport=MLB_SPORT_KEY)
    oa = _canonical_team_name(odds_away, sport=MLB_SPORT_KEY)
    mh = str(matchup.get("home_team_key") or "")
    ma = str(matchup.get("away_team_key") or "")
    return bool(oh and oa and mh and ma and oh == mh and oa == ma)


def _scores_align_odds_mlb(
    odds_event: dict[str, Any],
    mlb_game: dict[str, Any],
    *,
    tolerance: float = 0.51,
) -> bool:
    odds_scores = _odds_final_scores_by_team_key(odds_event)
    mlb_scores = _mlb_final_scores_by_team_key(mlb_game)
    if len(odds_scores) < 2 or len(mlb_scores) < 2:
        return True
    for key, value in odds_scores.items():
        if key not in mlb_scores:
            return False
        if abs(float(mlb_scores[key]) - float(value)) > tolerance:
            return False
    return True


def _parse_mlb_game_datetime(game: dict[str, Any]) -> datetime | None:
    raw = str(game.get("gameDate") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def resolve_mlb_game_pk(
    home_team: str,
    away_team: str,
    commence_time: str | None,
    *,
    odds_completed_event: dict[str, Any] | None,
    cache: dict[tuple[str, str, str], BoxscoreResolveResult],
    now: datetime | None = None,
    schedule_games: list[dict[str, Any]] | None = None,
    telemetry: dict[str, Any] | None = None,
    context: str = "prop",
    ref_id: str | None = None,
) -> BoxscoreResolveResult:
    home_key = _canonical_team_name(home_team, sport=MLB_SPORT_KEY)
    away_key = _canonical_team_name(away_team, sport=MLB_SPORT_KEY)
    odds_event_id = (
        str(odds_completed_event.get("id") or "").strip() or None
        if isinstance(odds_completed_event, dict)
        else None
    )
    matchup_label = f"{away_team} @ {home_team}".strip()

    def _fail(reason: str) -> BoxscoreResolveResult:
        return BoxscoreResolveResult(
            provider="mlb_statsapi",
            provider_event_id=None,
            odds_event_id=odds_event_id,
            matchup=matchup_label,
            confidence_tier=reason,
        )

    if not home_key or not away_key:
        return _fail("missing_team_keys")

    cache_key = _espn_resolve_cache_key(home_key, away_key, commence_time)
    if cache_key in cache:
        cached = cache[cache_key]
        if not cached.provider_event_id:
            return cached
        result = replace(cached, from_cache=True)
        _record_mlb_resolve_telemetry(telemetry, result, context=context, ref_id=ref_id)
        return result

    bet_dt = _parse_utc_iso(commence_time)
    if schedule_games is None:
        merged = await fetch_mlb_schedule_for_dates(build_auto_settle_mlb_schedule_dates(bet_dt, now=now))
        raw_games = merged.get("games") or []
        schedule_games = [game for game in raw_games if isinstance(game, dict)]

    pair = tuple(sorted([home_key, away_key]))
    candidates: list[dict[str, Any]] = []
    for game in schedule_games:
        if not isinstance(game, dict) or not _mlb_event_completed(game):
            continue
        matchup = _mlb_extract_matchup(game)
        if not matchup:
            continue
        mh = str(matchup.get("home_team_key") or "")
        ma = str(matchup.get("away_team_key") or "")
        if tuple(sorted([mh, ma])) != pair:
            continue
        candidates.append(game)

    if not candidates:
        failed = _fail("no_mlb_candidate")
        cache[cache_key] = failed
        return failed

    odds_full = (
        odds_completed_event is not None
        and len(_odds_final_scores_by_team_key(odds_completed_event)) >= 2
    )
    fallback_used = False
    if odds_completed_event is not None and odds_full:
        aligned = [game for game in candidates if _scores_align_odds_mlb(odds_completed_event, game)]
        if aligned:
            candidates = aligned
        else:
            fallback_used = True

    home_away_tiebreak_used = False
    if len(candidates) > 1 and isinstance(odds_completed_event, dict):
        odds_home = str(odds_completed_event.get("home_team") or "").strip()
        odds_away = str(odds_completed_event.get("away_team") or "").strip()
        if odds_home and odds_away:
            preferred = [game for game in candidates if _mlb_home_away_matches_odds(game, odds_home, odds_away)]
            if preferred:
                candidates = preferred
                home_away_tiebreak_used = True

    def _kickoff_delta(game: dict[str, Any]) -> float:
        mlb_dt = _parse_mlb_game_datetime(game)
        if bet_dt is None or mlb_dt is None:
            return 0.0
        return abs((mlb_dt - bet_dt).total_seconds())

    candidates.sort(key=_kickoff_delta)
    chosen = candidates[0]
    chosen_dt = _parse_mlb_game_datetime(chosen)
    if bet_dt is not None and chosen_dt is not None and abs(chosen_dt - bet_dt) > _MAX_KICKOFF_DRIFT:
        failed = _fail("kickoff_drift_exceeded")
        cache[cache_key] = failed
        return failed

    game_pk = str(chosen.get("gamePk") or "").strip() or None
    if not game_pk:
        failed = _fail("missing_mlb_game_pk")
        cache[cache_key] = failed
        return failed

    confidence_tier = "matchup_plus_time"
    if odds_full:
        confidence_tier = "fallback_time_only" if fallback_used else "score_verified"

    date_delta_hours: float | None = None
    if bet_dt is not None and chosen_dt is not None:
        date_delta_hours = round(abs((chosen_dt - bet_dt).total_seconds()) / 3600.0, 3)

    result = BoxscoreResolveResult(
        provider="mlb_statsapi",
        provider_event_id=game_pk,
        odds_event_id=odds_event_id,
        matchup=matchup_label,
        score_matched=bool(
            odds_completed_event is not None
            and len(_odds_final_scores_by_team_key(odds_completed_event)) >= 2
            and _scores_align_odds_mlb(odds_completed_event, chosen)
        ),
        fallback_used=fallback_used,
        confidence_tier=confidence_tier,
        date_delta_hours=date_delta_hours,
        home_away_tiebreak_used=home_away_tiebreak_used,
        from_cache=False,
    )
    cache[cache_key] = result
    _record_mlb_resolve_telemetry(telemetry, result, context=context, ref_id=ref_id)
    return result


def _stat_label_to_key(label: str) -> str | None:
    """Map ESPN boxscore column label to PTS/REB/AST/3PM."""
    u = str(label).strip().upper()
    if u in ("PTS", "POINTS", "POINT"):
        return "PTS"
    if u in ("REB", "REBOUNDS", "TOT REB", "TOTAL REBOUNDS"):
        return "REB"
    if u in ("AST", "ASSISTS"):
        return "AST"
    # ESPN NBA player boxscore uses "3PT" for made-attempted (e.g. "5-12"), not "3PM".
    if u in ("3PM", "3PTM", "3FGM", "3PT", "3-PT MADE", "3 POINTERS MADE"):
        return "3PM"
    if "3" in u and ("POINT" in u or "PT" in u) and "FREE" not in u and "FIELD" not in u:
        if "MADE" in u or u.endswith("3PM") or "3PM" in u:
            return "3PM"
    if "REBOUND" in u and "OFF" not in u and "DEF" not in u and "TEAM" not in u:
        return "REB"
    if "ASSIST" in u:
        return "AST"
    if u == "FG" or "FIELD GOAL" in u:
        return None
    if "POINT" in u and "FREE" not in u and "3" not in u:
        return "PTS"
    return None


def _parse_stat_cell(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if "-" in s and s[0].isdigit():
        s = s.split("-", 1)[0].strip()
    try:
        return float(s)
    except ValueError:
        return None


def _build_nba_player_stat_map(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Normalize ESPN summary boxscore into {player_key: {PTS: n, REB: n, ...}}."""
    out: dict[str, dict[str, float]] = {}
    box = summary.get("boxscore") or {}
    players = box.get("players") or []
    if not isinstance(players, list):
        return out

    for team_block in players:
        if not isinstance(team_block, dict):
            continue
        stats_list = team_block.get("statistics") or []
        if not isinstance(stats_list, list):
            continue
        for stat_block in stats_list:
            if not isinstance(stat_block, dict):
                continue
            names = stat_block.get("names") or stat_block.get("keys") or []
            athletes = stat_block.get("athletes") or []
            if not isinstance(names, list) or not isinstance(athletes, list):
                continue

            for athlete_row in athletes:
                if not isinstance(athlete_row, dict):
                    continue
                athlete = athlete_row.get("athlete") or {}
                display = str(
                    athlete.get("displayName") or athlete.get("fullName") or ""
                ).strip()
                if not display:
                    continue
                norm = _normalize_player_name(display)
                if not norm:
                    continue
                raw_stats = athlete_row.get("stats") or []
                if not isinstance(raw_stats, list):
                    continue

                row: dict[str, float] = {}
                for i, raw_name in enumerate(names):
                    if i >= len(raw_stats):
                        break
                    key = _stat_label_to_key(str(raw_name))
                    if not key:
                        continue
                    val = _parse_stat_cell(raw_stats[i])
                    if val is None:
                        continue
                    row[key] = val

                if norm not in out:
                    out[norm] = {}
                out[norm].update(row)

    return out


def _build_mlb_player_stat_map(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Normalize MLB boxscore into {player_key: {B_H: n, B_TB: n, P_SO: n, ...}}."""
    out: dict[str, dict[str, float]] = {}
    teams = summary.get("teams") or {}
    if not isinstance(teams, dict):
        return out

    for side in ("away", "home"):
        team_block = teams.get(side) or {}
        if not isinstance(team_block, dict):
            continue
        players = team_block.get("players") or {}
        iterable = players.values() if isinstance(players, dict) else players
        if not isinstance(iterable, (list, tuple, set)) and not hasattr(iterable, "__iter__"):
            continue

        for player_row in iterable:
            if not isinstance(player_row, dict):
                continue
            person = player_row.get("person") or {}
            if not isinstance(person, dict):
                continue
            display = str(person.get("fullName") or person.get("boxscoreName") or "").strip()
            if not display:
                continue
            norm = _normalize_player_name(display)
            if not norm:
                continue

            stats_block = player_row.get("stats") or {}
            if not isinstance(stats_block, dict):
                continue
            batting = stats_block.get("batting") or {}
            pitching = stats_block.get("pitching") or {}

            row: dict[str, float] = {}
            if isinstance(batting, dict):
                hits = _parse_stat_cell(batting.get("hits"))
                total_bases = _parse_stat_cell(batting.get("totalBases"))
                runs = _parse_stat_cell(batting.get("runs"))
                rbi = _parse_stat_cell(batting.get("rbi"))
                home_runs = _parse_stat_cell(batting.get("homeRuns"))
                strikeouts = _parse_stat_cell(batting.get("strikeOuts"))
                if hits is not None:
                    row["B_H"] = hits
                if total_bases is not None:
                    row["B_TB"] = total_bases
                if runs is not None:
                    row["B_R"] = runs
                if rbi is not None:
                    row["B_RBI"] = rbi
                if home_runs is not None:
                    row["B_HR"] = home_runs
                if strikeouts is not None:
                    row["B_SO"] = strikeouts
            if isinstance(pitching, dict):
                pitcher_strikeouts = _parse_stat_cell(pitching.get("strikeOuts"))
                if pitcher_strikeouts is not None:
                    row["P_SO"] = pitcher_strikeouts

            if not row:
                continue

            if norm not in out:
                out[norm] = {}
            out[norm].update(row)

    return out


def build_player_stat_map(
    summary: dict[str, Any],
    *,
    sport: str = NBA_SPORT_KEY,
) -> dict[str, dict[str, float]]:
    normalized_sport = str(sport or "").strip().lower()
    if normalized_sport == MLB_SPORT_KEY:
        return _build_mlb_player_stat_map(summary)
    return _build_nba_player_stat_map(summary)


def _market_stat_value_from_player_stats(
    sport: str,
    market_key: str,
    player_stats: dict[str, float],
) -> float | None:
    normalized_sport = str(sport or "").strip().lower()
    normalized_market = str(market_key or "").strip()

    if normalized_sport == NBA_SPORT_KEY:
        if normalized_market == "player_points_rebounds_assists":
            points = player_stats.get("PTS")
            rebounds = player_stats.get("REB")
            assists = player_stats.get("AST")
            if points is None or rebounds is None or assists is None:
                return None
            return float(points + rebounds + assists)
        stat_col = PROP_MARKET_TO_ESPN_STAT.get(normalized_market)
        if not stat_col:
            return None
        actual = player_stats.get(stat_col)
        return float(actual) if actual is not None else None

    if normalized_sport == MLB_SPORT_KEY:
        if normalized_market == "batter_hits_runs_rbis":
            hits = player_stats.get("B_H")
            runs = player_stats.get("B_R")
            rbi = player_stats.get("B_RBI")
            if hits is None or runs is None or rbi is None:
                return None
            return float(hits + runs + rbi)
        stat_col = PROP_MARKET_TO_MLB_STAT.get(normalized_market)
        if not stat_col:
            return None
        actual = player_stats.get(stat_col)
        return float(actual) if actual is not None else None

    return None


def _espn_resolve_cache_key(
    hk: str,
    ak: str,
    commence_time: str | None,
) -> tuple[str, str, str]:
    """Key by matchup plus kickoff timestamp so same-day repeat matchups don't collide."""
    bet_dt = _parse_utc_iso(commence_time)
    commence_token = bet_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if bet_dt else "_"
    a, b = sorted([hk, ak])
    return (a, b, commence_token)


async def resolve_espn_event_id(
    home_team: str,
    away_team: str,
    commence_time: str | None,
    *,
    odds_completed_event: dict[str, Any] | None,
    cache: dict[tuple[str, str, str], EspnResolveResult],
    now: datetime | None = None,
    scoreboard_events: list[dict[str, Any]] | None = None,
    telemetry: dict[str, Any] | None = None,
    context: str = "prop",
    ref_id: str | None = None,
) -> EspnResolveResult:
    """Match Odds API home/away (+ optional score check) to an ESPN NBA event id (final only)."""
    hk = _canonical_team_name(home_team)
    ak = _canonical_team_name(away_team)
    odds_event_id = (
        str(odds_completed_event.get("id") or "").strip() or None
        if isinstance(odds_completed_event, dict)
        else None
    )
    matchup_label = f"{away_team} @ {home_team}".strip()

    def _fail(reason: str) -> EspnResolveResult:
        r = EspnResolveResult(
            espn_event_id=None,
            odds_event_id=odds_event_id,
            matchup=matchup_label,
            confidence_tier=reason,
        )
        return r

    if not hk or not ak:
        return _fail("missing_team_keys")

    cache_key = _espn_resolve_cache_key(hk, ak, commence_time)
    if cache_key in cache:
        prev = cache[cache_key]
        if not prev.espn_event_id:
            return prev
        out = replace(prev, from_cache=True)
        _log_espn_resolve_line(out, context=context, ref_id=ref_id)
        _record_espn_resolve_telemetry(telemetry, out, context=context, ref_id=ref_id)
        return out

    bet_dt = _parse_utc_iso(commence_time)
    if scoreboard_events is not None:
        events = scoreboard_events
    else:
        date_list = build_auto_settle_scoreboard_dates(bet_dt, now=now)
        payload = await fetch_nba_scoreboard_for_dates(date_list)
        events = payload.get("events") or []
    if not isinstance(events, list):
        failed = _fail("no_scoreboard_events")
        cache[cache_key] = failed
        return failed

    pair = tuple(sorted([hk, ak]))
    candidates: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if not _event_completed(event):
            continue
        matchup = _extract_matchup(event)
        if not matchup:
            continue
        mhk = matchup.get("home_team_key") or ""
        mak = matchup.get("away_team_key") or ""
        if tuple(sorted([mhk, mak])) != pair:
            continue
        candidates.append(event)

    if not candidates:
        failed = _fail("no_espn_candidate")
        cache[cache_key] = failed
        return failed

    odds_full = (
        odds_completed_event is not None
        and len(_odds_final_scores_by_team_key(odds_completed_event)) >= 2
    )
    aligned: list[dict[str, Any]] = []
    fallback_used = False
    if odds_completed_event is not None and odds_full:
        aligned = [
            e
            for e in candidates
            if _scores_align_odds_espn(odds_completed_event, e)
        ]
        if aligned:
            candidates = aligned
        else:
            fallback_used = True
            print(
                "[Auto-Settler:props] ESPN candidates failed score cross-check vs Odds API; "
                "falling back to kickoff proximity / home-away tiebreak."
            )

    home_away_tiebreak_used = False
    if (
        len(candidates) > 1
        and isinstance(odds_completed_event, dict)
    ):
        oh = str(odds_completed_event.get("home_team") or "").strip()
        oa = str(odds_completed_event.get("away_team") or "").strip()
        if oh and oa:
            ha_pref = [c for c in candidates if _espn_home_away_matches_odds(c, oh, oa)]
            if ha_pref:
                candidates = ha_pref
                home_away_tiebreak_used = True

    def _kickoff_delta(ev: dict[str, Any]) -> float:
        espn_dt = _parse_espn_event_datetime(ev)
        if bet_dt is None or espn_dt is None:
            return 0.0
        return abs((espn_dt - bet_dt).total_seconds())

    candidates.sort(key=_kickoff_delta)
    chosen = candidates[0]
    espn_dt = _parse_espn_event_datetime(chosen)
    if bet_dt is not None and espn_dt is not None:
        if abs(espn_dt - bet_dt) > _MAX_KICKOFF_DRIFT:
            print(
                "[Auto-Settler:props] ESPN event kickoff too far from bet commence_time — skip"
            )
            failed = _fail("kickoff_drift_exceeded")
            cache[cache_key] = failed
            return failed

    matchup = _extract_matchup(chosen)
    eid = str((matchup or {}).get("event_id") or "").strip() or None
    if not eid:
        failed = _fail("missing_espn_id")
        cache[cache_key] = failed
        return failed

    score_matched = bool(
        odds_completed_event is not None
        and len(_odds_final_scores_by_team_key(odds_completed_event)) >= 2
        and _scores_align_odds_espn(odds_completed_event, chosen)
    )
    if odds_full:
        confidence_tier = "fallback_time_only" if fallback_used else "score_verified"
    else:
        confidence_tier = "matchup_plus_time"

    delta_h: float | None = None
    if bet_dt is not None and espn_dt is not None:
        delta_h = round(abs((espn_dt - bet_dt).total_seconds()) / 3600.0, 3)

    result = EspnResolveResult(
        espn_event_id=eid,
        odds_event_id=odds_event_id,
        matchup=matchup_label,
        score_matched=score_matched,
        fallback_used=fallback_used,
        confidence_tier=confidence_tier,
        date_delta_hours=delta_h,
        home_away_tiebreak_used=home_away_tiebreak_used,
        from_cache=False,
    )
    cache[cache_key] = result
    _log_espn_resolve_line(result, context=context, ref_id=ref_id)
    _record_espn_resolve_telemetry(telemetry, result, context=context, ref_id=ref_id)
    return result


def _boxscore_result_from_espn(result: EspnResolveResult) -> BoxscoreResolveResult:
    return BoxscoreResolveResult(
        provider="espn",
        provider_event_id=result.espn_event_id,
        odds_event_id=result.odds_event_id,
        matchup=result.matchup,
        score_matched=result.score_matched,
        fallback_used=result.fallback_used,
        confidence_tier=result.confidence_tier,
        date_delta_hours=result.date_delta_hours,
        home_away_tiebreak_used=result.home_away_tiebreak_used,
        from_cache=result.from_cache,
    )


async def resolve_boxscore_event_id(
    sport: str,
    home_team: str,
    away_team: str,
    commence_time: str | None,
    *,
    odds_completed_event: dict[str, Any] | None,
    cache_by_sport: dict[str, dict[tuple[str, str, str], Any]],
    now: datetime | None = None,
    provider_events_by_sport: dict[str, list[dict[str, Any]]] | None = None,
    telemetry: dict[str, Any] | None = None,
    context: str = "prop",
    ref_id: str | None = None,
) -> BoxscoreResolveResult:
    normalized_sport = str(sport or "").strip().lower()
    provider_events = (provider_events_by_sport or {}).get(normalized_sport)

    if normalized_sport == NBA_SPORT_KEY:
        nba_cache = cache_by_sport.setdefault(NBA_SPORT_KEY, {})
        result = await resolve_espn_event_id(
            home_team,
            away_team,
            commence_time,
            odds_completed_event=odds_completed_event,
            cache=nba_cache,
            now=now,
            scoreboard_events=provider_events,
            telemetry=telemetry,
            context=context,
            ref_id=ref_id,
        )
        return _boxscore_result_from_espn(result)

    if normalized_sport == MLB_SPORT_KEY:
        mlb_cache = cache_by_sport.setdefault(MLB_SPORT_KEY, {})
        return await resolve_mlb_game_pk(
            home_team,
            away_team,
            commence_time,
            odds_completed_event=odds_completed_event,
            cache=mlb_cache,
            now=now,
            schedule_games=provider_events,
            telemetry=telemetry,
            context=context,
            ref_id=ref_id,
        )

    return BoxscoreResolveResult(
        provider="unsupported",
        provider_event_id=None,
        odds_event_id=str(odds_completed_event.get("id") or "").strip() or None
        if isinstance(odds_completed_event, dict)
        else None,
        matchup=f"{away_team} @ {home_team}".strip(),
        confidence_tier="unsupported_sport",
    )


async def fetch_boxscore_summary(sport: str, provider_event_id: str) -> dict[str, Any]:
    normalized_sport = str(sport or "").strip().lower()
    if normalized_sport == NBA_SPORT_KEY:
        return await fetch_nba_game_summary(provider_event_id)
    if normalized_sport == MLB_SPORT_KEY:
        return await fetch_mlb_game_boxscore(provider_event_id)
    return {}


def _build_boxscore_date_union_for_commence_values(
    sport: str,
    commence_values: list[Any],
    *,
    now: datetime | None,
) -> list[str]:
    normalized_sport = str(sport or "").strip().lower()
    commence_times = [_parse_utc_iso(str(value) if value else None) for value in commence_values]
    if normalized_sport == NBA_SPORT_KEY:
        dates: set[str] = set(build_scoreboard_date_window(now))
        for commence_dt in commence_times:
            dates.update(build_auto_settle_scoreboard_dates(commence_dt, now=now))
        return sorted(dates)
    if normalized_sport == MLB_SPORT_KEY:
        dates: set[str] = set(build_mlb_schedule_date_window(now))
        for commence_dt in commence_times:
            dates.update(build_auto_settle_mlb_schedule_dates(commence_dt, now=now))
        return sorted(dates)
    return []


async def fetch_boxscore_provider_events_for_rows(
    rows: list[dict[str, Any]],
    *,
    sport_field: str,
    commence_time_field: str = "commence_time",
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    commence_by_sport: dict[str, list[Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sport = str(row.get(sport_field) or "").strip().lower()
        if sport not in SUPPORTED_PROP_BOX_SCORE_SPORTS:
            continue
        commence_by_sport.setdefault(sport, []).append(row.get(commence_time_field))

    provider_events_by_sport: dict[str, list[dict[str, Any]]] = {}
    for sport, commence_values in commence_by_sport.items():
        date_union = _build_boxscore_date_union_for_commence_values(sport, commence_values, now=now)
        if not date_union:
            provider_events_by_sport[sport] = []
            continue
        if sport == NBA_SPORT_KEY:
            merged = await fetch_nba_scoreboard_for_dates(date_union)
            raw_events = merged.get("events") or []
            provider_events_by_sport[sport] = [event for event in raw_events if isinstance(event, dict)]
            continue
        if sport == MLB_SPORT_KEY:
            merged = await fetch_mlb_schedule_for_dates(date_union)
            raw_games = merged.get("games") or []
            provider_events_by_sport[sport] = [game for game in raw_games if isinstance(game, dict)]
            continue
        provider_events_by_sport[sport] = []

    return provider_events_by_sport


def grade_prop(
    player_name: str | None,
    market_key: str,
    line_value: float | None,
    selection_side: str | None,
    stat_map: dict[str, dict[str, float]],
    *,
    sport: str = NBA_SPORT_KEY,
) -> tuple[str | None, dict[str, Any]]:
    """Return (win|loss|push|None, detail) for telemetry (player_match, stat_present)."""
    detail: dict[str, Any] = {
        "player_match": "n_a",
        "stat_present": False,
    }
    if not is_auto_settle_supported_prop_market(sport, market_key):
        return None, detail
    norm = _normalize_player_name(player_name)
    if not norm:
        return None, detail
    if line_value is None:
        return None, detail
    try:
        line = float(line_value)
    except (TypeError, ValueError):
        return None, detail

    side = str(selection_side or "").strip().lower()
    if side not in ("over", "under"):
        return None, detail

    player_stats, match_kind = _match_player_stat_key(norm, player_name, stat_map)
    if not player_stats:
        detail["player_match"] = "none"
        return None, detail
    detail["player_match"] = match_kind

    actual = _market_stat_value_from_player_stats(sport, market_key, player_stats)
    if actual is None:
        return None, detail

    detail["stat_present"] = True
    if actual == line:
        return "push", detail
    if side == "over":
        return ("win" if actual > line else "loss"), detail
    return ("win" if actual < line else "loss"), detail


def _record_prop_grade_telemetry(
    telemetry: dict[str, Any] | None,
    grade: str | None,
    detail: dict[str, Any],
) -> None:
    if telemetry is None:
        return
    pm = str(detail.get("player_match") or "")
    if grade is None:
        if pm == "none":
            _telemetry_bump(telemetry, "props_player_not_found")
        elif pm in ("exact", "fuzzy") and not detail.get("stat_present"):
            _telemetry_bump(telemetry, "props_stat_missing")
        return
    if pm == "exact":
        _telemetry_bump(telemetry, "props_player_match_exact")
    elif pm == "fuzzy":
        _telemetry_bump(telemetry, "props_player_match_fuzzy")


def combine_parlay_resolved_grades(grades: list[str]) -> str:
    """Combine leg grades when each is win or push. At least one win => parlay win."""
    if any(g == "win" for g in grades):
        return "win"
    return "push"


def grade_parlay_ml_leg(
    leg: dict[str, Any],
    completed_events_by_sport: dict[str, list[dict]],
) -> str | None:
    from services.odds_api import _grade_ml, _select_completed_event_for_bet

    sport = str(leg.get("sport") or "").strip()
    if not sport:
        return None
    team = leg.get("team")
    if not team:
        return None

    events = completed_events_by_sport.get(sport) or []
    synthetic = {
        "clv_event_id": str(
            leg.get("sourceEventId")
            or leg.get("source_event_id")
            or leg.get("eventId")
            or leg.get("event_id")
            or ""
        ).strip()
        or None,
        "clv_team": team,
        "commence_time": leg.get("commenceTime") or leg.get("commence_time"),
        "clv_sport_key": sport,
    }
    if synthetic["clv_event_id"] == "":
        synthetic["clv_event_id"] = None

    event, _reason = _select_completed_event_for_bet(synthetic, events)
    if event is None:
        return None

    return _grade_ml(
        str(team),
        str(event.get("home_team", "")),
        str(event.get("away_team", "")),
        event.get("scores") or [],
        sport_key=sport,
    )


async def grade_parlay_prop_leg(
    leg: dict[str, Any],
    completed_events_by_sport: dict[str, list[dict]],
    boxscore_summary_cache: dict[tuple[str, str], dict[str, Any]],
    boxscore_resolve_cache_by_sport: dict[str, dict[tuple[str, str, str], Any]],
    *,
    now: datetime | None = None,
    provider_events_by_sport: dict[str, list[dict[str, Any]]] | None = None,
    telemetry: dict[str, Any] | None = None,
    ref_id: str | None = None,
) -> str | None:
    from services.odds_api import _select_completed_event_for_bet

    sport = str(leg.get("sport") or "").strip().lower()
    if sport not in SUPPORTED_PROP_BOX_SCORE_SPORTS:
        return None

    mk = str(leg.get("marketKey") or leg.get("market_key") or "").strip()
    if not is_auto_settle_supported_prop_market(sport, mk):
        return None

    line_raw = leg.get("lineValue") if leg.get("lineValue") is not None else leg.get("line_value")
    side = leg.get("selectionSide") or leg.get("selection_side")
    player = leg.get("participantName") or leg.get("participant_name")

    events = completed_events_by_sport.get(sport) or []
    synthetic = {
        "clv_event_id": str(
            leg.get("sourceEventId")
            or leg.get("source_event_id")
            or leg.get("eventId")
            or leg.get("event_id")
            or ""
        ).strip()
        or None,
        "clv_team": leg.get("team"),
        "commence_time": leg.get("commenceTime") or leg.get("commence_time"),
        "clv_sport_key": sport,
    }
    if synthetic["clv_event_id"] == "":
        synthetic["clv_event_id"] = None

    event, _reason = _select_completed_event_for_bet(synthetic, events)
    if event is None:
        return None

    home = str(event.get("home_team", ""))
    away = str(event.get("away_team", ""))
    if not home or not away:
        return None

    res = await resolve_boxscore_event_id(
        sport,
        home,
        away,
        synthetic.get("commence_time"),
        odds_completed_event=event,
        cache_by_sport=boxscore_resolve_cache_by_sport,
        now=now,
        provider_events_by_sport=provider_events_by_sport,
        telemetry=telemetry,
        context="parlay_leg",
        ref_id=ref_id,
    )
    provider_event_id = res.provider_event_id
    if not provider_event_id:
        return None

    summary_cache_key = (sport, provider_event_id)
    if summary_cache_key not in boxscore_summary_cache:
        try:
            boxscore_summary_cache[summary_cache_key] = await fetch_boxscore_summary(
                sport,
                provider_event_id,
            )
        except Exception:
            _telemetry_bump(telemetry, "props_boxscore_fetch_failed")
            boxscore_summary_cache[summary_cache_key] = {}

    summary = boxscore_summary_cache.get(summary_cache_key) or {}
    stat_map = build_player_stat_map(summary, sport=sport)
    grade, detail = grade_prop(player, mk, line_raw, side, stat_map, sport=sport)
    _record_prop_grade_telemetry(telemetry, grade, detail)
    return grade


async def grade_parlay_leg(
    leg: dict[str, Any],
    completed_events_by_sport: dict[str, list[dict]],
    boxscore_summary_cache: dict[tuple[str, str], dict[str, Any]],
    boxscore_resolve_cache_by_sport: dict[str, dict[tuple[str, str, str], Any]],
    *,
    now: datetime | None = None,
    provider_events_by_sport: dict[str, list[dict[str, Any]]] | None = None,
    telemetry: dict[str, Any] | None = None,
    prop_ref_id: str | None = None,
) -> str | None:
    surface = str(leg.get("surface") or "").strip().lower()
    if surface == "player_props":
        return await grade_parlay_prop_leg(
            leg,
            completed_events_by_sport,
            boxscore_summary_cache,
            boxscore_resolve_cache_by_sport,
            now=now,
            provider_events_by_sport=provider_events_by_sport,
            telemetry=telemetry,
            ref_id=prop_ref_id,
        )
    if surface == "straight_bets":
        return grade_parlay_ml_leg(leg, completed_events_by_sport)
    return None


def _parlay_prop_leg_can_prefetch_provider_event(leg: dict[str, Any], *, now: datetime) -> bool:
    if str(leg.get("surface") or "").strip().lower() != "player_props":
        return False
    sport = str(leg.get("sport") or "").strip().lower()
    market_key = str(leg.get("marketKey") or leg.get("market_key") or "").strip()
    if not is_auto_settle_supported_prop_market(sport, market_key):
        return False
    if not leg.get("team"):
        return False
    if not (leg.get("participantName") or leg.get("participant_name")):
        return False
    if not (leg.get("selectionSide") or leg.get("selection_side")):
        return False
    line_value = leg.get("lineValue") if leg.get("lineValue") is not None else leg.get("line_value")
    if line_value is None:
        return False
    commence_time = leg.get("commenceTime") or leg.get("commence_time")
    kickoff = _parse_utc_iso(str(commence_time) if commence_time else None)
    return kickoff is not None and kickoff <= now


def _build_parlay_provider_prefetch_rows(
    parlay_bets: list[dict[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bet in parlay_bets:
        meta = bet.get("selection_meta")
        if not isinstance(meta, dict):
            continue
        for leg in meta.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            if not _parlay_prop_leg_can_prefetch_provider_event(leg, now=now):
                continue
            sport = str(leg.get("sport") or "").strip()
            commence_time = leg.get("commenceTime") or leg.get("commence_time")
            key = (sport.lower(), str(commence_time or "").strip())
            if not sport or key in seen:
                continue
            seen.add(key)
            rows.append({"sport": sport, "commence_time": commence_time})
    return rows


def is_standalone_prop_bet(bet: dict[str, Any]) -> bool:
    surface = str(bet.get("surface") or "").strip().lower()
    if surface != "player_props":
        return False
    sport = str(bet.get("clv_sport_key") or "").strip().lower()
    mk = str(bet.get("source_market_key") or "").strip()
    return (
        is_auto_settle_supported_prop_market(sport, mk)
        and bool(bet.get("participant_name"))
        and bool(bet.get("selection_side"))
        and bet.get("line_value") is not None
        and _parse_utc_iso(str(bet.get("commence_time") or "").strip() or None) is not None
    )


async def settle_standalone_props(
    db: Any,
    prop_bets: list[dict[str, Any]],
    completed_events_by_sport: dict[str, list[dict]],
    settled_at: str,
    *,
    source: str,
    now: datetime | None = None,
    telemetry: dict[str, Any] | None = None,
) -> tuple[int, dict[str, int]]:
    from services.odds_api import _select_completed_event_for_bet

    skipped: dict[str, int] = {
        "unsupported_sport": 0,
        "no_match": 0,
        "boxscore_resolve_failed": 0,
        "boxscore_fetch_failed": 0,
        "ungraded_prop": 0,
        "db_update_failed": 0,
    }
    settled = 0
    boxscore_summary_cache: dict[tuple[str, str], dict[str, Any]] = {}
    boxscore_resolve_cache_by_sport: dict[str, dict[tuple[str, str, str], Any]] = {}
    provider_events_by_sport = await fetch_boxscore_provider_events_for_rows(
        prop_bets,
        sport_field="clv_sport_key",
        commence_time_field="commence_time",
        now=now,
    )

    for bet in prop_bets:
        sport = str(bet.get("clv_sport_key") or "").strip().lower()
        if not is_standalone_prop_bet(bet):
            skipped["unsupported_sport"] += 1
            continue

        events = completed_events_by_sport.get(sport) or []
        event, reason = _select_completed_event_for_bet(bet, events)
        if event is None:
            skipped["no_match"] += 1
            print(
                f"[Auto-Settler:props] bet {bet.get('id')} no completed event "
                f"({reason})"
            )
            continue

        home = str(event.get("home_team", ""))
        away = str(event.get("away_team", ""))
        res = await resolve_boxscore_event_id(
            sport,
            home,
            away,
            bet.get("commence_time"),
            odds_completed_event=event,
            cache_by_sport=boxscore_resolve_cache_by_sport,
            now=now,
            provider_events_by_sport=provider_events_by_sport,
            telemetry=telemetry,
            context="standalone_prop",
            ref_id=str(bet.get("id")) if bet.get("id") is not None else None,
        )
        provider_event_id = res.provider_event_id
        if not provider_event_id:
            skipped["boxscore_resolve_failed"] += 1
            print(
                f"[Auto-Settler:props] bet {bet.get('id')} boxscore id not resolved "
                f"({res.confidence_tier})"
            )
            continue

        summary_cache_key = (sport, provider_event_id)
        if summary_cache_key not in boxscore_summary_cache:
            try:
                boxscore_summary_cache[summary_cache_key] = await fetch_boxscore_summary(
                    sport,
                    provider_event_id,
                )
            except Exception as e:
                _telemetry_bump(telemetry, "props_boxscore_fetch_failed")
                skipped["boxscore_fetch_failed"] += 1
                print(
                    f"[Auto-Settler:props] boxscore fetch failed for sport={sport} "
                    f"provider_event_id={provider_event_id}: {e}"
                )
                continue

        stat_map = build_player_stat_map(
            boxscore_summary_cache[summary_cache_key],
            sport=sport,
        )
        mk = str(bet.get("source_market_key") or "").strip()
        grade, g_detail = grade_prop(
            bet.get("participant_name"),
            mk,
            bet.get("line_value"),
            bet.get("selection_side"),
            stat_map,
            sport=sport,
        )
        _record_prop_grade_telemetry(telemetry, grade, g_detail)
        if grade is None:
            skipped["ungraded_prop"] += 1
            print(
                f"[Auto-Settler:props] bet {bet.get('id')} could not grade prop "
                f"market={mk!r} participant={bet.get('participant_name')!r} "
                f"line={bet.get('line_value')!r} side={bet.get('selection_side')!r} "
                f"detail={g_detail!r}"
            )
            continue

        try:
            db.table("bets").update(
                {"result": grade, "settled_at": settled_at}
            ).eq("id", bet["id"]).execute()
            settled += 1
        except Exception as e:
            skipped["db_update_failed"] += 1
            print(f"[Auto-Settler:props] Failed updating bet {bet.get('id')}: {e}")

    if any(v > 0 for v in skipped.values()):
        print(f"[Auto-Settler:props] summary settled={settled} skipped={skipped} source={source}")

    return settled, skipped

async def settle_parlays(
    db: Any,
    parlay_bets: list[dict[str, Any]],
    completed_events_by_sport: dict[str, list[dict]],
    settled_at: str,
    *,
    now: datetime,
    source: str,
    telemetry: dict[str, Any] | None = None,
) -> tuple[int, dict[str, int]]:
    skipped: dict[str, int] = {
        "no_legs": 0,
        "not_ready": 0,
        "ungraded": 0,
        "db_update_failed": 0,
    }
    settled = 0
    boxscore_summary_cache: dict[tuple[str, str], dict[str, Any]] = {}
    boxscore_resolve_cache_by_sport: dict[str, dict[tuple[str, str, str], Any]] = {}
    provider_prefetch_rows = _build_parlay_provider_prefetch_rows(parlay_bets, now=now)
    provider_events_by_sport = await fetch_boxscore_provider_events_for_rows(
        provider_prefetch_rows,
        sport_field="sport",
        commence_time_field="commence_time",
        now=now,
    )

    for bet in parlay_bets:
        meta = bet.get("selection_meta")
        if not isinstance(meta, dict):
            skipped["no_legs"] += 1
            continue
        legs = meta.get("legs") or []
        if not isinstance(legs, list) or not legs:
            skipped["no_legs"] += 1
            continue

        bid = str(bet.get("id") or "")
        leg_outcomes: list[str | None] = []
        for leg in legs:
            if not isinstance(leg, dict):
                leg_outcomes.append(None)
                continue
            ct = leg.get("commenceTime") or leg.get("commence_time")
            kickoff = _parse_utc_iso(str(ct) if ct else None)
            if kickoff is not None and kickoff > now:
                leg_outcomes.append("not_started")
                continue

            lid = str(leg.get("id") or "")
            prop_ref = f"{bid}:{lid}" if bid or lid else None
            g = await grade_parlay_leg(
                leg,
                completed_events_by_sport,
                boxscore_summary_cache,
                boxscore_resolve_cache_by_sport,
                now=now,
                provider_events_by_sport=provider_events_by_sport,
                telemetry=telemetry,
                prop_ref_id=prop_ref,
            )
            leg_outcomes.append(g)

        if any(g == "loss" for g in leg_outcomes):
            final = "loss"
        elif any(g is None for g in leg_outcomes):
            skipped["ungraded"] += 1
            continue
        elif any(g == "not_started" for g in leg_outcomes):
            skipped["not_ready"] += 1
            continue
        else:
            resolved = [g for g in leg_outcomes if g in ("win", "push")]
            if len(resolved) != len(leg_outcomes):
                skipped["ungraded"] += 1
                continue
            final = combine_parlay_resolved_grades(resolved)

        try:
            db.table("bets").update(
                {"result": final, "settled_at": settled_at}
            ).eq("id", bet["id"]).execute()
            settled += 1
        except Exception as e:
            skipped["db_update_failed"] += 1
            print(f"[Auto-Settler:parlay] Failed updating bet {bet.get('id')}: {e}")

    if any(v > 0 for v in skipped.values()):
        print(f"[Auto-Settler:parlay] summary settled={settled} skipped={skipped} source={source}")

    return settled, skipped
