from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from models import BetLiveSnapshot, BetLiveSnapshotResponse, LiveProviderMeta
from services.bet_crud import _retry_supabase
from services.espn_live import EspnLiveProvider
from services.live_provider_contracts import (
    LiveBetCandidate,
    LivePlayerStatRequest,
    LiveTrackingProvider,
)
from services.mlb_live import MlbLiveProvider

logger = logging.getLogger("ev_tracker.live_tracking")

LIVE_TRACKING_TTL_SECONDS = 60
_ACTIVE_PAST_WINDOW = timedelta(hours=8)
_ACTIVE_FUTURE_WINDOW = timedelta(hours=36)
_MAX_PENDING_ROWS = 500
_SUPPORTED_PROVIDERS: dict[str, LiveTrackingProvider] = {
    "espn": EspnLiveProvider(),
    "mlb": MlbLiveProvider(),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _live_tracking_enabled() -> bool:
    return (os.getenv("LIVE_TRACKING_ENABLED") or "1").strip().lower() not in {"0", "false", "off", "no"}


def _provider_order() -> list[str]:
    raw = os.getenv("LIVE_TRACKING_PROVIDER_ORDER")
    if raw is None:
        raw = "espn,mlb,api_sports,odds_scores"
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


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


def _pick_str(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _pick_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _parse_event_teams(event_name: str | None) -> tuple[str | None, str | None]:
    """Return (away, home) from common tracker event labels."""
    raw = str(event_name or "").strip()
    if not raw:
        return None, None
    separators = [
        r"\s+@\s+",
        r"\s+at\s+",
        r"\s+vs\.?\s+",
    ]
    for pattern in separators:
        pieces = re.split(pattern, raw, maxsplit=1, flags=re.IGNORECASE)
        if len(pieces) != 2:
            continue
        left = pieces[0].strip()
        right = pieces[1].strip()
        if left and right:
            return left, right
    return None, None


def _selection_meta(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("selection_meta")
    return meta if isinstance(meta, dict) else {}


def _prop_event_teams(row: dict[str, Any]) -> tuple[str | None, str | None]:
    meta = _selection_meta(row)

    away, home = _parse_event_teams(_pick_str(meta, "event", "game", "matchup"))
    if away and home:
        return away, home

    team = _pick_str(row, "clv_team") or _pick_str(meta, "team")
    opponent = _pick_str(meta, "opponent", "opponent_team")
    if team and opponent:
        return team, opponent

    return _parse_event_teams(_pick_str(row, "event"))


def _line_from_meta(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _candidate_from_row(row: dict[str, Any], *, now: datetime) -> LiveBetCandidate | None:
    sport_key = _pick_str(row, "clv_sport_key")
    surface = _pick_str(row, "surface") or "straight_bets"
    if surface == "parlay":
        meta = _selection_meta(row)
        if isinstance(meta, dict):
            legs = meta.get("legs")
            if isinstance(legs, list):
                for idx, raw_leg in enumerate(legs):
                    if not isinstance(raw_leg, dict):
                        continue
                    candidate = _candidate_from_leg(row, raw_leg, idx, len(legs), now=now)
                    if candidate is not None:
                        return candidate
        return None

    if surface == "player_props":
        away, home = _prop_event_teams(row)
    else:
        away, home = _parse_event_teams(_pick_str(row, "event"))
    commence_time = _pick_str(row, "commence_time")
    return LiveBetCandidate(
        bet_id=str(row.get("id") or ""),
        sport_key=sport_key,
        event_name=_pick_str(row, "event"),
        commence_time=commence_time,
        source_event_id=_pick_str(row, "source_event_id"),
        clv_event_id=_pick_str(row, "clv_event_id"),
        away_team=away,
        home_team=home,
        market_key=_pick_str(row, "source_market_key"),
        participant_name=_pick_str(row, "participant_name"),
        participant_id=_pick_str(row, "participant_id"),
        selection_side=_pick_str(row, "selection_side"),
        line_value=_pick_float(row, "line_value"),
        surface=surface,
    )


def _candidate_from_leg(
    row: dict[str, Any],
    raw_leg: dict[str, Any],
    index: int,
    leg_count: int,
    *,
    now: datetime,
) -> LiveBetCandidate | None:
    away, home = _parse_event_teams(_pick_str(raw_leg, "event"))
    sport_key = _pick_str(raw_leg, "sport")
    if sport_key and sport_key.upper() == sport_key and "_" not in sport_key:
        # Logged parlay legs often carry display sport ("NBA"); parent CLV key is safer when present.
        sport_key = _pick_str(row, "clv_sport_key") or sport_key
    candidate = LiveBetCandidate(
        bet_id=str(row.get("id") or ""),
        sport_key=sport_key or _pick_str(row, "clv_sport_key"),
        event_name=_pick_str(raw_leg, "event") or _pick_str(row, "event"),
        commence_time=_pick_str(raw_leg, "commenceTime", "commence_time") or _pick_str(row, "commence_time"),
        source_event_id=_pick_str(raw_leg, "sourceEventId", "source_event_id", "eventId", "event_id"),
        clv_event_id=_pick_str(row, "clv_event_id"),
        away_team=away,
        home_team=home,
        market_key=_pick_str(raw_leg, "sourceMarketKey", "source_market_key", "marketKey", "market_key"),
        participant_name=_pick_str(raw_leg, "participantName", "participant_name"),
        participant_id=_pick_str(raw_leg, "participantId", "participant_id"),
        selection_side=_pick_str(raw_leg, "selectionSide", "selection_side"),
        line_value=_line_from_meta(raw_leg.get("lineValue") if "lineValue" in raw_leg else raw_leg.get("line_value")),
        surface="parlay",
        leg_index=index,
        leg_count=leg_count,
    )
    commence = _parse_utc_iso(candidate.commence_time)
    if commence is None:
        return candidate
    if now - _ACTIVE_PAST_WINDOW <= commence <= now + _ACTIVE_FUTURE_WINDOW:
        return candidate
    return None


def _is_candidate_active(candidate: LiveBetCandidate, now: datetime) -> bool:
    commence = _parse_utc_iso(candidate.commence_time)
    if commence is None:
        return bool(candidate.source_event_id or candidate.clv_event_id)
    return now - _ACTIVE_PAST_WINDOW <= commence <= now + _ACTIVE_FUTURE_WINDOW


def _unavailable_snapshot(
    bet_id: str,
    *,
    sport_key: str | None,
    reason: str,
    provider_name: str | None = None,
) -> BetLiveSnapshot:
    return BetLiveSnapshot(
        bet_id=bet_id,
        sport_key=sport_key,
        status="unavailable",
        provider=LiveProviderMeta(
            primary_provider=provider_name,
            source="live_tracking",
            unavailable_reason=reason,
        ),
    )


def _fetch_pending_live_rows(db, user_id: str) -> list[dict[str, Any]]:
    response = _retry_supabase(
        lambda: (
            db.table("bets")
            .select(
                "id,surface,event,result,clv_sport_key,clv_event_id,source_event_id,"
                "source_market_key,participant_name,participant_id,selection_side,line_value,"
                "commence_time,clv_team,selection_meta"
            )
            .eq("user_id", user_id)
            .eq("result", "pending")
            .range(0, _MAX_PENDING_ROWS - 1)
            .execute()
        ),
        label="bets.live.select_pending",
    )
    rows = response.data or []
    return [row for row in rows if isinstance(row, dict)]


async def build_live_snapshots_for_rows(
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    providers: dict[str, LiveTrackingProvider] | None = None,
) -> BetLiveSnapshotResponse:
    generated_at = now or _utc_now()
    provider_map = providers or _SUPPORTED_PROVIDERS
    provider_order = list(provider_map.keys()) if providers is not None else _provider_order()
    snapshots: dict[str, BetLiveSnapshot] = {}

    candidates: list[LiveBetCandidate] = []
    for row in rows:
        bet_id = str(row.get("id") or "").strip()
        if not bet_id:
            continue
        candidate = _candidate_from_row(row, now=generated_at)
        if candidate is None:
            snapshots[bet_id] = _unavailable_snapshot(
                bet_id,
                sport_key=_pick_str(row, "clv_sport_key"),
                reason="missing_live_identity",
            )
            continue
        if not _is_candidate_active(candidate, generated_at):
            snapshots[bet_id] = _unavailable_snapshot(
                bet_id,
                sport_key=candidate.sport_key,
                reason="outside_live_window",
            )
            continue
        candidates.append(candidate)

    unresolved = {candidate.bet_id: candidate for candidate in candidates}
    for provider_name in provider_order:
        provider = provider_map.get(provider_name)
        if provider is None:
            continue
        provider_candidates = [
            candidate for candidate in unresolved.values()
            if provider.supports_sport(candidate.sport_key)
        ]
        if not provider_candidates:
            continue
        lookup = await provider.lookup_events(provider_candidates, now=generated_at)
        stat_requests: list[LivePlayerStatRequest] = []

        for bet_id, result in lookup.items():
            candidate = result.candidate
            if result.event is None:
                snapshots[bet_id] = _unavailable_snapshot(
                    bet_id,
                    sport_key=candidate.sport_key,
                    reason=result.unavailable_reason or "provider_event_unavailable",
                    provider_name=provider.provider_name,
                )
                snapshots[bet_id].provider.cache_hit = result.cache_hit
                snapshots[bet_id].provider.stale = result.stale
                snapshots[bet_id].provider.confidence = result.confidence
                continue
            snapshot = BetLiveSnapshot(
                bet_id=bet_id,
                sport_key=candidate.sport_key,
                status=result.event.status,
                event=result.event,
                provider=LiveProviderMeta(
                    primary_provider=provider.provider_name,
                    source="live_tracking",
                    cache_hit=result.cache_hit,
                    stale=result.stale,
                    last_updated=result.event.last_updated,
                    confidence=result.confidence,
                ),
            )
            snapshots[bet_id] = snapshot
            unresolved.pop(bet_id, None)
            if candidate.participant_name and candidate.market_key and result.event.status in {"live", "final"}:
                stat_requests.append(
                    LivePlayerStatRequest(
                        candidate=candidate,
                        provider_event_id=result.event.provider_event_id,
                    )
                )

        if stat_requests:
            stat_results = await provider.get_player_stat_snapshots(stat_requests)
            for bet_id, stat_result in stat_results.items():
                snapshot = snapshots.get(bet_id)
                if snapshot is None:
                    continue
                snapshot.provider.cache_hit = snapshot.provider.cache_hit or stat_result.cache_hit
                snapshot.provider.stale = snapshot.provider.stale or stat_result.stale
                if stat_result.stat is not None:
                    snapshot.player_stat = stat_result.stat
                elif stat_result.unavailable_reason and not snapshot.provider.unavailable_reason:
                    snapshot.provider.unavailable_reason = stat_result.unavailable_reason

    for bet_id, candidate in unresolved.items():
        if bet_id not in snapshots:
            snapshots[bet_id] = _unavailable_snapshot(
                bet_id,
                sport_key=candidate.sport_key,
                reason="unsupported_sport_or_provider",
            )

    return BetLiveSnapshotResponse(
        generated_at=generated_at,
        ttl_seconds=LIVE_TRACKING_TTL_SECONDS,
        active_bet_count=len(candidates),
        snapshots_by_bet_id=snapshots,
    )


async def get_bet_live_snapshots_impl(
    db,
    user: dict[str, Any],
    *,
    now: datetime | None = None,
) -> BetLiveSnapshotResponse:
    generated_at = now or _utc_now()
    if not _live_tracking_enabled():
        return BetLiveSnapshotResponse(
            generated_at=generated_at,
            ttl_seconds=LIVE_TRACKING_TTL_SECONDS,
            active_bet_count=0,
            snapshots_by_bet_id={},
        )

    rows = _fetch_pending_live_rows(db, str(user.get("id") or ""))
    response = await build_live_snapshots_for_rows(rows, now=generated_at)
    logger.info(
        "live_tracking.snapshots user_id=%s pending_rows=%s active=%s snapshots=%s",
        user.get("id"),
        len(rows),
        response.active_bet_count,
        len(response.snapshots_by_bet_id),
    )
    return response
