from __future__ import annotations

import copy
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from calculations import calculate_clv
from services.model_calibration import update_scan_opportunity_model_evaluations_close_snapshot

CLOSE_WINDOW_MINUTES = 20
CLV_FINALIZER_GRACE_MINUTES = CLOSE_WINDOW_MINUTES + 10
CLV_IDENTITY_BACKFILL_LOOKBACK_HOURS = 72
CLV_AUDIT_REASON_CODES = (
    "missing_identity",
    "outside_close_window",
    "event_not_returned",
    "market_not_returned",
    "selection_not_returned",
    "line_mismatch",
    "participant_mismatch",
    "promoted_from_latest",
    "latest_not_in_close_window",
    "stale_identity_backfilled",
    "write_failed",
    "db_schema_mismatch",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def is_within_close_window(
    commence_time: str | None,
    *,
    now: datetime | None = None,
    window_minutes: int = CLOSE_WINDOW_MINUTES,
) -> bool:
    commence_dt = _parse_iso_datetime(commence_time)
    if commence_dt is None:
        return False
    current = now or _utc_now()
    if commence_dt <= current:
        return False
    return commence_dt <= current + timedelta(minutes=window_minutes)


def has_valid_close_snapshot(
    commence_time: str | None,
    captured_at: Any,
    *,
    window_minutes: int = CLOSE_WINDOW_MINUTES,
) -> bool:
    commence_dt = _parse_iso_datetime(commence_time)
    captured_dt = _parse_iso_datetime(captured_at)
    if commence_dt is None or captured_dt is None:
        return False
    close_window_start = commence_dt - timedelta(minutes=window_minutes)
    return close_window_start <= captured_dt <= commence_dt


def should_capture_close_snapshot(
    commence_time: str | None,
    *,
    existing_close: Any,
    captured_at: Any,
    now: datetime | None = None,
    window_minutes: int = CLOSE_WINDOW_MINUTES,
    allow_retroactive_close_capture: bool = False,
) -> bool:
    if allow_retroactive_close_capture:
        commence_dt = _parse_iso_datetime(commence_time)
        if commence_dt is None:
            return False
        if existing_close is None:
            return True
        return not has_valid_close_snapshot(commence_time, captured_at, window_minutes=window_minutes)

    current = now or _utc_now()
    if not is_within_close_window(commence_time, now=current, window_minutes=window_minutes):
        return False
    if existing_close is None:
        return True
    return not has_valid_close_snapshot(commence_time, captured_at, window_minutes=window_minutes)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_line_value(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    return _normalize_line_value(value)


def _normalize_participant_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_selection_key_parts(selection_key: Any) -> list[str]:
    return [part.strip().lower() for part in str(selection_key or "").split("|")]


def _parse_straight_selection_key(selection_key: Any) -> dict[str, Any]:
    parts = _parse_selection_key_parts(selection_key)
    event_id = parts[0] if len(parts) > 0 and parts[0] else None
    market_key = parts[1] if len(parts) > 1 and parts[1] else None
    selection_token = parts[2] if len(parts) > 2 and parts[2] else None
    line_value = _normalize_line_value(parts[3]) if len(parts) > 3 else None
    selection_side = None
    if market_key == "totals" and selection_token in {"over", "under"}:
        selection_side = selection_token
    return {
        "event_id": event_id,
        "market_key": market_key,
        "selection_token": selection_token,
        "selection_side": selection_side,
        "line_value": line_value,
    }


def _parse_prop_selection_key(selection_key: Any) -> dict[str, Any]:
    parts = _parse_selection_key_parts(selection_key)
    event_id = parts[0] if len(parts) > 0 and parts[0] else None
    market_key = parts[1] if len(parts) > 1 and parts[1] else None
    player_name = parts[2] if len(parts) > 2 and parts[2] else None
    side_and_line = parts[3] if len(parts) > 3 and parts[3] else ""
    selection_side = side_and_line or None
    line_value = None
    if ":" in side_and_line:
        selection_side, line_token = side_and_line.split(":", 1)
        line_value = _normalize_line_value(line_token)
    return {
        "event_id": event_id,
        "market_key": market_key,
        "player_name": player_name,
        "selection_side": selection_side or None,
        "line_value": line_value,
    }


def _normalize_total_side(value: Any) -> str | None:
    normalized = _normalize_text(value)
    return normalized if normalized in {"over", "under"} else None


def _normalize_straight_selection_side(*, market_key: Any, selection_side: Any, team: Any) -> str | None:
    normalized_market = _normalize_text(market_key) or "h2h"
    if normalized_market == "totals":
        return _normalize_total_side(selection_side) or _normalize_total_side(team)
    normalized_selection = str(selection_side or "").strip()
    if normalized_selection:
        return normalized_selection
    normalized_team = str(team or "").strip()
    return normalized_team or None


def _prop_identity_keys(*, player_name: Any, participant_id: Any) -> list[str]:
    keys: list[str] = []
    normalized_participant_id = _normalize_participant_id(participant_id)
    normalized_player_name = _normalize_text(player_name)
    if normalized_participant_id:
        keys.append(f"id:{normalized_participant_id}")
    if normalized_player_name:
        keys.append(f"name:{normalized_player_name}")
    return keys


def _new_snapshot_update_summary() -> dict[str, Any]:
    return {
        "row_count": 0,
        "matched_count": 0,
        "unmatched_count": 0,
        "latest_updated": 0,
        "close_updated": 0,
        "close_rejected_count": 0,
        "rescue_eligible_count": 0,
        "rescue_from_latest_count": 0,
        "identity_backfilled_count": 0,
        "candidate_surface_counts": {},
        "candidate_market_counts": {},
        "matched_surface_counts": {},
        "matched_market_counts": {},
        "reason_counts": {},
    }


def _bump_counter(counter: dict[str, int], key: Any, amount: int = 1) -> None:
    normalized_key = str(key or "unknown").strip() or "unknown"
    counter[normalized_key] = int(counter.get(normalized_key, 0)) + amount


def _mark_snapshot_reason(summary: dict[str, Any], reason: str) -> None:
    if reason not in CLV_AUDIT_REASON_CODES:
        reason = "write_failed"
    _bump_counter(summary["reason_counts"], reason)


def _normalize_snapshot_summary(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary)
    for key in (
        "candidate_surface_counts",
        "candidate_market_counts",
        "matched_surface_counts",
        "matched_market_counts",
        "reason_counts",
    ):
        bucket = normalized.get(key) or {}
        normalized[key] = {str(name): int(value) for name, value in bucket.items() if int(value) > 0}
    return normalized


def _context_keys(event_id: Any, commence_time: Any) -> list[str]:
    keys: list[str] = []
    raw_event_id = str(event_id or "").strip()
    raw_commence_time = str(commence_time or "").strip()
    if raw_event_id:
        keys.append(f"event:{raw_event_id}")
    if raw_commence_time:
        keys.append(f"time:{raw_commence_time}")
    return keys


def _build_reference_coverage(sides: list[dict[str, Any]]) -> dict[str, Any]:
    coverage: dict[str, Any] = {
        "straight_events": set(),
        "straight_markets": defaultdict(set),
        "straight_lines": defaultdict(set),
        "straight_selections": defaultdict(set),
        "prop_events": set(),
        "prop_markets": defaultdict(set),
        "prop_players": defaultdict(set),
        "prop_lines": defaultdict(set),
        "prop_sides": defaultdict(set),
    }

    for side in sides:
        surface = str(side.get("surface") or "straight_bets").strip().lower()
        contexts = _context_keys(side.get("event_id"), side.get("commence_time"))
        if not contexts:
            continue
        if surface == "player_props":
            market_key = _normalize_text(side.get("market_key"))
            player_name = _normalize_text(side.get("player_name"))
            participant_id = _normalize_participant_id(side.get("participant_id"))
            selection_side = _normalize_text(side.get("selection_side"))
            line_value = _normalize_line_value(side.get("line_value"))
            for context in contexts:
                coverage["prop_events"].add(context)
                if market_key:
                    coverage["prop_markets"][context].add(market_key)
                for identity_key in _prop_identity_keys(player_name=player_name, participant_id=participant_id):
                    if market_key:
                        coverage["prop_players"][(context, market_key)].add(identity_key)
                    if market_key and line_value is not None:
                        coverage["prop_lines"][(context, market_key, identity_key)].add(line_value)
                    if market_key and line_value is not None and selection_side:
                        coverage["prop_sides"][(context, market_key, identity_key, line_value)].add(selection_side)
            continue

        market_key = _normalize_text(side.get("market_key")) or "h2h"
        team = _normalize_text(side.get("team"))
        line_value = _normalize_line_value(side.get("line_value"))
        line_key = line_value if market_key in {"spreads", "totals"} else None
        for context in contexts:
            coverage["straight_events"].add(context)
            coverage["straight_markets"][context].add(market_key)
            if market_key in {"spreads", "totals"} and line_key is not None:
                coverage["straight_lines"][(context, market_key)].add(line_key)
            if team:
                coverage["straight_selections"][(context, market_key, line_key)].add(team)

    return coverage


def _straight_market_label(row: dict[str, Any]) -> str:
    market_key = _normalize_text(row.get("source_market_key"))
    return market_key or "h2h"


def _diagnose_straight_reference_miss(row: dict[str, Any], coverage: dict[str, Any]) -> str:
    team = _normalize_text(row.get("clv_team"))
    contexts = _context_keys(row.get("source_event_id") or row.get("clv_event_id"), row.get("commence_time"))
    market_key = _straight_market_label(row)
    line_value = _normalize_line_value(row.get("line_value"))

    if not team or not contexts:
        return "missing_identity"
    if market_key in {"spreads", "totals"} and line_value is None:
        return "missing_identity"
    if not any(context in coverage["straight_events"] for context in contexts):
        return "event_not_returned"
    if not any(market_key in coverage["straight_markets"].get(context, set()) for context in contexts):
        return "market_not_returned"
    if market_key in {"spreads", "totals"}:
        if not any(line_value in coverage["straight_lines"].get((context, market_key), set()) for context in contexts):
            return "line_mismatch"
        if not any(team in coverage["straight_selections"].get((context, market_key, line_value), set()) for context in contexts):
            return "selection_not_returned"
        return "selection_not_returned"
    if not any(team in coverage["straight_selections"].get((context, market_key, None), set()) for context in contexts):
        return "selection_not_returned"
    return "selection_not_returned"


def _diagnose_prop_reference_miss(row: dict[str, Any], coverage: dict[str, Any], *, market_field: str) -> str:
    player_name = _normalize_text(row.get("participant_name") or row.get("player_name"))
    participant_id = _normalize_participant_id(row.get("participant_id"))
    market_key = _normalize_text(row.get(market_field))
    selection_side = _normalize_text(row.get("selection_side"))
    line_value = _normalize_line_value(row.get("line_value"))
    contexts = _context_keys(row.get("source_event_id") or row.get("event_id") or row.get("clv_event_id"), row.get("commence_time"))

    if (not player_name and not participant_id) or not market_key or not selection_side or line_value is None or not contexts:
        return "missing_identity"
    if not any(context in coverage["prop_events"] for context in contexts):
        return "event_not_returned"
    if not any(market_key in coverage["prop_markets"].get(context, set()) for context in contexts):
        return "market_not_returned"
    identity_keys = _prop_identity_keys(player_name=player_name, participant_id=participant_id)
    if not any(
        any(identity_key in coverage["prop_players"].get((context, market_key), set()) for identity_key in identity_keys)
        for context in contexts
    ):
        return "participant_mismatch"
    if not any(
        any(line_value in coverage["prop_lines"].get((context, market_key, identity_key), set()) for identity_key in identity_keys)
        for context in contexts
    ):
        return "line_mismatch"
    if not any(
        any(
            selection_side in coverage["prop_sides"].get((context, market_key, identity_key, line_value), set())
            for identity_key in identity_keys
        )
        for context in contexts
    ):
        return "selection_not_returned"
    return "selection_not_returned"


def _is_missing_scan_opportunities_column_error(error: Exception, *columns: str) -> bool:
    msg = str(error)
    message = str(getattr(error, "message", "") or "")
    combined = f"{msg} {message}".lower()
    code = str(getattr(error, "code", "") or "").strip().upper()
    if code != "42703" and "scan_opportunities" not in combined:
        return False
    return any(column.strip().lower() in combined for column in columns if column)


def build_reference_snapshots(sides: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    snapshot_by_event: dict[tuple[str, str], float] = {}
    snapshot_by_time: dict[tuple[str, str], float] = {}
    for side in sides:
        if str(side.get("surface") or "straight_bets").strip().lower() != "straight_bets":
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        team = _normalize_text(side.get("team"))
        pinnacle_odds = side.get("pinnacle_odds")
        if pinnacle_odds is None or not team:
            continue
        if commence_time:
            snapshot_by_time[(commence_time, team)] = float(pinnacle_odds)
        if event_id:
            snapshot_by_event[(event_id, team)] = float(pinnacle_odds)
    return snapshot_by_event, snapshot_by_time


def build_reference_pair_snapshots(
    sides: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    snapshot_by_event: dict[str, dict[str, float]] = {}
    snapshot_by_time: dict[str, dict[str, float]] = {}
    for side in sides:
        if str(side.get("surface") or "straight_bets").strip().lower() != "straight_bets":
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        team = _normalize_text(side.get("team"))
        pinnacle_odds = side.get("pinnacle_odds")
        if pinnacle_odds is None or not team:
            continue
        if event_id:
            snapshot_by_event.setdefault(event_id, {})[team] = float(pinnacle_odds)
        if commence_time:
            snapshot_by_time.setdefault(commence_time, {})[team] = float(pinnacle_odds)
    return snapshot_by_event, snapshot_by_time


def _straight_pair_line_key(market_key: Any, line_value: Any) -> tuple[str, float] | None:
    normalized_market = _normalize_text(market_key)
    normalized_line = _normalize_line_value(line_value)
    if normalized_market not in {"spreads", "totals"} or normalized_line is None:
        return None
    if normalized_market == "spreads":
        return (normalized_market, abs(normalized_line))
    return (normalized_market, normalized_line)


def build_straight_exact_reference_snapshots(
    sides: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, float], float], dict[tuple[str, str, str, float], float]]:
    snapshot_by_event: dict[tuple[str, str, str, float], float] = {}
    snapshot_by_time: dict[tuple[str, str, str, float], float] = {}
    for side in sides:
        if str(side.get("surface") or "straight_bets").strip().lower() != "straight_bets":
            continue
        market_key = _normalize_text(side.get("market_key"))
        team = _normalize_text(side.get("team"))
        line_value = _normalize_line_value(side.get("line_value"))
        pinnacle_odds = side.get("pinnacle_odds")
        if market_key not in {"spreads", "totals"} or not team or line_value is None or pinnacle_odds is None:
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        if event_id:
            snapshot_by_event[(event_id, team, market_key, line_value)] = float(pinnacle_odds)
        if commence_time:
            snapshot_by_time[(commence_time, team, market_key, line_value)] = float(pinnacle_odds)
    return snapshot_by_event, snapshot_by_time


def build_straight_exact_pair_snapshots(
    sides: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, float], dict[str, float]], dict[tuple[str, str, float], dict[str, float]]]:
    snapshot_by_event: dict[tuple[str, str, float], dict[str, float]] = {}
    snapshot_by_time: dict[tuple[str, str, float], dict[str, float]] = {}
    for side in sides:
        if str(side.get("surface") or "straight_bets").strip().lower() != "straight_bets":
            continue
        team = _normalize_text(side.get("team"))
        pair_key = _straight_pair_line_key(side.get("market_key"), side.get("line_value"))
        pinnacle_odds = side.get("pinnacle_odds")
        if not team or pair_key is None or pinnacle_odds is None:
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        if event_id:
            snapshot_by_event.setdefault((event_id, pair_key[0], pair_key[1]), {})[team] = float(pinnacle_odds)
        if commence_time:
            snapshot_by_time.setdefault((commence_time, pair_key[0], pair_key[1]), {})[team] = float(pinnacle_odds)
    return snapshot_by_event, snapshot_by_time


def build_prop_reference_snapshots(
    sides: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, str, float], float], dict[tuple[str, str, str, str, float], float]]:
    snapshot_by_event: dict[tuple[str, str, str, str, float], float] = {}
    snapshot_by_time: dict[tuple[str, str, str, str, float], float] = {}
    for side in sides:
        if str(side.get("surface") or "").strip().lower() != "player_props":
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        participant_keys = _prop_identity_keys(
            player_name=side.get("player_name"),
            participant_id=side.get("participant_id"),
        )
        market_key = _normalize_text(side.get("market_key"))
        selection_side = _normalize_text(side.get("selection_side"))
        line_value = _normalize_line_value(side.get("line_value"))
        reference_odds = side.get("reference_odds")
        if reference_odds is None or not participant_keys or not market_key or not selection_side or line_value is None:
            continue
        for participant_key in participant_keys:
            if commence_time:
                snapshot_by_time[(commence_time, participant_key, market_key, selection_side, line_value)] = float(reference_odds)
            if event_id:
                snapshot_by_event[(event_id, participant_key, market_key, selection_side, line_value)] = float(reference_odds)
    return snapshot_by_event, snapshot_by_time


def build_prop_reference_pair_snapshots(
    sides: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, float], dict[str, float]], dict[tuple[str, str, str, float], dict[str, float]]]:
    snapshot_by_event: dict[tuple[str, str, str, float], dict[str, float]] = {}
    snapshot_by_time: dict[tuple[str, str, str, float], dict[str, float]] = {}
    for side in sides:
        if str(side.get("surface") or "").strip().lower() != "player_props":
            continue
        participant_keys = _prop_identity_keys(
            player_name=side.get("player_name"),
            participant_id=side.get("participant_id"),
        )
        market_key = _normalize_text(side.get("market_key"))
        selection_side = _normalize_text(side.get("selection_side"))
        line_value = _normalize_line_value(side.get("line_value"))
        reference_odds = side.get("reference_odds")
        if reference_odds is None or not participant_keys or not market_key or not selection_side or line_value is None:
            continue
        event_id = str(side.get("event_id") or "").strip()
        commence_time = str(side.get("commence_time") or "")
        for participant_key in participant_keys:
            if event_id:
                snapshot_by_event.setdefault((event_id, participant_key, market_key, line_value), {})[selection_side] = float(reference_odds)
            if commence_time:
                snapshot_by_time.setdefault((commence_time, participant_key, market_key, line_value), {})[selection_side] = float(reference_odds)
    return snapshot_by_event, snapshot_by_time


def lookup_reference_odds(
    *,
    team: str | None,
    commence_time: str | None,
    event_id: str | None,
    snapshot_by_event: dict[tuple[str, str], float],
    snapshot_by_time: dict[tuple[str, str], float],
) -> float | None:
    normalized_team = _normalize_text(team)
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    if normalized_event_id and normalized_team:
        match = snapshot_by_event.get((normalized_event_id, normalized_team))
        if match is not None:
            return match
    if normalized_commence and normalized_team:
        return snapshot_by_time.get((normalized_commence, normalized_team))
    return None


def lookup_opposing_reference_odds(
    *,
    team: str | None,
    commence_time: str | None,
    event_id: str | None,
    pair_snapshot_by_event: dict[str, dict[str, float]],
    pair_snapshot_by_time: dict[str, dict[str, float]],
) -> float | None:
    normalized_team = _normalize_text(team)
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    market = pair_snapshot_by_event.get(normalized_event_id) if normalized_event_id else None
    if not market and normalized_commence:
        market = pair_snapshot_by_time.get(normalized_commence)
    if not isinstance(market, dict) or len(market) < 2:
        return None
    for candidate_team, candidate_odds in market.items():
        if candidate_team != normalized_team:
            return float(candidate_odds)
    return None


def lookup_straight_exact_reference_odds(
    *,
    team: str | None,
    source_market_key: str | None,
    line_value: float | None,
    commence_time: str | None,
    event_id: str | None,
    snapshot_by_event: dict[tuple[str, str, str, float], float],
    snapshot_by_time: dict[tuple[str, str, str, float], float],
) -> float | None:
    normalized_team = _normalize_text(team)
    normalized_market = _normalize_text(source_market_key)
    normalized_line = _normalize_line_value(line_value)
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    if normalized_market not in {"spreads", "totals"} or not normalized_team or normalized_line is None:
        return None
    if normalized_event_id:
        match = snapshot_by_event.get((normalized_event_id, normalized_team, normalized_market, normalized_line))
        if match is not None:
            return match
    if normalized_commence:
        return snapshot_by_time.get((normalized_commence, normalized_team, normalized_market, normalized_line))
    return None


def lookup_straight_exact_opposing_reference_odds(
    *,
    team: str | None,
    source_market_key: str | None,
    line_value: float | None,
    commence_time: str | None,
    event_id: str | None,
    pair_snapshot_by_event: dict[tuple[str, str, float], dict[str, float]],
    pair_snapshot_by_time: dict[tuple[str, str, float], dict[str, float]],
) -> float | None:
    normalized_team = _normalize_text(team)
    pair_key = _straight_pair_line_key(source_market_key, line_value)
    if not normalized_team or pair_key is None:
        return None
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    pair = pair_snapshot_by_event.get((normalized_event_id, pair_key[0], pair_key[1])) if normalized_event_id else None
    if not pair and normalized_commence:
        pair = pair_snapshot_by_time.get((normalized_commence, pair_key[0], pair_key[1]))
    if not isinstance(pair, dict):
        return None
    for candidate_team, candidate_odds in pair.items():
        if candidate_team != normalized_team:
            return float(candidate_odds)
    return None


def lookup_prop_reference_odds(
    *,
    player_name: str | None,
    participant_id: str | None = None,
    source_market_key: str | None,
    selection_side: str | None,
    line_value: float | None,
    commence_time: str | None,
    event_id: str | None,
    snapshot_by_event: dict[tuple[str, str, str, str, float], float],
    snapshot_by_time: dict[tuple[str, str, str, str, float], float],
) -> float | None:
    participant_keys = _prop_identity_keys(player_name=player_name, participant_id=participant_id)
    normalized_market = _normalize_text(source_market_key)
    normalized_side = _normalize_text(selection_side)
    normalized_line = _normalize_line_value(line_value)
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    if not participant_keys or not normalized_market or not normalized_side or normalized_line is None:
        return None
    if normalized_event_id:
        for participant_key in participant_keys:
            match = snapshot_by_event.get(
                (normalized_event_id, participant_key, normalized_market, normalized_side, normalized_line)
            )
            if match is not None:
                return match
    if normalized_commence:
        for participant_key in participant_keys:
            match = snapshot_by_time.get(
                (normalized_commence, participant_key, normalized_market, normalized_side, normalized_line)
            )
            if match is not None:
                return match
    return None


def lookup_prop_opposing_reference_odds(
    *,
    player_name: str | None,
    participant_id: str | None = None,
    source_market_key: str | None,
    selection_side: str | None,
    line_value: float | None,
    commence_time: str | None,
    event_id: str | None,
    pair_snapshot_by_event: dict[tuple[str, str, str, float], dict[str, float]],
    pair_snapshot_by_time: dict[tuple[str, str, str, float], dict[str, float]],
) -> float | None:
    participant_keys = _prop_identity_keys(player_name=player_name, participant_id=participant_id)
    normalized_market = _normalize_text(source_market_key)
    normalized_side = _normalize_text(selection_side)
    normalized_line = _normalize_line_value(line_value)
    if not participant_keys or not normalized_market or not normalized_side or normalized_line is None:
        return None
    normalized_event_id = str(event_id or "").strip()
    normalized_commence = str(commence_time or "")
    opposing_side = "under" if normalized_side == "over" else "over"
    for participant_key in participant_keys:
        pair = (
            pair_snapshot_by_event.get((normalized_event_id, participant_key, normalized_market, normalized_line))
            if normalized_event_id
            else None
        )
        if not pair and normalized_commence:
            pair = pair_snapshot_by_time.get((normalized_commence, participant_key, normalized_market, normalized_line))
        if not isinstance(pair, dict):
            continue
        opposing_odds = pair.get(opposing_side)
        if opposing_odds is not None:
            return float(opposing_odds)
    return None


def _is_missing_value(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _parse_prop_opportunity_key(opportunity_key: Any) -> dict[str, Any]:
    parts = _parse_selection_key_parts(opportunity_key)
    if len(parts) < 8 or parts[0] != "player_props":
        return {}
    event_ref = parts[2]
    event_id = event_ref[3:] if event_ref.startswith("id:") else None
    return {
        "event_id": event_id or None,
        "market_key": parts[3] or None,
        "player_name": parts[4] or None,
        "selection_side": parts[5] or None,
        "line_value": _normalize_line_value(parts[6]),
    }


def _parse_pickem_identity_keys(*, observation_key: Any, comparison_key: Any) -> dict[str, Any]:
    comparison_parts = _parse_selection_key_parts(comparison_key)
    observation_parts = _parse_selection_key_parts(observation_key)
    selection_side = observation_parts[-1] if observation_parts else None
    event_id = comparison_parts[0] if len(comparison_parts) > 0 and comparison_parts[0] else None
    market_key = comparison_parts[1] if len(comparison_parts) > 1 and comparison_parts[1] else None
    player_name = comparison_parts[2] if len(comparison_parts) > 2 and comparison_parts[2] else None
    line_value = _normalize_line_value(comparison_parts[3]) if len(comparison_parts) > 3 else None
    return {
        "event_id": event_id,
        "market_key": market_key,
        "player_name": player_name,
        "selection_side": selection_side,
        "line_value": line_value,
    }


def _repair_bet_identity_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    repaired = dict(row)
    payload: dict[str, Any] = {}
    meta = _coerce_selection_meta_dict(row.get("selection_meta")) or {}
    surface = str(row.get("surface") or "straight_bets").strip().lower()
    selection_key = row.get("source_selection_key")
    if surface == "player_props":
        parsed = _parse_prop_selection_key(selection_key)
        if _is_missing_value(repaired.get("source_event_id")):
            value = parsed.get("event_id") or row.get("clv_event_id")
            if value:
                repaired["source_event_id"] = value
                payload["source_event_id"] = value
        if _is_missing_value(repaired.get("source_market_key")):
            value = parsed.get("market_key")
            if value:
                repaired["source_market_key"] = value
                payload["source_market_key"] = value
        if _is_missing_value(repaired.get("selection_side")):
            value = parsed.get("selection_side")
            if value:
                repaired["selection_side"] = value
                payload["selection_side"] = value
        if _normalize_line_value(repaired.get("line_value")) is None:
            value = parsed.get("line_value")
            if value is not None:
                repaired["line_value"] = value
                payload["line_value"] = value
        if _is_missing_value(repaired.get("participant_id")):
            value = meta.get("participant_id") or meta.get("participantId")
            if value:
                repaired["participant_id"] = value
                payload["participant_id"] = value
        if _is_missing_value(repaired.get("participant_name")) and parsed.get("player_name"):
            repaired["participant_name"] = parsed.get("player_name")
        return repaired, payload

    parsed = _parse_straight_selection_key(selection_key)
    inferred_market = (
        str(repaired.get("source_market_key") or "").strip().lower()
        or str(meta.get("marketKey") or meta.get("market_key") or "").strip().lower()
        or str(parsed.get("market_key") or "").strip().lower()
    )
    if not inferred_market and repaired.get("clv_team") and _normalize_line_value(repaired.get("line_value")) is None:
        inferred_market = "h2h"
    if _is_missing_value(repaired.get("source_event_id")):
        value = parsed.get("event_id") or row.get("clv_event_id")
        if value:
            repaired["source_event_id"] = value
            payload["source_event_id"] = value
    if _is_missing_value(repaired.get("source_market_key")) and inferred_market:
        repaired["source_market_key"] = inferred_market
        payload["source_market_key"] = inferred_market
    normalized_line = _normalize_line_value(repaired.get("line_value"))
    if normalized_line is None:
        value = parsed.get("line_value")
        if value is not None:
            repaired["line_value"] = value
            payload["line_value"] = value
    if _is_missing_value(repaired.get("selection_side")):
        value = _normalize_straight_selection_side(
            market_key=inferred_market or parsed.get("market_key"),
            selection_side=parsed.get("selection_side"),
            team=repaired.get("clv_team"),
        )
        if value:
            repaired["selection_side"] = value
            payload["selection_side"] = value
    if _is_missing_value(repaired.get("clv_team")) and inferred_market == "totals":
        value = _normalize_total_side(repaired.get("selection_side"))
        if value:
            repaired["clv_team"] = value
            payload["clv_team"] = value
    return repaired, payload


def _repair_scan_opportunity_identity_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    repaired = dict(row)
    payload: dict[str, Any] = {}
    surface = str(row.get("surface") or "straight_bets").strip().lower()
    if surface == "player_props":
        parsed = _parse_prop_opportunity_key(row.get("opportunity_key"))
        if _is_missing_value(repaired.get("event_id")) and parsed.get("event_id"):
            repaired["event_id"] = parsed["event_id"]
            payload["event_id"] = parsed["event_id"]
        if _is_missing_value(repaired.get("source_market_key")) and parsed.get("market_key"):
            repaired["source_market_key"] = parsed["market_key"]
            payload["source_market_key"] = parsed["market_key"]
        if _is_missing_value(repaired.get("selection_side")) and parsed.get("selection_side"):
            repaired["selection_side"] = parsed["selection_side"]
            payload["selection_side"] = parsed["selection_side"]
        if _normalize_line_value(repaired.get("line_value")) is None and parsed.get("line_value") is not None:
            repaired["line_value"] = parsed["line_value"]
            payload["line_value"] = parsed["line_value"]
        if _is_missing_value(repaired.get("player_name")) and parsed.get("player_name"):
            repaired["player_name"] = parsed["player_name"]
        return repaired, payload

    inferred_market = str(repaired.get("source_market_key") or "").strip().lower()
    if not inferred_market and repaired.get("team") and _normalize_line_value(repaired.get("line_value")) is None:
        inferred_market = "h2h"
    if _is_missing_value(repaired.get("source_market_key")) and inferred_market:
        repaired["source_market_key"] = inferred_market
        payload["source_market_key"] = inferred_market
    if _is_missing_value(repaired.get("selection_side")):
        value = _normalize_straight_selection_side(
            market_key=inferred_market,
            selection_side=repaired.get("selection_side"),
            team=repaired.get("team"),
        )
        if value:
            repaired["selection_side"] = value
            payload["selection_side"] = value
    return repaired, payload


def _repair_pickem_identity_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    repaired = dict(row)
    payload: dict[str, Any] = {}
    parsed = _parse_pickem_identity_keys(
        observation_key=row.get("observation_key"),
        comparison_key=row.get("comparison_key"),
    )
    if _is_missing_value(repaired.get("event_id")) and parsed.get("event_id"):
        repaired["event_id"] = parsed["event_id"]
        payload["event_id"] = parsed["event_id"]
    if _is_missing_value(repaired.get("market_key")) and parsed.get("market_key"):
        repaired["market_key"] = parsed["market_key"]
        payload["market_key"] = parsed["market_key"]
    if _is_missing_value(repaired.get("selection_side")) and parsed.get("selection_side"):
        repaired["selection_side"] = parsed["selection_side"]
        payload["selection_side"] = parsed["selection_side"]
    if _normalize_line_value(repaired.get("line_value")) is None and parsed.get("line_value") is not None:
        repaired["line_value"] = parsed["line_value"]
        payload["line_value"] = parsed["line_value"]
    if _is_missing_value(repaired.get("player_name")) and parsed.get("player_name"):
        repaired["player_name"] = parsed["player_name"]
    return repaired, payload


def _backfill_table_rows(
    db,
    *,
    table_name: str,
    timestamp_field: str,
    row_repairer,
    select_fields: str,
    now: datetime,
    lookback_hours: int,
) -> dict[str, Any]:
    summary = {
        "updated": 0,
        "by_surface": {},
        "by_market": {},
        "fields_updated": {},
    }
    cutoff = now - timedelta(hours=max(1, int(lookback_hours)))
    result = db.table(table_name).select(select_fields).execute()
    for row in result.data or []:
        row_ts = _parse_iso_datetime(row.get(timestamp_field))
        if row_ts is None or row_ts < cutoff:
            continue
        repaired_row, payload = row_repairer(row)
        if not payload:
            continue
        db.table(table_name).update(payload).eq("id", row["id"]).execute()
        summary["updated"] += 1
        _bump_counter(summary["by_surface"], repaired_row.get("surface") or "straight_bets")
        market_key = repaired_row.get("source_market_key") or repaired_row.get("market_key") or "h2h"
        _bump_counter(summary["by_market"], market_key)
        for field_name in payload:
            _bump_counter(summary["fields_updated"], field_name)
    return summary


def repair_recent_clv_tracking_identity(
    db,
    *,
    now: datetime | None = None,
    lookback_hours: int = CLV_IDENTITY_BACKFILL_LOOKBACK_HOURS,
) -> dict[str, Any]:
    current = now or _utc_now()
    bets = _backfill_table_rows(
        db,
        table_name="bets",
        timestamp_field="created_at",
        row_repairer=_repair_bet_identity_row,
        select_fields=(
            "id,created_at,surface,clv_event_id,source_event_id,source_market_key,source_selection_key,"
            "selection_side,line_value,participant_name,participant_id,clv_team,selection_meta"
        ),
        now=current,
        lookback_hours=lookback_hours,
    )
    try:
        research = _backfill_table_rows(
            db,
            table_name="scan_opportunities",
            timestamp_field="first_seen_at",
            row_repairer=_repair_scan_opportunity_identity_row,
            select_fields=(
                "id,first_seen_at,surface,team,event_id,player_name,opportunity_key,source_market_key,"
                "selection_side,line_value"
            ),
            now=current,
            lookback_hours=lookback_hours,
        )
    except Exception as exc:
        from services.research_opportunities import is_missing_scan_opportunities_error

        if is_missing_scan_opportunities_error(exc):
            research = {"updated": 0, "by_surface": {}, "by_market": {}, "fields_updated": {}}
        else:
            raise
    try:
        pickem = _backfill_table_rows(
            db,
            table_name="pickem_research_observations",
            timestamp_field="created_at",
            row_repairer=_repair_pickem_identity_row,
            select_fields=(
                "id,created_at,surface,observation_key,comparison_key,event_id,market_key,player_name,"
                "selection_side,line_value"
            ),
            now=current,
            lookback_hours=lookback_hours,
        )
    except Exception as exc:
        from services.pickem_research import is_missing_pickem_research_observations_error

        if is_missing_pickem_research_observations_error(exc):
            pickem = {"updated": 0, "by_surface": {}, "by_market": {}, "fields_updated": {}}
        else:
            raise

    return {
        "lookback_hours": max(1, int(lookback_hours)),
        "updated": int(bets["updated"]) + int(research["updated"]) + int(pickem["updated"]),
        "bets": bets,
        "research": research,
        "pickem": pickem,
    }


def _coerce_selection_meta_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        return copy.deepcopy(parsed) if isinstance(parsed, dict) else None
    return None


def _parlay_leg_sport_key(leg: dict[str, Any]) -> str:
    return str(leg.get("sport") or "").strip()


def _parlay_meta_has_leg_in_sports(meta: dict[str, Any], sports_set: set[str]) -> bool:
    legs = meta.get("legs")
    if not isinstance(legs, list):
        return False
    for leg in legs:
        if isinstance(leg, dict) and _parlay_leg_sport_key(leg) in sports_set:
            return True
    return False


def lookup_parlay_leg_reference_odds(
    leg: dict[str, Any],
    *,
    straight_snapshot_by_event: dict[tuple[str, str], float],
    straight_snapshot_by_time: dict[tuple[str, str], float],
    straight_exact_snapshot_by_event: dict[tuple[str, str, str, float], float],
    straight_exact_snapshot_by_time: dict[tuple[str, str, str, float], float],
    prop_snapshot_by_event: dict[tuple[str, str, str, str, float], float],
    prop_snapshot_by_time: dict[tuple[str, str, str, str, float], float],
) -> float | None:
    surface = str(leg.get("surface") or "straight_bets").strip().lower()
    commence = str(leg.get("commenceTime") or leg.get("commence_time") or "").strip()
    event_id = str(
        leg.get("sourceEventId")
        or leg.get("source_event_id")
        or leg.get("eventId")
        or leg.get("event_id")
        or ""
    ).strip()
    if surface == "player_props":
        return lookup_prop_reference_odds(
            player_name=leg.get("participantName") or leg.get("participant_name"),
            participant_id=leg.get("participantId") or leg.get("participant_id"),
            source_market_key=leg.get("sourceMarketKey") or leg.get("source_market_key"),
            selection_side=leg.get("selectionSide") or leg.get("selection_side"),
            line_value=_normalize_line_value(
                leg.get("lineValue") if leg.get("lineValue") is not None else leg.get("line_value")
            ),
            commence_time=commence or None,
            event_id=event_id or None,
            snapshot_by_event=prop_snapshot_by_event,
            snapshot_by_time=prop_snapshot_by_time,
        )
    source_market_key = leg.get("sourceMarketKey") or leg.get("source_market_key")
    line_value = _normalize_line_value(
        leg.get("lineValue") if leg.get("lineValue") is not None else leg.get("line_value")
    )
    team = leg.get("team")
    if not team:
        return None
    if _normalize_text(source_market_key) in {"spreads", "totals"} and line_value is not None:
        match = lookup_straight_exact_reference_odds(
            team=team,
            source_market_key=source_market_key,
            line_value=line_value,
            commence_time=commence or None,
            event_id=event_id or None,
            snapshot_by_event=straight_exact_snapshot_by_event,
            snapshot_by_time=straight_exact_snapshot_by_time,
        )
        if match is not None:
            return match
    return lookup_reference_odds(
        team=team,
        commence_time=commence or None,
        event_id=event_id or None,
        snapshot_by_event=straight_snapshot_by_event,
        snapshot_by_time=straight_snapshot_by_time,
    )


def _update_parlay_bet_leg_snapshots(
    db,
    *,
    sports_set: set[str],
    straight_snapshot_by_event: dict[tuple[str, str], float],
    straight_snapshot_by_time: dict[tuple[str, str], float],
    straight_exact_snapshot_by_event: dict[tuple[str, str, str, float], float],
    straight_exact_snapshot_by_time: dict[tuple[str, str, str, float], float],
    prop_snapshot_by_event: dict[tuple[str, str, str, str, float], float],
    prop_snapshot_by_time: dict[tuple[str, str, str, str, float], float],
    allow_close: bool,
    current: datetime,
    updated_at: str,
    allow_retroactive_close_capture: bool = False,
) -> tuple[int, int]:
    """Merge per-leg reference / close CLV into bets.selection_meta.legs (parlay rows only)."""
    if not sports_set:
        return (0, 0)

    parlay_result = (
        db.table("bets")
        .select("id,result,surface,selection_meta")
        .eq("result", "pending")
        .eq("surface", "parlay")
        .execute()
    )

    latest_updated = 0
    close_updated = 0

    for row in parlay_result.data or []:
        meta = _coerce_selection_meta_dict(row.get("selection_meta"))
        if meta is None or str(meta.get("type") or "").strip().lower() != "parlay":
            continue
        if not _parlay_meta_has_leg_in_sports(meta, sports_set):
            continue
        legs = meta.get("legs")
        if not isinstance(legs, list):
            continue

        new_legs: list[Any] = []
        row_touched = False

        for leg in legs:
            if not isinstance(leg, dict):
                new_legs.append(leg)
                continue
            if _parlay_leg_sport_key(leg) not in sports_set:
                new_legs.append(leg)
                continue

            leg_out = dict(leg)
            reference_odds = lookup_parlay_leg_reference_odds(
                leg_out,
                straight_snapshot_by_event=straight_snapshot_by_event,
                straight_snapshot_by_time=straight_snapshot_by_time,
                straight_exact_snapshot_by_event=straight_exact_snapshot_by_event,
                straight_exact_snapshot_by_time=straight_exact_snapshot_by_time,
                prop_snapshot_by_event=prop_snapshot_by_event,
                prop_snapshot_by_time=prop_snapshot_by_time,
            )
            if reference_odds is None:
                new_legs.append(leg_out)
                continue

            row_touched = True
            leg_out["latest_reference_odds"] = reference_odds
            leg_out["latest_reference_updated_at"] = updated_at

            book_raw = (
                leg_out.get("oddsAmerican")
                if leg_out.get("oddsAmerican") is not None
                else leg_out.get("odds_american")
            )
            try:
                book_am = float(book_raw) if book_raw is not None else None
            except (TypeError, ValueError):
                book_am = None

            leg_commence = str(leg_out.get("commenceTime") or leg_out.get("commence_time") or "").strip() or None

            if allow_close and book_am is not None and should_capture_close_snapshot(
                leg_commence,
                existing_close=leg_out.get("pinnacle_odds_at_close"),
                captured_at=leg_out.get("reference_updated_at"),
                now=current,
                allow_retroactive_close_capture=allow_retroactive_close_capture,
            ):
                clv_result = calculate_clv(book_am, float(reference_odds))
                leg_out["pinnacle_odds_at_close"] = reference_odds
                leg_out["reference_updated_at"] = updated_at
                leg_out["clv_ev_percent"] = clv_result["clv_ev_percent"]
                leg_out["beat_close"] = clv_result["beat_close"]
                close_updated += 1

            new_legs.append(leg_out)

        if row_touched:
            meta["legs"] = new_legs
            latest_updated += 1
            db.table("bets").update({"selection_meta": meta}).eq("id", row["id"]).execute()

    return latest_updated, close_updated


def _is_within_finalizer_grace_window(
    commence_time: Any,
    *,
    now: datetime,
    grace_minutes: int = CLV_FINALIZER_GRACE_MINUTES,
) -> bool:
    commence_dt = _parse_iso_datetime(commence_time)
    if commence_dt is None:
        return False
    return (now - timedelta(minutes=grace_minutes)) <= commence_dt <= now


def _apply_finalizer_candidate_counts(summary: dict[str, Any], *, surface: str, market_label: str) -> None:
    summary["row_count"] += 1
    _bump_counter(summary["candidate_surface_counts"], surface)
    _bump_counter(summary["candidate_market_counts"], market_label)


def _mark_identity_backfill(summary: dict[str, Any], repair_payload: dict[str, Any]) -> None:
    if not repair_payload:
        return
    summary["identity_backfilled_count"] += 1
    _mark_snapshot_reason(summary, "stale_identity_backfilled")


def finalize_tracked_clv_closes_from_latest(
    db,
    *,
    now: datetime | None = None,
    grace_minutes: int = CLV_FINALIZER_GRACE_MINUTES,
) -> dict[str, Any]:
    current = now or _utc_now()
    updated_summary = {
        "bet_updates": _new_snapshot_update_summary(),
        "research_updates": _new_snapshot_update_summary(),
        "pickem_updates": _new_snapshot_update_summary(),
    }

    bet_result = (
        db.table("bets")
        .select(
            "id,result,surface,commence_time,created_at,clv_sport_key,clv_event_id,source_event_id,clv_team,"
            "participant_name,participant_id,source_market_key,source_selection_key,selection_side,line_value,"
            "odds_american,latest_pinnacle_odds,latest_pinnacle_updated_at,pinnacle_odds_at_close,clv_updated_at,selection_meta"
        )
        .eq("result", "pending")
        .execute()
    )
    for row in bet_result.data or []:
        repaired_row, repair_payload = _repair_bet_identity_row(row)
        surface = str(repaired_row.get("surface") or "straight_bets").strip().lower()
        market_label = (
            _normalize_text(repaired_row.get("source_market_key")) if surface == "player_props" else _straight_market_label(repaired_row)
        ) or ("player_props" if surface == "player_props" else "h2h")
        if not _is_within_finalizer_grace_window(repaired_row.get("commence_time"), now=current, grace_minutes=grace_minutes):
            continue
        _apply_finalizer_candidate_counts(updated_summary["bet_updates"], surface=surface, market_label=market_label)
        _mark_identity_backfill(updated_summary["bet_updates"], repair_payload)
        if repair_payload:
            db.table("bets").update(repair_payload).eq("id", row["id"]).execute()
        if has_valid_close_snapshot(repaired_row.get("commence_time"), repaired_row.get("clv_updated_at")):
            continue
        latest_reference = _coerce_float(repaired_row.get("latest_pinnacle_odds"))
        latest_updated_at = repaired_row.get("latest_pinnacle_updated_at")
        if latest_reference is None or _parse_iso_datetime(latest_updated_at) is None:
            continue
        if has_valid_close_snapshot(repaired_row.get("commence_time"), latest_updated_at):
            payload = {
                "pinnacle_odds_at_close": latest_reference,
                "clv_updated_at": latest_updated_at,
            }
            db.table("bets").update(payload).eq("id", row["id"]).execute()
            updated_summary["bet_updates"]["matched_count"] += 1
            updated_summary["bet_updates"]["close_updated"] += 1
            updated_summary["bet_updates"]["rescue_eligible_count"] += 1
            updated_summary["bet_updates"]["rescue_from_latest_count"] += 1
            _bump_counter(updated_summary["bet_updates"]["matched_surface_counts"], surface)
            _bump_counter(updated_summary["bet_updates"]["matched_market_counts"], market_label)
            _mark_snapshot_reason(updated_summary["bet_updates"], "promoted_from_latest")
        else:
            updated_summary["bet_updates"]["close_rejected_count"] += 1
            _mark_snapshot_reason(updated_summary["bet_updates"], "latest_not_in_close_window")

    try:
        research_result = (
            db.table("scan_opportunities")
            .select(
                "id,opportunity_key,surface,sport,team,commence_time,event_id,player_name,source_market_key,selection_side,line_value,"
                "first_book_odds,latest_reference_odds,latest_reference_updated_at,reference_odds_at_close,close_captured_at"
            )
            .execute()
        )
        research_rows = list(research_result.data or [])
    except Exception as exc:
        from services.research_opportunities import is_missing_scan_opportunities_error

        if is_missing_scan_opportunities_error(exc):
            research_rows = []
        else:
            raise

    for row in research_rows:
        repaired_row, repair_payload = _repair_scan_opportunity_identity_row(row)
        surface = str(repaired_row.get("surface") or "straight_bets").strip().lower()
        market_label = (
            _normalize_text(repaired_row.get("source_market_key")) if surface == "player_props" else _straight_market_label(repaired_row)
        ) or ("player_props" if surface == "player_props" else "h2h")
        if not _is_within_finalizer_grace_window(repaired_row.get("commence_time"), now=current, grace_minutes=grace_minutes):
            continue
        _apply_finalizer_candidate_counts(updated_summary["research_updates"], surface=surface, market_label=market_label)
        _mark_identity_backfill(updated_summary["research_updates"], repair_payload)
        if repair_payload:
            db.table("scan_opportunities").update(repair_payload).eq("id", row["id"]).execute()
        if has_valid_close_snapshot(repaired_row.get("commence_time"), repaired_row.get("close_captured_at")):
            continue
        latest_reference = _coerce_float(repaired_row.get("latest_reference_odds"))
        latest_updated_at = repaired_row.get("latest_reference_updated_at")
        if latest_reference is None or _parse_iso_datetime(latest_updated_at) is None:
            continue
        if has_valid_close_snapshot(repaired_row.get("commence_time"), latest_updated_at):
            first_book_odds = _coerce_float(repaired_row.get("first_book_odds"))
            if first_book_odds is None:
                continue
            clv_result = calculate_clv(first_book_odds, latest_reference)
            payload = {
                "reference_odds_at_close": latest_reference,
                "close_captured_at": latest_updated_at,
                "clv_ev_percent": clv_result["clv_ev_percent"],
                "beat_close": clv_result["beat_close"],
                "close_true_prob": clv_result.get("close_true_prob"),
                "close_quality": clv_result.get("close_quality"),
                "close_opposing_reference_odds": None,
            }
            try:
                db.table("scan_opportunities").update(payload).eq("id", row["id"]).execute()
            except Exception as exc:
                if _is_missing_scan_opportunities_column_error(
                    exc,
                    "close_true_prob",
                    "close_quality",
                    "close_opposing_reference_odds",
                ):
                    legacy_payload = dict(payload)
                    legacy_payload.pop("close_true_prob", None)
                    legacy_payload.pop("close_quality", None)
                    legacy_payload.pop("close_opposing_reference_odds", None)
                    db.table("scan_opportunities").update(legacy_payload).eq("id", row["id"]).execute()
                    _mark_snapshot_reason(updated_summary["research_updates"], "db_schema_mismatch")
                else:
                    _mark_snapshot_reason(updated_summary["research_updates"], "write_failed")
                    raise
            if repaired_row.get("opportunity_key"):
                update_scan_opportunity_model_evaluations_close_snapshot(
                    db,
                    opportunity_key=str(repaired_row.get("opportunity_key")),
                    close_reference_odds=float(latest_reference),
                    close_opposing_reference_odds=None,
                    close_captured_at=str(latest_updated_at),
                )
            updated_summary["research_updates"]["matched_count"] += 1
            updated_summary["research_updates"]["close_updated"] += 1
            updated_summary["research_updates"]["rescue_eligible_count"] += 1
            updated_summary["research_updates"]["rescue_from_latest_count"] += 1
            _bump_counter(updated_summary["research_updates"]["matched_surface_counts"], surface)
            _bump_counter(updated_summary["research_updates"]["matched_market_counts"], market_label)
            _mark_snapshot_reason(updated_summary["research_updates"], "promoted_from_latest")
        else:
            updated_summary["research_updates"]["close_rejected_count"] += 1
            _mark_snapshot_reason(updated_summary["research_updates"], "latest_not_in_close_window")

    try:
        pickem_result = (
            db.table("pickem_research_observations")
            .select(
                "id,surface,created_at,observation_key,comparison_key,sport,commence_time,event_id,player_name,market_key,selection_side,"
                "line_value,first_fair_odds_american,last_fair_odds_american,latest_reference_odds,latest_reference_updated_at,"
                "close_reference_odds,close_captured_at"
            )
            .execute()
        )
        pickem_rows = list(pickem_result.data or [])
    except Exception as exc:
        from services.pickem_research import is_missing_pickem_research_observations_error

        if is_missing_pickem_research_observations_error(exc):
            pickem_rows = []
        else:
            raise

    for row in pickem_rows:
        repaired_row, repair_payload = _repair_pickem_identity_row(row)
        surface = "player_props"
        market_label = _normalize_text(repaired_row.get("market_key")) or "player_props"
        if not _is_within_finalizer_grace_window(repaired_row.get("commence_time"), now=current, grace_minutes=grace_minutes):
            continue
        _apply_finalizer_candidate_counts(updated_summary["pickem_updates"], surface=surface, market_label=market_label)
        _mark_identity_backfill(updated_summary["pickem_updates"], repair_payload)
        if repair_payload:
            db.table("pickem_research_observations").update(repair_payload).eq("id", row["id"]).execute()
        if has_valid_close_snapshot(repaired_row.get("commence_time"), repaired_row.get("close_captured_at")):
            continue
        latest_reference = _coerce_float(repaired_row.get("latest_reference_odds"))
        latest_updated_at = repaired_row.get("latest_reference_updated_at")
        if latest_reference is None or _parse_iso_datetime(latest_updated_at) is None:
            continue
        if has_valid_close_snapshot(repaired_row.get("commence_time"), latest_updated_at):
            fair_odds = _coerce_float(repaired_row.get("first_fair_odds_american")) or _coerce_float(
                repaired_row.get("last_fair_odds_american")
            )
            close_eval = calculate_clv(
                float(fair_odds if fair_odds is not None else latest_reference),
                float(latest_reference),
            )
            payload = {
                "close_reference_odds": latest_reference,
                "close_opposing_reference_odds": None,
                "close_true_prob": close_eval.get("close_true_prob"),
                "close_quality": close_eval.get("close_quality"),
                "close_captured_at": latest_updated_at,
                "close_edge_pct": close_eval.get("clv_ev_percent"),
            }
            db.table("pickem_research_observations").update(payload).eq("id", row["id"]).execute()
            updated_summary["pickem_updates"]["matched_count"] += 1
            updated_summary["pickem_updates"]["close_updated"] += 1
            updated_summary["pickem_updates"]["rescue_eligible_count"] += 1
            updated_summary["pickem_updates"]["rescue_from_latest_count"] += 1
            _bump_counter(updated_summary["pickem_updates"]["matched_surface_counts"], surface)
            _bump_counter(updated_summary["pickem_updates"]["matched_market_counts"], market_label)
            _mark_snapshot_reason(updated_summary["pickem_updates"], "promoted_from_latest")
        else:
            updated_summary["pickem_updates"]["close_rejected_count"] += 1
            _mark_snapshot_reason(updated_summary["pickem_updates"], "latest_not_in_close_window")

    return {
        "job_source": "clv_finalize",
        "grace_minutes": grace_minutes,
        "bet_updates": _normalize_snapshot_summary(updated_summary["bet_updates"]),
        "research_updates": _normalize_snapshot_summary(updated_summary["research_updates"]),
        "pickem_updates": _normalize_snapshot_summary(updated_summary["pickem_updates"]),
        "updated": int(updated_summary["bet_updates"]["close_updated"])
        + int(updated_summary["research_updates"]["close_updated"])
        + int(updated_summary["pickem_updates"]["close_updated"]),
        "close_updated": int(updated_summary["bet_updates"]["close_updated"])
        + int(updated_summary["research_updates"]["close_updated"])
        + int(updated_summary["pickem_updates"]["close_updated"]),
        "rescue_eligible_count": int(updated_summary["bet_updates"]["rescue_eligible_count"])
        + int(updated_summary["research_updates"]["rescue_eligible_count"])
        + int(updated_summary["pickem_updates"]["rescue_eligible_count"]),
        "rescue_from_latest_count": int(updated_summary["bet_updates"]["rescue_from_latest_count"])
        + int(updated_summary["research_updates"]["rescue_from_latest_count"])
        + int(updated_summary["pickem_updates"]["rescue_from_latest_count"]),
        "reason_counts": {
            "bets": dict(updated_summary["bet_updates"].get("reason_counts") or {}),
            "research": dict(updated_summary["research_updates"].get("reason_counts") or {}),
            "pickem": dict(updated_summary["pickem_updates"].get("reason_counts") or {}),
        },
    }


def update_bet_reference_snapshots(
    db,
    *,
    sides: list[dict[str, Any]],
    allow_close: bool,
    now: datetime | None = None,
    allow_retroactive_close_capture: bool = False,
) -> dict[str, Any]:
    if not sides:
        return _normalize_snapshot_summary(_new_snapshot_update_summary())

    straight_snapshot_by_event, straight_snapshot_by_time = build_reference_snapshots(sides)
    straight_exact_snapshot_by_event, straight_exact_snapshot_by_time = build_straight_exact_reference_snapshots(sides)
    prop_snapshot_by_event, prop_snapshot_by_time = build_prop_reference_snapshots(sides)
    straight_pair_by_event, straight_pair_by_time = build_reference_pair_snapshots(sides)
    straight_exact_pair_by_event, straight_exact_pair_by_time = build_straight_exact_pair_snapshots(sides)
    prop_pair_by_event, prop_pair_by_time = build_prop_reference_pair_snapshots(sides)
    coverage = _build_reference_coverage(sides)

    if (
        not straight_snapshot_by_event
        and not straight_snapshot_by_time
        and not straight_exact_snapshot_by_event
        and not straight_exact_snapshot_by_time
        and not prop_snapshot_by_event
        and not prop_snapshot_by_time
    ):
        return _normalize_snapshot_summary(_new_snapshot_update_summary())

    sports = sorted({str(side.get("sport") or "").strip() for side in sides if side.get("sport")})
    sports_set = {s for s in sports if s}
    query = (
        db.table("bets")
        .select(
            "id,result,surface,commence_time,clv_event_id,source_event_id,clv_sport_key,clv_team,"
            "participant_name,participant_id,source_market_key,source_selection_key,selection_side,line_value,odds_american,"
            "latest_pinnacle_odds,latest_pinnacle_updated_at,pinnacle_odds_at_close,clv_updated_at,selection_meta"
        )
        .eq("result", "pending")
    )
    if sports:
        query = query.in_("clv_sport_key", sports)

    result = query.execute()

    current = now or _utc_now()
    updated_at = current.isoformat()
    summary = _new_snapshot_update_summary()

    for row in result.data or []:
        repaired_row, repair_payload = _repair_bet_identity_row(row)
        surface = str(repaired_row.get("surface") or "straight_bets").strip().lower()
        market_label = (
            _normalize_text(repaired_row.get("source_market_key")) if surface == "player_props" else _straight_market_label(repaired_row)
        ) or ("player_props" if surface == "player_props" else "h2h")
        summary["row_count"] += 1
        _bump_counter(summary["candidate_surface_counts"], surface)
        _bump_counter(summary["candidate_market_counts"], market_label)
        _mark_identity_backfill(summary, repair_payload)

        if surface == "player_props":
            reference_odds = lookup_prop_reference_odds(
                player_name=repaired_row.get("participant_name"),
                participant_id=repaired_row.get("participant_id"),
                source_market_key=repaired_row.get("source_market_key"),
                selection_side=repaired_row.get("selection_side"),
                line_value=_normalize_line_value(repaired_row.get("line_value")),
                commence_time=repaired_row.get("commence_time"),
                event_id=repaired_row.get("source_event_id") or repaired_row.get("clv_event_id"),
                snapshot_by_event=prop_snapshot_by_event,
                snapshot_by_time=prop_snapshot_by_time,
            )
            opposing_reference_odds = lookup_prop_opposing_reference_odds(
                player_name=repaired_row.get("participant_name"),
                participant_id=repaired_row.get("participant_id"),
                source_market_key=repaired_row.get("source_market_key"),
                selection_side=repaired_row.get("selection_side"),
                line_value=_normalize_line_value(repaired_row.get("line_value")),
                commence_time=repaired_row.get("commence_time"),
                event_id=repaired_row.get("source_event_id") or repaired_row.get("clv_event_id"),
                pair_snapshot_by_event=prop_pair_by_event,
                pair_snapshot_by_time=prop_pair_by_time,
            )
        else:
            if not repaired_row.get("clv_team"):
                summary["unmatched_count"] += 1
                _mark_snapshot_reason(summary, "missing_identity")
                continue
            market_key = _normalize_text(repaired_row.get("source_market_key"))
            line_value = _normalize_line_value(repaired_row.get("line_value"))
            if market_key in {"spreads", "totals"} and line_value is not None:
                reference_odds = lookup_straight_exact_reference_odds(
                    team=repaired_row.get("clv_team"),
                    source_market_key=repaired_row.get("source_market_key"),
                    line_value=line_value,
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("source_event_id") or repaired_row.get("clv_event_id"),
                    snapshot_by_event=straight_exact_snapshot_by_event,
                    snapshot_by_time=straight_exact_snapshot_by_time,
                )
                opposing_reference_odds = lookup_straight_exact_opposing_reference_odds(
                    team=repaired_row.get("clv_team"),
                    source_market_key=repaired_row.get("source_market_key"),
                    line_value=line_value,
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("source_event_id") or repaired_row.get("clv_event_id"),
                    pair_snapshot_by_event=straight_exact_pair_by_event,
                    pair_snapshot_by_time=straight_exact_pair_by_time,
                )
            else:
                reference_odds = lookup_reference_odds(
                    team=repaired_row.get("clv_team"),
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("source_event_id") or repaired_row.get("clv_event_id"),
                    snapshot_by_event=straight_snapshot_by_event,
                    snapshot_by_time=straight_snapshot_by_time,
                )
                opposing_reference_odds = lookup_opposing_reference_odds(
                    team=repaired_row.get("clv_team"),
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("source_event_id") or repaired_row.get("clv_event_id"),
                    pair_snapshot_by_event=straight_pair_by_event,
                    pair_snapshot_by_time=straight_pair_by_time,
                )

        if reference_odds is None:
            summary["unmatched_count"] += 1
            if surface == "player_props":
                _mark_snapshot_reason(summary, _diagnose_prop_reference_miss(repaired_row, coverage, market_field="source_market_key"))
            else:
                _mark_snapshot_reason(summary, _diagnose_straight_reference_miss(repaired_row, coverage))
            continue

        payload: dict[str, Any] = {
            "latest_pinnacle_odds": reference_odds,
            "latest_pinnacle_updated_at": updated_at,
        }
        if repair_payload:
            payload.update(repair_payload)
        summary["matched_count"] += 1
        summary["latest_updated"] += 1
        _bump_counter(summary["matched_surface_counts"], surface)
        _bump_counter(summary["matched_market_counts"], market_label)

        can_capture_close = allow_close and should_capture_close_snapshot(
            repaired_row.get("commence_time"),
            existing_close=repaired_row.get("pinnacle_odds_at_close"),
            captured_at=repaired_row.get("clv_updated_at"),
            now=current,
            allow_retroactive_close_capture=allow_retroactive_close_capture,
        )
        if can_capture_close:
            payload.update(
                {
                    "pinnacle_odds_at_close": reference_odds,
                    "clv_updated_at": updated_at,
                }
            )
            summary["close_updated"] += 1
        elif allow_close and (
            repaired_row.get("pinnacle_odds_at_close") is None
            or not has_valid_close_snapshot(repaired_row.get("commence_time"), repaired_row.get("clv_updated_at"))
        ):
            summary["close_rejected_count"] += 1
            _mark_snapshot_reason(summary, "outside_close_window")

        try:
            db.table("bets").update(payload).eq("id", row["id"]).execute()
        except Exception:
            _mark_snapshot_reason(summary, "write_failed")
            raise

    p_latest, p_close = _update_parlay_bet_leg_snapshots(
        db,
        sports_set=sports_set,
        straight_snapshot_by_event=straight_snapshot_by_event,
        straight_snapshot_by_time=straight_snapshot_by_time,
        straight_exact_snapshot_by_event=straight_exact_snapshot_by_event,
        straight_exact_snapshot_by_time=straight_exact_snapshot_by_time,
        prop_snapshot_by_event=prop_snapshot_by_event,
        prop_snapshot_by_time=prop_snapshot_by_time,
        allow_close=allow_close,
        current=current,
        updated_at=updated_at,
        allow_retroactive_close_capture=allow_retroactive_close_capture,
    )
    summary["latest_updated"] += p_latest
    summary["close_updated"] += p_close

    return _normalize_snapshot_summary(summary)

def update_scan_opportunity_reference_snapshots(
    db,
    *,
    sides: list[dict[str, Any]],
    allow_close: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not sides:
        return _normalize_snapshot_summary(_new_snapshot_update_summary())

    straight_snapshot_by_event, straight_snapshot_by_time = build_reference_snapshots(sides)
    straight_exact_snapshot_by_event, straight_exact_snapshot_by_time = build_straight_exact_reference_snapshots(sides)
    prop_snapshot_by_event, prop_snapshot_by_time = build_prop_reference_snapshots(sides)
    straight_pair_by_event, straight_pair_by_time = build_reference_pair_snapshots(sides)
    straight_exact_pair_by_event, straight_exact_pair_by_time = build_straight_exact_pair_snapshots(sides)
    prop_pair_by_event, prop_pair_by_time = build_prop_reference_pair_snapshots(sides)
    coverage = _build_reference_coverage(sides)
    if (
        not straight_snapshot_by_event
        and not straight_snapshot_by_time
        and not straight_exact_snapshot_by_event
        and not straight_exact_snapshot_by_time
        and not prop_snapshot_by_event
        and not prop_snapshot_by_time
    ):
        return _normalize_snapshot_summary(_new_snapshot_update_summary())

    from services.research_opportunities import is_missing_scan_opportunities_error

    sports = sorted({str(side.get("sport") or "").strip() for side in sides if side.get("sport")})
    try:
        query = (
            db.table("scan_opportunities")
            .select(
                "id,opportunity_key,surface,sport,team,commence_time,event_id,player_name,source_market_key,selection_side,line_value,"
                "first_book_odds,latest_reference_odds,"
                "latest_reference_updated_at,reference_odds_at_close,close_captured_at,clv_ev_percent,beat_close"
            )
        )
        if sports:
            query = query.in_("sport", sports)
        result = query.execute()
    except Exception as e:
        if is_missing_scan_opportunities_error(e):
            return _normalize_snapshot_summary(_new_snapshot_update_summary())
        raise

    current = now or _utc_now()
    updated_at = current.isoformat()
    summary = _new_snapshot_update_summary()

    for row in result.data or []:
        repaired_row, repair_payload = _repair_scan_opportunity_identity_row(row)
        surface = str(repaired_row.get("surface") or "straight_bets").strip().lower()
        market_label = (
            _normalize_text(repaired_row.get("source_market_key")) if surface == "player_props" else _straight_market_label(repaired_row)
        ) or ("player_props" if surface == "player_props" else "h2h")
        summary["row_count"] += 1
        _bump_counter(summary["candidate_surface_counts"], surface)
        _bump_counter(summary["candidate_market_counts"], market_label)
        _mark_identity_backfill(summary, repair_payload)

        if surface == "player_props":
            reference_odds = lookup_prop_reference_odds(
                player_name=repaired_row.get("player_name"),
                source_market_key=repaired_row.get("source_market_key"),
                selection_side=repaired_row.get("selection_side"),
                line_value=_normalize_line_value(repaired_row.get("line_value")),
                commence_time=repaired_row.get("commence_time"),
                event_id=repaired_row.get("event_id"),
                snapshot_by_event=prop_snapshot_by_event,
                snapshot_by_time=prop_snapshot_by_time,
            )
            opposing_reference_odds = lookup_prop_opposing_reference_odds(
                player_name=repaired_row.get("player_name"),
                source_market_key=repaired_row.get("source_market_key"),
                selection_side=repaired_row.get("selection_side"),
                line_value=_normalize_line_value(repaired_row.get("line_value")),
                commence_time=repaired_row.get("commence_time"),
                event_id=repaired_row.get("event_id"),
                pair_snapshot_by_event=prop_pair_by_event,
                pair_snapshot_by_time=prop_pair_by_time,
            )
        else:
            market_key = _normalize_text(repaired_row.get("source_market_key"))
            line_value = _normalize_line_value(repaired_row.get("line_value"))
            if market_key in {"spreads", "totals"} and line_value is not None:
                reference_odds = lookup_straight_exact_reference_odds(
                    team=repaired_row.get("team"),
                    source_market_key=repaired_row.get("source_market_key"),
                    line_value=line_value,
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("event_id"),
                    snapshot_by_event=straight_exact_snapshot_by_event,
                    snapshot_by_time=straight_exact_snapshot_by_time,
                )
                opposing_reference_odds = lookup_straight_exact_opposing_reference_odds(
                    team=repaired_row.get("team"),
                    source_market_key=repaired_row.get("source_market_key"),
                    line_value=line_value,
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("event_id"),
                    pair_snapshot_by_event=straight_exact_pair_by_event,
                    pair_snapshot_by_time=straight_exact_pair_by_time,
                )
            else:
                reference_odds = lookup_reference_odds(
                    team=repaired_row.get("team"),
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("event_id"),
                    snapshot_by_event=straight_snapshot_by_event,
                    snapshot_by_time=straight_snapshot_by_time,
                )
                opposing_reference_odds = lookup_opposing_reference_odds(
                    team=repaired_row.get("team"),
                    commence_time=repaired_row.get("commence_time"),
                    event_id=repaired_row.get("event_id"),
                    pair_snapshot_by_event=straight_pair_by_event,
                    pair_snapshot_by_time=straight_pair_by_time,
                )
        if reference_odds is None:
            summary["unmatched_count"] += 1
            if surface == "player_props":
                _mark_snapshot_reason(summary, _diagnose_prop_reference_miss(repaired_row, coverage, market_field="source_market_key"))
            else:
                _mark_snapshot_reason(summary, _diagnose_straight_reference_miss({
                    **repaired_row,
                    "clv_team": repaired_row.get("team"),
                    "clv_event_id": repaired_row.get("event_id"),
                    "source_event_id": repaired_row.get("event_id"),
                }, coverage))
            continue

        payload: dict[str, Any] = {
            "latest_reference_odds": reference_odds,
            "latest_reference_updated_at": updated_at,
        }
        if repair_payload:
            payload.update(repair_payload)
        summary["matched_count"] += 1
        summary["latest_updated"] += 1
        _bump_counter(summary["matched_surface_counts"], surface)
        _bump_counter(summary["matched_market_counts"], market_label)

        can_capture_close = allow_close and should_capture_close_snapshot(
            repaired_row.get("commence_time"),
            existing_close=repaired_row.get("reference_odds_at_close"),
            captured_at=repaired_row.get("close_captured_at"),
            now=current,
        )
        if can_capture_close:
            clv_result = calculate_clv(float(repaired_row.get("first_book_odds")), reference_odds, opposing_reference_odds)
            payload.update(
                {
                    "reference_odds_at_close": reference_odds,
                    "close_captured_at": updated_at,
                    "clv_ev_percent": clv_result["clv_ev_percent"],
                    "beat_close": clv_result["beat_close"],
                    "close_true_prob": clv_result.get("close_true_prob"),
                    "close_quality": clv_result.get("close_quality"),
                    "close_opposing_reference_odds": opposing_reference_odds,
                }
            )
            if repaired_row.get("opportunity_key"):
                update_scan_opportunity_model_evaluations_close_snapshot(
                    db,
                    opportunity_key=str(repaired_row.get("opportunity_key")),
                    close_reference_odds=float(reference_odds),
                    close_opposing_reference_odds=opposing_reference_odds,
                    close_captured_at=updated_at,
                )
            summary["close_updated"] += 1
        elif allow_close and (
            repaired_row.get("reference_odds_at_close") is None
            or not has_valid_close_snapshot(repaired_row.get("commence_time"), repaired_row.get("close_captured_at"))
        ):
            summary["close_rejected_count"] += 1
            _mark_snapshot_reason(summary, "outside_close_window")

        try:
            db.table("scan_opportunities").update(payload).eq("id", row["id"]).execute()
        except Exception as exc:
            if _is_missing_scan_opportunities_column_error(
                exc,
                "close_true_prob",
                "close_quality",
                "close_opposing_reference_odds",
            ):
                legacy_payload = dict(payload)
                legacy_payload.pop("close_true_prob", None)
                legacy_payload.pop("close_quality", None)
                legacy_payload.pop("close_opposing_reference_odds", None)
                db.table("scan_opportunities").update(legacy_payload).eq("id", row["id"]).execute()
                _mark_snapshot_reason(summary, "db_schema_mismatch")
            else:
                _mark_snapshot_reason(summary, "write_failed")
                raise

    return _normalize_snapshot_summary(summary)
