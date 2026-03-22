from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


ESPN_NBA_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_NBA_TEAM_ROSTER_URL_TEMPLATE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
NATIONAL_TV_NETWORKS = ("espn", "tnt", "abc")
SECONDARY_TV_NETWORKS = ("nba tv", "nbatv")
_team_roster_cache: dict[str, dict[str, Any]] = {}


async def fetch_nba_scoreboard() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(ESPN_NBA_SCOREBOARD_URL)
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}


async def fetch_nba_scoreboard_for_date(date_value: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(ESPN_NBA_SCOREBOARD_URL, params={"dates": date_value})
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}


def build_scoreboard_date_window(now: datetime | None = None) -> list[str]:
    anchor = now or datetime.now(timezone.utc)
    anchor_date = anchor.date()
    return [
        (anchor_date - timedelta(days=1)).strftime("%Y%m%d"),
        anchor_date.strftime("%Y%m%d"),
        (anchor_date + timedelta(days=1)).strftime("%Y%m%d"),
    ]


async def fetch_nba_scoreboard_window(now: datetime | None = None) -> dict[str, Any]:
    merged_events: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()

    for date_value in build_scoreboard_date_window(now):
        payload = await fetch_nba_scoreboard_for_date(date_value)
        events = payload.get("events") or []
        if not isinstance(events, list):
            continue
        for event in events:
            event_id = str(event.get("id") or "").strip()
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            merged_events.append(event)

    merged_events.sort(key=lambda event: str(event.get("date") or ""))
    return {"events": merged_events}


async def fetch_team_roster(team_id: str) -> dict[str, Any]:
    cached = _team_roster_cache.get(team_id)
    if cached is not None:
        return cached

    url = ESPN_NBA_TEAM_ROSTER_URL_TEMPLATE.format(team_id=team_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        roster = payload if isinstance(payload, dict) else {}
        _team_roster_cache[team_id] = roster
        return roster


async def build_matchup_player_lookup(
    *,
    home_team_id: str | None,
    home_team_name: str | None,
    away_team_id: str | None,
    away_team_name: str | None,
) -> dict[str, dict[str, str | None]]:
    async def _lookup_for_team(team_id: str | None, team_name: str | None) -> dict[str, dict[str, str | None]]:
        if not team_id or not team_name:
            return {}

        roster = await fetch_team_roster(team_id)
        athletes = roster.get("athletes") or []
        if not isinstance(athletes, list):
            return {}

        entries: dict[str, dict[str, str | None]] = {}
        for athlete in athletes:
            if not isinstance(athlete, dict):
                continue
            athlete_id = str(athlete.get("id") or "").strip() or None
            for field in ("fullName", "displayName", "shortName"):
                value = str(athlete.get(field) or "").strip()
                if not value:
                    continue
                key = "".join(ch for ch in value.lower() if ch.isalnum())
                if not key or key in entries:
                    continue
                entries[key] = {
                    "team": str(team_name).strip() or None,
                    "participant_id": athlete_id,
                }
        return entries

    home_lookup, away_lookup = await asyncio.gather(
        _lookup_for_team(home_team_id, home_team_name),
        _lookup_for_team(away_team_id, away_team_name),
    )
    return {**home_lookup, **away_lookup}


def _canonical_team_name(name: str | None) -> str:
    if not name:
        return ""
    lowered = str(name).strip().lower().replace("los angeles", "la")
    return "".join(ch for ch in lowered if ch.isalnum())


def _extract_broadcast_names(event: dict[str, Any]) -> list[str]:
    names: list[str] = []
    competitions = event.get("competitions") or []
    if not isinstance(competitions, list):
        return names

    for competition in competitions:
        broadcasts = competition.get("broadcasts") or []
        if not isinstance(broadcasts, list):
            continue
        for broadcast in broadcasts:
            for key in ("names", "shortName", "market", "type"):
                value = broadcast.get(key)
                if isinstance(value, list):
                    names.extend(str(item) for item in value if item)
                elif value:
                    names.append(str(value))
    return names


def _extract_matchup(event: dict[str, Any]) -> dict[str, str] | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competitors = (competitions[0] or {}).get("competitors") or []
    home_team = None
    away_team = None
    home_team_id = None
    away_team_id = None
    for competitor in competitors:
        team = competitor.get("team") or {}
        display_name = str(team.get("displayName") or "").strip()
        team_id = str(team.get("id") or "").strip()
        home_away = str(competitor.get("homeAway") or "").strip().lower()
        if not display_name:
            continue
        if home_away == "home":
            home_team = display_name
            home_team_id = team_id
        elif home_away == "away":
            away_team = display_name
            away_team_id = team_id

    if not home_team or not away_team:
        return None

    return {
        "event_id": str(event.get("id") or "").strip(),
        "home_team": home_team,
        "home_team_id": home_team_id,
        "away_team": away_team,
        "away_team_id": away_team_id,
        "home_team_key": _canonical_team_name(home_team),
        "away_team_key": _canonical_team_name(away_team),
    }


def extract_national_tv_matchups(scoreboard_payload: dict[str, Any], max_games: int = 3) -> list[dict[str, str]]:
    events = scoreboard_payload.get("events") or []
    if not isinstance(events, list):
        return []

    primary: list[dict[str, str]] = []
    secondary: list[dict[str, str]] = []
    fallback: list[dict[str, str]] = []
    for event in events:
        broadcast_names = _extract_broadcast_names(event)
        broadcast_blob = " ".join(broadcast_names).lower()
        matchup = _extract_matchup(event)
        if not matchup:
            continue
        matchup["broadcasts"] = broadcast_names

        if any(network in broadcast_blob for network in NATIONAL_TV_NETWORKS):
            matchup["selection_reason"] = "national_tv"
            primary.append(matchup)
        elif any(network in broadcast_blob for network in SECONDARY_TV_NETWORKS):
            matchup["selection_reason"] = "nba_tv"
            secondary.append(matchup)
        else:
            matchup["selection_reason"] = "scoreboard_fallback"
            fallback.append(matchup)

    return (primary + secondary + fallback)[:max_games]
