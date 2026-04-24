from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from models import LiveEventSnapshot, LivePlayerStatSnapshot, LiveTeamScore
from services.http_client import request_with_retries
from services.live_provider_contracts import (
    LiveBetCandidate,
    LivePlayerStatRequest,
    ProviderLookupResult,
    ProviderPlayerStatResult,
)
from services.prop_settler import (
    MLB_SPORT_KEY,
    PROP_MARKET_TO_MLB_STAT,
    _market_stat_value_from_player_stats,
    _match_player_stat_key,
    _mlb_extract_matchup,
    _normalize_player_name,
    _parse_mlb_game_datetime,
    _parse_utc_iso,
    build_auto_settle_mlb_schedule_dates,
    build_player_stat_map,
    fetch_mlb_game_boxscore,
    fetch_mlb_schedule_for_date,
)
from services.shared_state import get_json, set_json
from services.team_aliases import canonical_short_name, canonical_team_token

logger = logging.getLogger("ev_tracker.live_tracking")

MLB_PROVIDER = "mlb_statsapi"
MLB_STATSAPI_LINESCORE_URL_TEMPLATE = "https://statsapi.mlb.com/api/v1/game/{game_pk}/linescore"
_FRESH_SCHEDULE_TTL_SECONDS = 60
_STALE_SCHEDULE_TTL_SECONDS = 10 * 60
_FRESH_BOXSCORE_TTL_SECONDS = 60
_STALE_BOXSCORE_TTL_SECONDS = 10 * 60
_FRESH_LINESCORE_TTL_SECONDS = 60
_STALE_LINESCORE_TTL_SECONDS = 10 * 60
_MAX_MATCH_DRIFT = timedelta(hours=18)
_AMBIGUOUS_TIME_GAP = timedelta(hours=2)
_SUPPORTED_MLB_PROP_MARKETS = {
    "pitcher_strikeouts",
    "pitcher_strikeouts_alternate",
    "batter_total_bases",
    "batter_total_bases_alternate",
    "batter_hits",
    "batter_hits_alternate",
    "batter_hits_runs_rbis",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _parse_provider_datetime(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status_from_mlb(status: dict[str, Any]) -> str:
    abstract = str(status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailedState") or "").strip().lower()
    coded = str(status.get("codedGameState") or status.get("statusCode") or "").strip().upper()
    detail_blob = " ".join(part for part in (abstract, detailed, coded.lower()) if part)

    if abstract == "final" or coded == "F" or "final" in detail_blob or "game over" in detail_blob:
        return "final"
    if "postpon" in detail_blob:
        return "postponed"
    if "cancel" in detail_blob:
        return "cancelled"
    if "delay" in detail_blob or "suspend" in detail_blob:
        return "delayed"
    if abstract == "live" or coded in {"I", "M", "N"} or "progress" in detail_blob:
        return "live"
    if abstract in {"preview", "pregame"} or coded in {"S", "P"} or "scheduled" in detail_blob:
        return "scheduled"
    return "unknown"


def _score_from_team_row(team_row: dict[str, Any]) -> float | None:
    raw = team_row.get("score")
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _team_from_schedule_row(
    team_row: dict[str, Any],
    *,
    home_away: str,
) -> LiveTeamScore | None:
    team = team_row.get("team") or {}
    if not isinstance(team, dict):
        return None
    name = str(team.get("name") or "").strip()
    if not name:
        return None
    return LiveTeamScore(
        name=name,
        short_name=canonical_short_name(MLB_SPORT_KEY, name),
        score=_score_from_team_row(team_row),
        home_away=home_away,  # type: ignore[arg-type]
    )


def normalize_mlb_game(game: dict[str, Any]) -> LiveEventSnapshot | None:
    game_pk = str(game.get("gamePk") or "").strip()
    matchup = _mlb_extract_matchup(game)
    teams = game.get("teams") or {}
    if not game_pk or not matchup or not isinstance(teams, dict):
        return None

    away = _team_from_schedule_row(teams.get("away") or {}, home_away="away")
    home = _team_from_schedule_row(teams.get("home") or {}, home_away="home")
    if away is None or home is None:
        return None

    status = game.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    status_detail = str(status.get("detailedState") or "").strip() or None
    last_updated = _parse_provider_datetime(game.get("_live_fetched_at")) or _utc_now()

    return LiveEventSnapshot(
        provider=MLB_PROVIDER,
        provider_event_id=game_pk,
        sport_key=MLB_SPORT_KEY,
        status=_status_from_mlb(status),  # type: ignore[arg-type]
        status_detail=status_detail,
        period_label=None,
        clock=None,
        start_time=_parse_mlb_game_datetime(game),
        last_updated=last_updated,
        home=home,
        away=away,
    )


def _linescore_cache_key(game_pk: str) -> str:
    return f"live:provider:{MLB_PROVIDER}:{MLB_SPORT_KEY}:linescore:{game_pk}:fresh"


def _linescore_stale_cache_key(game_pk: str) -> str:
    return f"live:provider:{MLB_PROVIDER}:{MLB_SPORT_KEY}:linescore:{game_pk}:last-good"


def _schedule_cache_key(date_value: str) -> str:
    return f"live:provider:{MLB_PROVIDER}:{MLB_SPORT_KEY}:schedule:{date_value}:fresh"


def _schedule_stale_cache_key(date_value: str) -> str:
    return f"live:provider:{MLB_PROVIDER}:{MLB_SPORT_KEY}:schedule:{date_value}:last-good"


def _boxscore_cache_key(game_pk: str) -> str:
    return f"live:provider:{MLB_PROVIDER}:{MLB_SPORT_KEY}:boxscore:{game_pk}:fresh"


def _boxscore_stale_cache_key(game_pk: str) -> str:
    return f"live:provider:{MLB_PROVIDER}:{MLB_SPORT_KEY}:boxscore:{game_pk}:last-good"


def _stamp_games(games: list[dict[str, Any]], fetched_at: str) -> list[dict[str, Any]]:
    return [{**game, "_live_fetched_at": fetched_at} for game in games if isinstance(game, dict)]


def _stamp_payload(payload: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {**payload, "_live_fetched_at": fetched_at}


async def _fetch_cached_schedule_date(date_value: str) -> tuple[list[dict[str, Any]], bool, bool]:
    cached = get_json(_schedule_cache_key(date_value))
    if isinstance(cached, dict) and isinstance(cached.get("games"), list):
        fetched_at = str(cached.get("fetched_at") or "").strip() or _iso_now()
        return _stamp_games(cached["games"], fetched_at), True, False

    try:
        payload = await fetch_mlb_schedule_for_date(date_value)
        raw_dates = payload.get("dates") if isinstance(payload, dict) else []
        games: list[dict[str, Any]] = []
        if isinstance(raw_dates, list):
            for date_block in raw_dates:
                if not isinstance(date_block, dict):
                    continue
                raw_games = date_block.get("games") or []
                if not isinstance(raw_games, list):
                    continue
                games.extend(game for game in raw_games if isinstance(game, dict))

        wrapped = {"fetched_at": _iso_now(), "games": games}
        set_json(_schedule_cache_key(date_value), wrapped, _FRESH_SCHEDULE_TTL_SECONDS)
        set_json(_schedule_stale_cache_key(date_value), wrapped, _STALE_SCHEDULE_TTL_SECONDS)
        return _stamp_games(games, wrapped["fetched_at"]), False, False
    except Exception as exc:
        logger.warning(
            "live_tracking.provider.schedule_failed provider=%s sport=%s date=%s err=%s",
            MLB_PROVIDER,
            MLB_SPORT_KEY,
            date_value,
            exc,
        )
        stale = get_json(_schedule_stale_cache_key(date_value))
        if isinstance(stale, dict) and isinstance(stale.get("games"), list):
            fetched_at = str(stale.get("fetched_at") or "").strip() or _iso_now()
            return _stamp_games(stale["games"], fetched_at), True, True
        return [], False, False


async def _fetch_cached_boxscore(game_pk: str) -> tuple[dict[str, Any], bool, bool]:
    cached = get_json(_boxscore_cache_key(game_pk))
    if isinstance(cached, dict) and isinstance(cached.get("boxscore"), dict):
        return cached["boxscore"], True, False

    try:
        boxscore = await fetch_mlb_game_boxscore(game_pk)
        wrapped = {"fetched_at": _iso_now(), "boxscore": boxscore}
        set_json(_boxscore_cache_key(game_pk), wrapped, _FRESH_BOXSCORE_TTL_SECONDS)
        set_json(_boxscore_stale_cache_key(game_pk), wrapped, _STALE_BOXSCORE_TTL_SECONDS)
        return boxscore, False, False
    except Exception as exc:
        logger.warning(
            "live_tracking.provider.boxscore_failed provider=%s sport=%s game_pk=%s err=%s",
            MLB_PROVIDER,
            MLB_SPORT_KEY,
            game_pk,
            exc,
        )
        stale = get_json(_boxscore_stale_cache_key(game_pk))
        if isinstance(stale, dict) and isinstance(stale.get("boxscore"), dict):
            return stale["boxscore"], True, True
        return {}, False, False


async def _fetch_cached_linescore(game_pk: str) -> tuple[dict[str, Any], bool, bool]:
    cached = get_json(_linescore_cache_key(game_pk))
    if isinstance(cached, dict) and isinstance(cached.get("linescore"), dict):
        fetched_at = str(cached.get("fetched_at") or "").strip() or _iso_now()
        return _stamp_payload(cached["linescore"], fetched_at), True, False

    try:
        response = await request_with_retries(
            "GET",
            MLB_STATSAPI_LINESCORE_URL_TEMPLATE.format(game_pk=game_pk),
            timeout=15.0,
            retries=2,
        )
        response.raise_for_status()
        payload = response.json()
        linescore = payload if isinstance(payload, dict) else {}
        wrapped = {"fetched_at": _iso_now(), "linescore": linescore}
        set_json(_linescore_cache_key(game_pk), wrapped, _FRESH_LINESCORE_TTL_SECONDS)
        set_json(_linescore_stale_cache_key(game_pk), wrapped, _STALE_LINESCORE_TTL_SECONDS)
        return _stamp_payload(linescore, wrapped["fetched_at"]), False, False
    except Exception as exc:
        logger.warning(
            "live_tracking.provider.linescore_failed provider=%s sport=%s game_pk=%s err=%s",
            MLB_PROVIDER,
            MLB_SPORT_KEY,
            game_pk,
            exc,
        )
        stale = get_json(_linescore_stale_cache_key(game_pk))
        if isinstance(stale, dict) and isinstance(stale.get("linescore"), dict):
            fetched_at = str(stale.get("fetched_at") or "").strip() or _iso_now()
            return _stamp_payload(stale["linescore"], fetched_at), True, True
        return {}, False, False


def _candidate_dates(candidates: list[LiveBetCandidate], now: datetime | None) -> list[str]:
    dates: list[str] = []
    seen: set[str] = set()

    def _push(date_value: str) -> None:
        if date_value and date_value not in seen:
            seen.add(date_value)
            dates.append(date_value)

    for candidate in candidates:
        commence = _parse_utc_iso(candidate.commence_time)
        for date_value in build_auto_settle_mlb_schedule_dates(commence, now=now, days_around_commence=1):
            _push(date_value)
    if not dates:
        for date_value in build_auto_settle_mlb_schedule_dates(None, now=now, days_around_commence=1):
            _push(date_value)
    return dates


def _event_team_pair(event: LiveEventSnapshot) -> tuple[str, str]:
    return (
        canonical_team_token(event.sport_key, event.away.name),
        canonical_team_token(event.sport_key, event.home.name),
    )


def _candidate_team_pair(candidate: LiveBetCandidate) -> tuple[str, str]:
    return (
        canonical_team_token(candidate.sport_key, candidate.away_team),
        canonical_team_token(candidate.sport_key, candidate.home_team),
    )


def _candidate_team_pairs(candidate: LiveBetCandidate) -> list[tuple[str, str]]:
    away_key, home_key = _candidate_team_pair(candidate)
    if not away_key or not home_key:
        return []
    pairs = [(away_key, home_key)]
    if candidate.surface == "player_props" and away_key != home_key:
        pairs.append((home_key, away_key))
    return pairs


def _score_from_linescore(linescore: dict[str, Any], side: str) -> float | None:
    teams = linescore.get("teams") or {}
    if not isinstance(teams, dict):
        return None
    row = teams.get(side) or {}
    if not isinstance(row, dict):
        return None
    raw = row.get("runs")
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _inning_context_from_linescore(linescore: dict[str, Any]) -> tuple[str | None, str | None]:
    current_inning = linescore.get("currentInning")
    try:
        inning_num = int(current_inning)
    except (TypeError, ValueError):
        inning_num = 0
    if inning_num <= 0:
        return None, None

    inning_ordinal = str(linescore.get("currentInningOrdinal") or "").strip() or f"{inning_num}"
    half = str(linescore.get("inningHalf") or linescore.get("inningState") or "").strip().lower()
    is_top = linescore.get("isTopInning")
    if not half and isinstance(is_top, bool):
        half = "top" if is_top else "bottom"

    if half.startswith("top"):
        return f"T{inning_num}", f"Top {inning_ordinal}"
    if half.startswith("bottom"):
        return f"B{inning_num}", f"Bottom {inning_ordinal}"
    if half.startswith("middle"):
        return f"Mid{inning_num}", f"Middle {inning_ordinal}"
    if half.startswith("end"):
        return f"End{inning_num}", f"End {inning_ordinal}"
    return None, None


def _enrich_mlb_event_with_linescore(
    event: LiveEventSnapshot,
    linescore: dict[str, Any],
) -> LiveEventSnapshot:
    fetched_at = _parse_provider_datetime(linescore.get("_live_fetched_at")) or event.last_updated
    away_score = _score_from_linescore(linescore, "away")
    home_score = _score_from_linescore(linescore, "home")
    away = event.away.model_copy(update={"score": away_score if away_score is not None else event.away.score})
    home = event.home.model_copy(update={"score": home_score if home_score is not None else event.home.score})

    updates: dict[str, Any] = {
        "away": away,
        "home": home,
        "last_updated": fetched_at,
    }
    if event.status == "live":
        period_label, status_detail = _inning_context_from_linescore(linescore)
        if period_label:
            updates["period_label"] = period_label
        if status_detail:
            updates["status_detail"] = status_detail
    return event.model_copy(update=updates)


def _match_event_for_candidate(
    candidate: LiveBetCandidate,
    events: list[LiveEventSnapshot],
) -> tuple[LiveEventSnapshot | None, str, str | None]:
    provider_ids = {
        str(candidate.source_event_id or "").strip(),
        str(candidate.clv_event_id or "").strip(),
    }
    provider_ids.discard("")
    for event in events:
        if event.provider_event_id in provider_ids:
            return event, "provider_event_id", None

    candidate_pairs = _candidate_team_pairs(candidate)
    if not candidate_pairs:
        return None, "unresolved", "missing_team_mapping"

    pair_matches = [
        event for event in events
        if _event_team_pair(event) in candidate_pairs
    ]
    if not pair_matches:
        return None, "unresolved", "no_provider_event_match"

    commence = _parse_utc_iso(candidate.commence_time)
    if commence is not None:
        timed: list[tuple[float, LiveEventSnapshot]] = []
        for event in pair_matches:
            if event.start_time is None:
                continue
            delta = abs(event.start_time - commence)
            if delta <= _MAX_MATCH_DRIFT:
                timed.append((delta.total_seconds(), event))
        timed.sort(key=lambda item: item[0])
        if len(timed) == 1:
            return timed[0][1], "matchup_plus_time", None
        if len(timed) > 1:
            best_delta = timed[0][0]
            if timed[1][0] - best_delta >= _AMBIGUOUS_TIME_GAP.total_seconds():
                return timed[0][1], "matchup_plus_time", None
            return None, "ambiguous", "ambiguous_provider_event_match"
        return None, "unresolved", "kickoff_drift_exceeded"

    if len(pair_matches) == 1:
        return pair_matches[0], "matchup_only", None
    return None, "ambiguous", "ambiguous_provider_event_match"


class MlbLiveProvider:
    provider_name = MLB_PROVIDER

    def supports_sport(self, sport_key: str | None) -> bool:
        return str(sport_key or "").strip().lower() == MLB_SPORT_KEY

    async def lookup_events(
        self,
        candidates: list[LiveBetCandidate],
        *,
        now: datetime | None = None,
    ) -> dict[str, ProviderLookupResult]:
        mlb_candidates = [candidate for candidate in candidates if self.supports_sport(candidate.sport_key)]
        if not mlb_candidates:
            return {}

        rows: list[dict[str, Any]] = []
        any_cache_hit = False
        any_stale = False
        for date_value in _candidate_dates(mlb_candidates, now):
            date_rows, cache_hit, stale = await _fetch_cached_schedule_date(date_value)
            rows.extend(date_rows)
            any_cache_hit = any_cache_hit or cache_hit
            any_stale = any_stale or stale

        normalized: list[LiveEventSnapshot] = []
        seen: set[str] = set()
        for row in rows:
            event = normalize_mlb_game(row)
            if event is None or event.provider_event_id in seen:
                continue
            seen.add(event.provider_event_id)
            normalized.append(event)

        matched: dict[str, tuple[LiveBetCandidate, LiveEventSnapshot | None, str, str | None]] = {}
        live_event_ids: set[str] = set()
        for candidate in mlb_candidates:
            event, confidence, reason = _match_event_for_candidate(candidate, normalized)
            matched[candidate.bet_id] = (candidate, event, confidence, reason)
            if event is not None and event.status == "live":
                live_event_ids.add(event.provider_event_id)

        linescores: dict[str, tuple[dict[str, Any], bool, bool]] = {}
        for provider_event_id in live_event_ids:
            linescores[provider_event_id] = await _fetch_cached_linescore(provider_event_id)

        out: dict[str, ProviderLookupResult] = {}
        for bet_id, (candidate, event, confidence, reason) in matched.items():
            event_cache_hit = any_cache_hit
            event_stale = any_stale
            if event is not None:
                linescore_payload, linescore_cache_hit, linescore_stale = linescores.get(
                    event.provider_event_id,
                    ({}, False, False),
                )
                if linescore_payload:
                    event = _enrich_mlb_event_with_linescore(event, linescore_payload)
                event_cache_hit = event_cache_hit or linescore_cache_hit
                event_stale = event_stale or linescore_stale
            out[bet_id] = ProviderLookupResult(
                candidate=candidate,
                event=event,
                confidence=confidence,
                unavailable_reason=reason,
                cache_hit=event_cache_hit,
                stale=event_stale,
            )
        return out

    async def get_player_stat_snapshots(
        self,
        requests: list[LivePlayerStatRequest],
    ) -> dict[str, ProviderPlayerStatResult]:
        out: dict[str, ProviderPlayerStatResult] = {}
        boxscores: dict[str, tuple[dict[str, Any], bool, bool]] = {}

        for request in requests:
            candidate = request.candidate
            market = str(candidate.market_key or "").strip()
            participant = str(candidate.participant_name or "").strip()
            if not market or not participant:
                out[candidate.bet_id] = ProviderPlayerStatResult(
                    request=request,
                    stat=None,
                    unavailable_reason="missing_prop_identity",
                )
                continue
            if market not in _SUPPORTED_MLB_PROP_MARKETS:
                out[candidate.bet_id] = ProviderPlayerStatResult(
                    request=request,
                    stat=None,
                    unavailable_reason="unsupported_prop_market",
                )
                continue

            if request.provider_event_id not in boxscores:
                boxscores[request.provider_event_id] = await _fetch_cached_boxscore(request.provider_event_id)
            summary, cache_hit, stale = boxscores[request.provider_event_id]
            stat_map = build_player_stat_map(summary, sport=MLB_SPORT_KEY)
            norm = _normalize_player_name(participant)
            player_stats, match_kind = _match_player_stat_key(norm, participant, stat_map)
            if player_stats is None:
                out[candidate.bet_id] = ProviderPlayerStatResult(
                    request=request,
                    stat=None,
                    unavailable_reason="player_stat_not_found",
                    cache_hit=cache_hit,
                    stale=stale,
                )
                continue

            value = _market_stat_value_from_player_stats(MLB_SPORT_KEY, market, player_stats)
            if value is None:
                out[candidate.bet_id] = ProviderPlayerStatResult(
                    request=request,
                    stat=None,
                    unavailable_reason="prop_stat_missing",
                    cache_hit=cache_hit,
                    stale=stale,
                )
                continue

            line_value = candidate.line_value
            progress_ratio = None
            if line_value is not None and line_value > 0:
                progress_ratio = max(0.0, min(1.0, float(value) / float(line_value)))
            stat_key = "B_H_R_RBI" if market == "batter_hits_runs_rbis" else PROP_MARKET_TO_MLB_STAT[market]
            stat = LivePlayerStatSnapshot(
                participant_name=participant,
                stat_key=stat_key,
                stat_label=stat_key,
                value=float(value),
                line_value=line_value,
                selection_side=candidate.selection_side,
                progress_ratio=progress_ratio,
                match_kind=match_kind,  # type: ignore[arg-type]
            )
            out[candidate.bet_id] = ProviderPlayerStatResult(
                request=request,
                stat=stat,
                cache_hit=cache_hit,
                stale=stale,
            )

        return out
