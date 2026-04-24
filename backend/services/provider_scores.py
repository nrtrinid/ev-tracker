from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from services.espn_scoreboard import _extract_matchup
from services.prop_settler import (
    MLB_SPORT_KEY,
    NBA_SPORT_KEY,
    _event_completed,
    _mlb_event_completed,
    _mlb_extract_matchup,
    _parse_espn_event_datetime,
    _parse_mlb_game_datetime,
    _parse_utc_iso,
    fetch_boxscore_provider_events_for_rows,
)

AUTO_SETTLE_SCORE_SOURCE_ENV = "AUTO_SETTLE_SCORE_SOURCE"
AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS_ENV = "AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS"
AUTO_SETTLE_PROVIDER_FINALITY_DELAY_MINUTES_ENV = "AUTO_SETTLE_PROVIDER_FINALITY_DELAY_MINUTES"

SCORE_SOURCE_PROVIDER_FIRST = "provider_first"
SCORE_SOURCE_ODDS_API = "odds_api"
SUPPORTED_PROVIDER_SCORE_SPORTS = {NBA_SPORT_KEY, MLB_SPORT_KEY}

_FINALITY_DELAY_DEFAULT_MINUTES = 15
_NBA_MIN_FINAL_ELAPSED = timedelta(hours=2)
_MLB_MIN_FINAL_ELAPSED = timedelta(hours=2, minutes=30)


@dataclass
class ProviderCompletedEventsResult:
    completed_by_sport: dict[str, list[dict[str, Any]]]
    telemetry: dict[str, Any]


def auto_settle_score_source() -> str:
    raw = str(os.getenv(AUTO_SETTLE_SCORE_SOURCE_ENV) or SCORE_SOURCE_PROVIDER_FIRST).strip().lower()
    if raw in {SCORE_SOURCE_PROVIDER_FIRST, "provider", "providers"}:
        return SCORE_SOURCE_PROVIDER_FIRST
    if raw in {SCORE_SOURCE_ODDS_API, "odds", "scores"}:
        return SCORE_SOURCE_ODDS_API
    return SCORE_SOURCE_PROVIDER_FIRST


def auto_settle_provider_fallback_to_odds() -> bool:
    raw = str(os.getenv(AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def auto_settle_provider_finality_delay_minutes() -> int:
    raw = str(os.getenv(AUTO_SETTLE_PROVIDER_FINALITY_DELAY_MINUTES_ENV) or "").strip()
    if not raw:
        return _FINALITY_DELAY_DEFAULT_MINUTES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _FINALITY_DELAY_DEFAULT_MINUTES
    return max(0, min(value, 240))


def _score_value(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _score_text(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _parse_provider_datetime(raw: Any) -> datetime | None:
    return _parse_utc_iso(str(raw) if raw else None)


def _extract_provider_final_at(payload: dict[str, Any]) -> datetime | None:
    candidate_keys = (
        "final_at",
        "finalAt",
        "completed_at",
        "completedAt",
        "endTime",
        "end_time",
        "lastUpdated",
        "last_updated",
    )
    for key in candidate_keys:
        parsed = _parse_provider_datetime(payload.get(key))
        if parsed is not None:
            return parsed

    status = payload.get("status") or {}
    if isinstance(status, dict):
        for key in candidate_keys:
            parsed = _parse_provider_datetime(status.get(key))
            if parsed is not None:
                return parsed
        type_info = status.get("type") or {}
        if isinstance(type_info, dict):
            for key in candidate_keys:
                parsed = _parse_provider_datetime(type_info.get(key))
                if parsed is not None:
                    return parsed
    return None


def _finality_ready(
    *,
    sport: str,
    payload: dict[str, Any],
    start_time: datetime | None,
    now: datetime,
    finality_delay: timedelta,
) -> bool:
    final_at = _extract_provider_final_at(payload)
    if final_at is not None:
        return now >= final_at + finality_delay

    if start_time is None:
        return True

    minimum_elapsed = _NBA_MIN_FINAL_ELAPSED if sport == NBA_SPORT_KEY else _MLB_MIN_FINAL_ELAPSED
    return now >= start_time + minimum_elapsed + finality_delay


def normalize_espn_nba_completed_event(
    event: dict[str, Any],
    *,
    now: datetime | None = None,
    finality_delay_minutes: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(event, dict):
        return None, "invalid_event"
    if not _event_completed(event):
        return None, "not_final"

    matchup = _extract_matchup(event)
    if not matchup:
        return None, "missing_matchup"

    competitions = event.get("competitions") or []
    competition = competitions[0] if isinstance(competitions, list) and competitions else {}
    competitors = competition.get("competitors") if isinstance(competition, dict) else []
    if not isinstance(competitors, list):
        return None, "missing_scores"

    scores_by_side: dict[str, float] = {}
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        side = str(competitor.get("homeAway") or "").strip().lower()
        score = _score_value(competitor.get("score"))
        if side in {"home", "away"} and score is not None:
            scores_by_side[side] = score

    if "home" not in scores_by_side or "away" not in scores_by_side:
        return None, "missing_scores"

    start_time = _parse_espn_event_datetime(event)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    delay = timedelta(
        minutes=auto_settle_provider_finality_delay_minutes()
        if finality_delay_minutes is None
        else max(0, int(finality_delay_minutes))
    )
    if not _finality_ready(
        sport=NBA_SPORT_KEY,
        payload=event,
        start_time=start_time,
        now=current,
        finality_delay=delay,
    ):
        return None, "finality_delay"

    event_id = str(matchup.get("event_id") or event.get("id") or "").strip()
    home_team = str(matchup.get("home_team") or "").strip()
    away_team = str(matchup.get("away_team") or "").strip()
    if not event_id or not home_team or not away_team:
        return None, "missing_matchup"

    return (
        {
            "id": f"espn:{event_id}",
            "provider_event_id": event_id,
            "source_provider": "espn",
            "sport_key": NBA_SPORT_KEY,
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": start_time.isoformat().replace("+00:00", "Z") if start_time else None,
            "completed": True,
            "scores": [
                {"name": home_team, "score": _score_text(scores_by_side["home"])},
                {"name": away_team, "score": _score_text(scores_by_side["away"])},
            ],
        },
        None,
    )


def normalize_mlb_completed_event(
    game: dict[str, Any],
    *,
    now: datetime | None = None,
    finality_delay_minutes: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(game, dict):
        return None, "invalid_event"
    if not _mlb_event_completed(game):
        return None, "not_final"

    matchup = _mlb_extract_matchup(game)
    if not matchup:
        return None, "missing_matchup"

    teams = game.get("teams") or {}
    if not isinstance(teams, dict):
        return None, "missing_scores"

    home_score = _score_value((teams.get("home") or {}).get("score"))
    away_score = _score_value((teams.get("away") or {}).get("score"))
    if home_score is None or away_score is None:
        return None, "missing_scores"

    start_time = _parse_mlb_game_datetime(game)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    delay = timedelta(
        minutes=auto_settle_provider_finality_delay_minutes()
        if finality_delay_minutes is None
        else max(0, int(finality_delay_minutes))
    )
    if not _finality_ready(
        sport=MLB_SPORT_KEY,
        payload=game,
        start_time=start_time,
        now=current,
        finality_delay=delay,
    ):
        return None, "finality_delay"

    game_pk = str(matchup.get("event_id") or game.get("gamePk") or "").strip()
    home_team = str(matchup.get("home_team") or "").strip()
    away_team = str(matchup.get("away_team") or "").strip()
    if not game_pk or not home_team or not away_team:
        return None, "missing_matchup"

    return (
        {
            "id": f"mlb_statsapi:{game_pk}",
            "provider_event_id": game_pk,
            "source_provider": "mlb_statsapi",
            "sport_key": MLB_SPORT_KEY,
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": start_time.isoformat().replace("+00:00", "Z") if start_time else None,
            "completed": True,
            "scores": [
                {"name": home_team, "score": _score_text(home_score)},
                {"name": away_team, "score": _score_text(away_score)},
            ],
        },
        None,
    )


def _normalize_provider_completed_events_for_sport(
    sport: str,
    provider_events: list[dict[str, Any]],
    *,
    now: datetime,
    finality_delay_minutes: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    completed: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for provider_event in provider_events:
        if sport == NBA_SPORT_KEY:
            normalized, reason = normalize_espn_nba_completed_event(
                provider_event,
                now=now,
                finality_delay_minutes=finality_delay_minutes,
            )
        elif sport == MLB_SPORT_KEY:
            normalized, reason = normalize_mlb_completed_event(
                provider_event,
                now=now,
                finality_delay_minutes=finality_delay_minutes,
            )
        else:
            normalized, reason = None, "unsupported_sport"

        if normalized is not None:
            completed.append(normalized)
            continue
        skipped[str(reason or "unknown")] = skipped.get(str(reason or "unknown"), 0) + 1

    return completed, skipped


async def fetch_provider_completed_events_for_auto_settle(
    rows: list[dict[str, Any]],
    *,
    sport_keys: set[str],
    now: datetime | None = None,
    finality_delay_minutes: int | None = None,
) -> ProviderCompletedEventsResult:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    delay_minutes = (
        auto_settle_provider_finality_delay_minutes()
        if finality_delay_minutes is None
        else max(0, int(finality_delay_minutes))
    )
    completed_by_sport: dict[str, list[dict[str, Any]]] = {}
    telemetry: dict[str, Any] = {
        "score_source": SCORE_SOURCE_PROVIDER_FIRST,
        "provider_score_supported_sports": [],
        "provider_score_fetch_errors": [],
        "provider_completed_events": {},
        "provider_completed_event_count": 0,
        "provider_finality_delay_skipped": {},
        "provider_skipped_events": {},
        "provider_fallback_sports": [],
        "odds_api_score_sports": [],
        "odds_api_completed_events": {},
    }

    supported_sports = sorted(str(sport or "").strip().lower() for sport in sport_keys if sport in SUPPORTED_PROVIDER_SCORE_SPORTS)
    telemetry["provider_score_supported_sports"] = supported_sports

    for sport in supported_sports:
        sport_rows = [row for row in rows if str(row.get("sport") or "").strip().lower() == sport]
        if not sport_rows:
            sport_rows = [{"sport": sport, "commence_time": None}]
        try:
            provider_events_by_sport = await fetch_boxscore_provider_events_for_rows(
                sport_rows,
                sport_field="sport",
                commence_time_field="commence_time",
                now=current,
            )
            provider_events = provider_events_by_sport.get(sport) or []
            completed, skipped = _normalize_provider_completed_events_for_sport(
                sport,
                provider_events,
                now=current,
                finality_delay_minutes=delay_minutes,
            )
            completed_by_sport[sport] = completed
            telemetry["provider_completed_events"][sport] = len(completed)
            telemetry["provider_completed_event_count"] = int(telemetry["provider_completed_event_count"]) + len(completed)
            telemetry["provider_skipped_events"][sport] = skipped
            if skipped.get("finality_delay"):
                telemetry["provider_finality_delay_skipped"][sport] = skipped["finality_delay"]
        except Exception as exc:
            completed_by_sport[sport] = []
            telemetry["provider_completed_events"][sport] = 0
            telemetry["provider_score_fetch_errors"].append(
                {"sport_key": sport, "error": f"{type(exc).__name__}: {exc}"}
            )

    return ProviderCompletedEventsResult(
        completed_by_sport=completed_by_sport,
        telemetry=telemetry,
    )
