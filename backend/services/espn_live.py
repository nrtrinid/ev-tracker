from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from models import LiveEventSnapshot, LivePlayerStatSnapshot, LiveTeamScore
from services.espn_scoreboard import (
    build_auto_settle_scoreboard_dates,
    fetch_nba_game_summary,
    fetch_nba_scoreboard_for_date,
)
from services.live_provider_contracts import (
    LiveBetCandidate,
    LivePlayerStatRequest,
    ProviderLookupResult,
    ProviderPlayerStatResult,
)
from services.prop_settler import (
    NBA_SPORT_KEY,
    PROP_MARKET_TO_ESPN_STAT,
    _market_stat_value_from_player_stats,
    _match_player_stat_key,
    _normalize_player_name,
    _parse_utc_iso,
    build_player_stat_map,
)
from services.shared_state import get_json, set_json
from services.team_aliases import canonical_short_name, canonical_team_token

logger = logging.getLogger("ev_tracker.live_tracking")

ESPN_PROVIDER = "espn"
_FRESH_EVENT_TTL_SECONDS = 60
_STALE_EVENT_TTL_SECONDS = 10 * 60
_FRESH_SUMMARY_TTL_SECONDS = 60
_STALE_SUMMARY_TTL_SECONDS = 10 * 60
_MAX_MATCH_DRIFT = timedelta(hours=18)


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


def _status_from_espn(status: dict[str, Any]) -> str:
    type_info = status.get("type") if isinstance(status, dict) else {}
    if not isinstance(type_info, dict):
        type_info = {}
    state = str(type_info.get("state") or status.get("state") or "").strip().lower()
    name = str(type_info.get("name") or "").strip().lower()
    description = str(type_info.get("description") or status.get("description") or "").strip().lower()
    detail_blob = " ".join(part for part in (state, name, description) if part)

    if bool(type_info.get("completed")) or state in {"post", "final"} or "final" in detail_blob:
        return "final"
    if "postpon" in detail_blob:
        return "postponed"
    if "cancel" in detail_blob or "canceled" in detail_blob:
        return "cancelled"
    if "delay" in detail_blob:
        return "delayed"
    if state in {"in", "live"} or "progress" in detail_blob or "halftime" in detail_blob:
        return "live"
    if state in {"pre", "scheduled"} or "scheduled" in detail_blob:
        return "scheduled"
    return "unknown"


def _score_from_competitor(competitor: dict[str, Any]) -> float | None:
    raw = competitor.get("score")
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _team_from_competitor(
    sport_key: str,
    competitor: dict[str, Any],
) -> LiveTeamScore | None:
    team = competitor.get("team") or {}
    if not isinstance(team, dict):
        return None
    name = str(team.get("displayName") or team.get("name") or "").strip()
    home_away = str(competitor.get("homeAway") or "").strip().lower()
    if home_away not in {"home", "away"} or not name:
        return None
    abbreviation = str(team.get("abbreviation") or "").strip()
    return LiveTeamScore(
        name=name,
        short_name=abbreviation or canonical_short_name(sport_key, name),
        score=_score_from_competitor(competitor),
        home_away=home_away,  # type: ignore[arg-type]
    )


def _period_label(status: dict[str, Any], sport_key: str) -> str | None:
    period = status.get("period") if isinstance(status, dict) else None
    try:
        period_num = int(period)
    except (TypeError, ValueError):
        period_num = 0
    if period_num <= 0:
        return None
    if sport_key == NBA_SPORT_KEY:
        if period_num <= 4:
            return f"Q{period_num}"
        return f"OT{period_num - 4}"
    return str(period_num)


def normalize_espn_nba_event(event: dict[str, Any], *, stale: bool = False) -> LiveEventSnapshot | None:
    """Normalize an ESPN NBA scoreboard event into the app live-event contract."""
    event_id = str(event.get("id") or "").strip()
    competitions = event.get("competitions") or []
    if not event_id or not isinstance(competitions, list) or not competitions:
        return None
    competition = competitions[0] or {}
    if not isinstance(competition, dict):
        return None
    competitors = competition.get("competitors") or []
    if not isinstance(competitors, list):
        return None

    home: LiveTeamScore | None = None
    away: LiveTeamScore | None = None
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        team_score = _team_from_competitor(NBA_SPORT_KEY, competitor)
        if team_score is None:
            continue
        if team_score.home_away == "home":
            home = team_score
        elif team_score.home_away == "away":
            away = team_score

    if home is None or away is None:
        return None

    status = competition.get("status") or event.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    type_info = status.get("type") if isinstance(status.get("type"), dict) else {}
    status_detail = (
        str(status.get("shortDetail") or status.get("detail") or "").strip()
        or str(type_info.get("shortDetail") or type_info.get("description") or "").strip()
        or None
    )
    last_updated = _parse_provider_datetime(status.get("clock")) or _utc_now()

    return LiveEventSnapshot(
        provider=ESPN_PROVIDER,
        provider_event_id=event_id,
        sport_key=NBA_SPORT_KEY,
        status=_status_from_espn(status),  # type: ignore[arg-type]
        status_detail=status_detail,
        period_label=_period_label(status, NBA_SPORT_KEY),
        clock=str(status.get("displayClock") or "").strip() or None,
        start_time=_parse_provider_datetime(event.get("date")),
        last_updated=last_updated,
        home=home,
        away=away,
    )


def _event_cache_key(date_value: str) -> str:
    return f"live:provider:{ESPN_PROVIDER}:{NBA_SPORT_KEY}:scoreboard:{date_value}:fresh"


def _event_stale_cache_key(date_value: str) -> str:
    return f"live:provider:{ESPN_PROVIDER}:{NBA_SPORT_KEY}:scoreboard:{date_value}:last-good"


def _summary_cache_key(event_id: str) -> str:
    return f"live:provider:{ESPN_PROVIDER}:{NBA_SPORT_KEY}:summary:{event_id}:fresh"


def _summary_stale_cache_key(event_id: str) -> str:
    return f"live:provider:{ESPN_PROVIDER}:{NBA_SPORT_KEY}:summary:{event_id}:last-good"


async def _fetch_cached_scoreboard_date(date_value: str) -> tuple[list[dict[str, Any]], bool, bool]:
    cached = get_json(_event_cache_key(date_value))
    if isinstance(cached, dict) and isinstance(cached.get("events"), list):
        return [event for event in cached["events"] if isinstance(event, dict)], True, False

    try:
        payload = await fetch_nba_scoreboard_for_date(date_value)
        events = payload.get("events") if isinstance(payload, dict) else []
        event_rows = [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []
        wrapped = {"fetched_at": _iso_now(), "events": event_rows}
        set_json(_event_cache_key(date_value), wrapped, _FRESH_EVENT_TTL_SECONDS)
        set_json(_event_stale_cache_key(date_value), wrapped, _STALE_EVENT_TTL_SECONDS)
        return event_rows, False, False
    except Exception as exc:
        logger.warning(
            "live_tracking.provider.scoreboard_failed provider=%s sport=%s date=%s err=%s",
            ESPN_PROVIDER,
            NBA_SPORT_KEY,
            date_value,
            exc,
        )
        stale = get_json(_event_stale_cache_key(date_value))
        if isinstance(stale, dict) and isinstance(stale.get("events"), list):
            return [event for event in stale["events"] if isinstance(event, dict)], True, True
        return [], False, False


async def _fetch_cached_summary(event_id: str) -> tuple[dict[str, Any], bool, bool]:
    cached = get_json(_summary_cache_key(event_id))
    if isinstance(cached, dict) and isinstance(cached.get("summary"), dict):
        return cached["summary"], True, False

    try:
        summary = await fetch_nba_game_summary(event_id)
        wrapped = {"fetched_at": _iso_now(), "summary": summary}
        set_json(_summary_cache_key(event_id), wrapped, _FRESH_SUMMARY_TTL_SECONDS)
        set_json(_summary_stale_cache_key(event_id), wrapped, _STALE_SUMMARY_TTL_SECONDS)
        return summary, False, False
    except Exception as exc:
        logger.warning(
            "live_tracking.provider.summary_failed provider=%s sport=%s event_id=%s err=%s",
            ESPN_PROVIDER,
            NBA_SPORT_KEY,
            event_id,
            exc,
        )
        stale = get_json(_summary_stale_cache_key(event_id))
        if isinstance(stale, dict) and isinstance(stale.get("summary"), dict):
            return stale["summary"], True, True
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
        for date_value in build_auto_settle_scoreboard_dates(commence, now=now, days_around_commence=1):
            _push(date_value)
    if not dates:
        for date_value in build_auto_settle_scoreboard_dates(None, now=now, days_around_commence=1):
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
            if timed[1][0] - best_delta >= 60 * 60:
                return timed[0][1], "matchup_plus_time", None
            return None, "ambiguous", "ambiguous_provider_event_match"

    if len(pair_matches) == 1:
        return pair_matches[0], "matchup_only", None
    return None, "ambiguous", "ambiguous_provider_event_match"


def _candidate_event_time_delta(candidate: LiveBetCandidate, event: LiveEventSnapshot) -> float | None:
    commence = _parse_utc_iso(candidate.commence_time)
    if commence is None or event.start_time is None:
        return None
    delta = abs(event.start_time - commence)
    if delta > _MAX_MATCH_DRIFT:
        return None
    return delta.total_seconds()


def _candidate_player_summary_events(
    candidate: LiveBetCandidate,
    events: list[LiveEventSnapshot],
) -> list[LiveEventSnapshot]:
    timed: list[tuple[float, LiveEventSnapshot]] = []
    untimed: list[LiveEventSnapshot] = []
    for event in events:
        delta = _candidate_event_time_delta(candidate, event)
        if delta is not None:
            timed.append((delta, event))
        elif _parse_utc_iso(candidate.commence_time) is None:
            untimed.append(event)
    timed.sort(key=lambda item: item[0])
    return [event for _, event in timed] + untimed


async def _match_event_by_player_summary(
    candidate: LiveBetCandidate,
    events: list[LiveEventSnapshot],
) -> tuple[LiveEventSnapshot | None, str, str | None, bool, bool]:
    participant = str(candidate.participant_name or "").strip()
    if candidate.surface != "player_props" or not participant:
        return None, "unresolved", "missing_team_mapping", False, False

    norm = _normalize_player_name(participant)
    matches: list[LiveEventSnapshot] = []
    any_cache_hit = False
    any_stale = False
    for event in _candidate_player_summary_events(candidate, events):
        if event.status not in {"live", "final"}:
            continue
        summary, cache_hit, stale = await _fetch_cached_summary(event.provider_event_id)
        any_cache_hit = any_cache_hit or cache_hit
        any_stale = any_stale or stale
        stat_map = build_player_stat_map(summary, sport=NBA_SPORT_KEY)
        player_stats, _match_kind = _match_player_stat_key(norm, participant, stat_map)
        if player_stats is not None:
            matches.append(event)

    if len(matches) == 1:
        return matches[0], "player_summary", None, any_cache_hit, any_stale
    if len(matches) > 1:
        return None, "ambiguous", "ambiguous_provider_event_match", any_cache_hit, any_stale
    return None, "unresolved", "player_stat_not_found", any_cache_hit, any_stale


class EspnLiveProvider:
    provider_name = ESPN_PROVIDER

    def supports_sport(self, sport_key: str | None) -> bool:
        return str(sport_key or "").strip().lower() == NBA_SPORT_KEY

    async def lookup_events(
        self,
        candidates: list[LiveBetCandidate],
        *,
        now: datetime | None = None,
    ) -> dict[str, ProviderLookupResult]:
        nba_candidates = [candidate for candidate in candidates if self.supports_sport(candidate.sport_key)]
        if not nba_candidates:
            return {}

        rows: list[dict[str, Any]] = []
        any_cache_hit = False
        any_stale = False
        for date_value in _candidate_dates(nba_candidates, now):
            date_rows, cache_hit, stale = await _fetch_cached_scoreboard_date(date_value)
            rows.extend(date_rows)
            any_cache_hit = any_cache_hit or cache_hit
            any_stale = any_stale or stale

        normalized: list[LiveEventSnapshot] = []
        seen: set[str] = set()
        for row in rows:
            event = normalize_espn_nba_event(row, stale=any_stale)
            if event is None or event.provider_event_id in seen:
                continue
            seen.add(event.provider_event_id)
            normalized.append(event)

        out: dict[str, ProviderLookupResult] = {}
        for candidate in nba_candidates:
            event, confidence, reason = _match_event_for_candidate(candidate, normalized)
            candidate_cache_hit = any_cache_hit
            candidate_stale = any_stale
            if event is None and reason == "missing_team_mapping":
                event, confidence, reason, summary_cache_hit, summary_stale = await _match_event_by_player_summary(
                    candidate,
                    normalized,
                )
                candidate_cache_hit = candidate_cache_hit or summary_cache_hit
                candidate_stale = candidate_stale or summary_stale
            out[candidate.bet_id] = ProviderLookupResult(
                candidate=candidate,
                event=event,
                confidence=confidence,
                unavailable_reason=reason,
                cache_hit=candidate_cache_hit,
                stale=candidate_stale,
            )
        return out

    async def get_player_stat_snapshots(
        self,
        requests: list[LivePlayerStatRequest],
    ) -> dict[str, ProviderPlayerStatResult]:
        out: dict[str, ProviderPlayerStatResult] = {}
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
            if market not in PROP_MARKET_TO_ESPN_STAT and market != "player_points_rebounds_assists":
                out[candidate.bet_id] = ProviderPlayerStatResult(
                    request=request,
                    stat=None,
                    unavailable_reason="unsupported_prop_market",
                )
                continue

            summary, cache_hit, stale = await _fetch_cached_summary(request.provider_event_id)
            stat_map = build_player_stat_map(summary, sport=NBA_SPORT_KEY)
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
            value = _market_stat_value_from_player_stats(NBA_SPORT_KEY, market, player_stats)
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
            stat_key = "PTS_REB_AST" if market == "player_points_rebounds_assists" else PROP_MARKET_TO_ESPN_STAT[market]
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
