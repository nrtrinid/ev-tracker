from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from models import LiveEventSnapshot, LivePlayerStatSnapshot


@dataclass(frozen=True)
class LiveBetCandidate:
    """Minimum bet/leg identity needed to resolve live state."""

    bet_id: str
    sport_key: str | None
    event_name: str | None
    commence_time: str | None
    source_event_id: str | None
    clv_event_id: str | None
    away_team: str | None
    home_team: str | None
    market_key: str | None
    participant_name: str | None
    participant_id: str | None
    selection_side: str | None
    line_value: float | None
    surface: str | None = None
    leg_index: int | None = None
    leg_count: int | None = None


@dataclass(frozen=True)
class ProviderLookupResult:
    candidate: LiveBetCandidate
    event: LiveEventSnapshot | None
    confidence: str
    unavailable_reason: str | None = None
    cache_hit: bool = False
    stale: bool = False


@dataclass(frozen=True)
class LivePlayerStatRequest:
    candidate: LiveBetCandidate
    provider_event_id: str


@dataclass(frozen=True)
class ProviderPlayerStatResult:
    request: LivePlayerStatRequest
    stat: LivePlayerStatSnapshot | None
    unavailable_reason: str | None = None
    cache_hit: bool = False
    stale: bool = False


class LiveTrackingProvider(Protocol):
    """Provider-neutral contract for live bet tracking adapters."""

    provider_name: str

    def supports_sport(self, sport_key: str | None) -> bool:
        ...

    async def lookup_events(
        self,
        candidates: list[LiveBetCandidate],
        *,
        now: datetime | None = None,
    ) -> dict[str, ProviderLookupResult]:
        ...

    async def get_player_stat_snapshots(
        self,
        requests: list[LivePlayerStatRequest],
    ) -> dict[str, ProviderPlayerStatResult]:
        ...

