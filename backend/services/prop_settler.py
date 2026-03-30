"""
Auto-settlement for player props (NBA) and parlays whose legs are ML + props.

Uses The Odds API completed events for game matching and ESPN game summary
for per-player boxscore stats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

_ESPN_RESOLVE_LOG_CAP = 80

from services.espn_scoreboard import (
    _canonical_team_name,
    _extract_matchup,
    build_auto_settle_scoreboard_dates,
    build_scoreboard_date_window,
    fetch_nba_game_summary,
    fetch_nba_scoreboard_for_dates,
)

PROP_MARKET_TO_ESPN_STAT = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_threes": "3PM",
}

NBA_SPORT_KEY = "basketball_nba"

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


def create_prop_settle_telemetry() -> dict[str, Any]:
    return {
        "espn_resolve_log": [],
        "espn_resolve_score_verified": 0,
        "espn_resolve_matchup_plus_time": 0,
        "espn_resolve_fallback_time_only": 0,
        "props_espn_resolved": 0,
        "props_player_match_exact": 0,
        "props_player_match_fuzzy": 0,
        "props_player_not_found": 0,
        "props_stat_missing": 0,
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
    Map bet participant string to ESPN boxscore row.

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


def build_player_stat_map(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
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


def _espn_resolve_cache_key(
    hk: str,
    ak: str,
    commence_time: str | None,
) -> tuple[str, str, str]:
    """Include kickoff calendar day so Lakers@Celtics on different dates do not collide."""
    bet_dt = _parse_utc_iso(commence_time)
    day = bet_dt.strftime("%Y-%m-%d") if bet_dt else "_"
    a, b = sorted([hk, ak])
    return (a, b, day)


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


def grade_prop(
    player_name: str | None,
    market_key: str,
    line_value: float | None,
    selection_side: str | None,
    stat_map: dict[str, dict[str, float]],
) -> tuple[str | None, dict[str, Any]]:
    """Return (win|loss|push|None, detail) for telemetry (player_match, stat_present)."""
    detail: dict[str, Any] = {
        "player_match": "n_a",
        "stat_present": False,
    }
    stat_col = PROP_MARKET_TO_ESPN_STAT.get(str(market_key).strip())
    if not stat_col:
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

    actual = player_stats.get(stat_col)
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
    )


async def grade_parlay_prop_leg(
    leg: dict[str, Any],
    completed_events_by_sport: dict[str, list[dict]],
    espn_summary_cache: dict[str, dict[str, Any]],
    espn_resolve_cache: dict[tuple[str, str, str], EspnResolveResult],
    *,
    now: datetime | None = None,
    scoreboard_events: list[dict[str, Any]] | None = None,
    telemetry: dict[str, Any] | None = None,
    ref_id: str | None = None,
) -> str | None:
    from services.odds_api import _select_completed_event_for_bet

    sport = str(leg.get("sport") or "").strip()
    if sport != NBA_SPORT_KEY:
        return None

    mk = str(leg.get("marketKey") or leg.get("market_key") or "").strip()
    if mk not in PROP_MARKET_TO_ESPN_STAT:
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

    res = await resolve_espn_event_id(
        home,
        away,
        synthetic.get("commence_time"),
        odds_completed_event=event,
        cache=espn_resolve_cache,
        now=now,
        scoreboard_events=scoreboard_events,
        telemetry=telemetry,
        context="parlay_leg",
        ref_id=ref_id,
    )
    espn_id = res.espn_event_id
    if not espn_id:
        return None

    if espn_id not in espn_summary_cache:
        try:
            espn_summary_cache[espn_id] = await fetch_nba_game_summary(espn_id)
        except Exception:
            espn_summary_cache[espn_id] = {}

    summary = espn_summary_cache.get(espn_id) or {}
    stat_map = build_player_stat_map(summary)
    grade, detail = grade_prop(player, mk, line_raw, side, stat_map)
    _record_prop_grade_telemetry(telemetry, grade, detail)
    return grade


async def grade_parlay_leg(
    leg: dict[str, Any],
    completed_events_by_sport: dict[str, list[dict]],
    espn_summary_cache: dict[str, dict[str, Any]],
    espn_resolve_cache: dict[tuple[str, str, str], EspnResolveResult],
    *,
    now: datetime | None = None,
    scoreboard_events: list[dict[str, Any]] | None = None,
    telemetry: dict[str, Any] | None = None,
    prop_ref_id: str | None = None,
) -> str | None:
    surface = str(leg.get("surface") or "").strip().lower()
    if surface == "player_props":
        return await grade_parlay_prop_leg(
            leg,
            completed_events_by_sport,
            espn_summary_cache,
            espn_resolve_cache,
            now=now,
            scoreboard_events=scoreboard_events,
            telemetry=telemetry,
            ref_id=prop_ref_id,
        )
    if surface == "straight_bets":
        return grade_parlay_ml_leg(leg, completed_events_by_sport)
    return None


def _nba_scoreboard_date_union_prop_bets(
    prop_bets: list[dict[str, Any]],
    *,
    now: datetime | None,
) -> list[str]:
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    dates: set[str] = set(build_scoreboard_date_window(anchor))
    for bet in prop_bets:
        if str(bet.get("clv_sport_key") or "").strip() != NBA_SPORT_KEY:
            continue
        bet_dt = _parse_utc_iso(bet.get("commence_time"))
        dates.update(build_auto_settle_scoreboard_dates(bet_dt, now=now))
    return sorted(dates)


def _nba_scoreboard_date_union_parlays(
    parlay_bets: list[dict[str, Any]],
    *,
    now: datetime,
) -> list[str]:
    dates: set[str] = set(build_scoreboard_date_window(now))
    for bet in parlay_bets:
        meta = bet.get("selection_meta")
        if not isinstance(meta, dict):
            continue
        for leg in meta.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            if str(leg.get("sport") or "").strip() != NBA_SPORT_KEY:
                continue
            if str(leg.get("surface") or "").strip().lower() != "player_props":
                continue
            ct = leg.get("commenceTime") or leg.get("commence_time")
            bet_dt = _parse_utc_iso(str(ct) if ct else None)
            dates.update(build_auto_settle_scoreboard_dates(bet_dt, now=now))
    return sorted(dates)


def is_standalone_prop_bet(bet: dict[str, Any]) -> bool:
    surface = str(bet.get("surface") or "").strip().lower()
    if surface != "player_props":
        return False
    mk = str(bet.get("source_market_key") or "").strip()
    return mk in PROP_MARKET_TO_ESPN_STAT


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
        "espn_resolve_failed": 0,
        "espn_fetch_failed": 0,
        "ungraded_prop": 0,
        "db_update_failed": 0,
    }
    settled = 0
    espn_summary_cache: dict[str, dict[str, Any]] = {}
    espn_resolve_cache: dict[tuple[str, str, str], EspnResolveResult] = {}

    scoreboard_events: list[dict[str, Any]] | None = None
    if any(str(b.get("clv_sport_key") or "").strip() == NBA_SPORT_KEY for b in prop_bets):
        date_union = _nba_scoreboard_date_union_prop_bets(prop_bets, now=now)
        merged = await fetch_nba_scoreboard_for_dates(date_union)
        raw = merged.get("events") or []
        scoreboard_events = [e for e in raw if isinstance(e, dict)]

    for bet in prop_bets:
        sport = str(bet.get("clv_sport_key") or "").strip()
        if sport != NBA_SPORT_KEY:
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
        res = await resolve_espn_event_id(
            home,
            away,
            bet.get("commence_time"),
            odds_completed_event=event,
            cache=espn_resolve_cache,
            now=now,
            scoreboard_events=scoreboard_events,
            telemetry=telemetry,
            context="standalone_prop",
            ref_id=str(bet.get("id")) if bet.get("id") is not None else None,
        )
        espn_id = res.espn_event_id
        if not espn_id:
            skipped["espn_resolve_failed"] += 1
            print(
                f"[Auto-Settler:props] bet {bet.get('id')} ESPN id not resolved "
                f"({res.confidence_tier})"
            )
            continue

        if espn_id not in espn_summary_cache:
            try:
                espn_summary_cache[espn_id] = await fetch_nba_game_summary(espn_id)
            except Exception as e:
                skipped["espn_fetch_failed"] += 1
                print(f"[Auto-Settler:props] ESPN fetch failed for {espn_id}: {e}")
                continue

        stat_map = build_player_stat_map(espn_summary_cache[espn_id])
        mk = str(bet.get("source_market_key") or "").strip()
        grade, g_detail = grade_prop(
            bet.get("participant_name"),
            mk,
            bet.get("line_value"),
            bet.get("selection_side"),
            stat_map,
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
    espn_summary_cache: dict[str, dict[str, Any]] = {}
    espn_resolve_cache: dict[tuple[str, str, str], EspnResolveResult] = {}

    if parlay_bets:
        parlay_date_union = _nba_scoreboard_date_union_parlays(parlay_bets, now=now)
        parlay_merged = await fetch_nba_scoreboard_for_dates(parlay_date_union)
        parlay_raw = parlay_merged.get("events") or []
        parlay_scoreboard_events = [e for e in parlay_raw if isinstance(e, dict)]
    else:
        parlay_scoreboard_events = []

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
                espn_summary_cache,
                espn_resolve_cache,
                now=now,
                scoreboard_events=parlay_scoreboard_events,
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


def collect_sport_keys_from_parlays(parlay_bets: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for bet in parlay_bets:
        meta = bet.get("selection_meta")
        if not isinstance(meta, dict):
            continue
        for leg in meta.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            s = str(leg.get("sport") or "").strip()
            if s:
                keys.add(s)
    return keys
