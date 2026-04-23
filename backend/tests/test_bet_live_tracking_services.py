from datetime import datetime, timezone

import pytest

from models import LiveEventSnapshot, LivePlayerStatSnapshot, LiveTeamScore
from services.bet_live_tracking import build_live_snapshots_for_rows
from services.espn_live import normalize_espn_nba_event
from services.live_provider_contracts import (
    LiveBetCandidate,
    LivePlayerStatRequest,
    ProviderLookupResult,
    ProviderPlayerStatResult,
)


def _nba_event() -> LiveEventSnapshot:
    return LiveEventSnapshot(
        provider="fake",
        provider_event_id="espn-1",
        sport_key="basketball_nba",
        status="live",
        status_detail="Q3 04:22",
        period_label="Q3",
        clock="4:22",
        start_time=datetime(2026, 4, 22, 2, 0, tzinfo=timezone.utc),
        last_updated=datetime(2026, 4, 22, 3, 15, tzinfo=timezone.utc),
        away=LiveTeamScore(name="Los Angeles Lakers", short_name="LAL", score=68, home_away="away"),
        home=LiveTeamScore(name="Golden State Warriors", short_name="GSW", score=72, home_away="home"),
    )


class FakeLiveProvider:
    provider_name = "fake"

    def supports_sport(self, sport_key: str | None) -> bool:
        return sport_key == "basketball_nba"

    async def lookup_events(self, candidates: list[LiveBetCandidate], *, now=None):
        event = _nba_event()
        return {
            candidate.bet_id: ProviderLookupResult(
                candidate=candidate,
                event=event,
                confidence="matchup_plus_time",
                cache_hit=True,
            )
            for candidate in candidates
        }

    async def get_player_stat_snapshots(self, requests: list[LivePlayerStatRequest]):
        return {
            request.candidate.bet_id: ProviderPlayerStatResult(
                request=request,
                stat=LivePlayerStatSnapshot(
                    participant_name=request.candidate.participant_name or "",
                    stat_key="AST",
                    stat_label="AST",
                    value=2,
                    line_value=request.candidate.line_value,
                    selection_side=request.candidate.selection_side,
                    progress_ratio=0.5,
                    match_kind="exact",
                ),
                cache_hit=True,
            )
            for request in requests
        }


def test_normalize_espn_nba_event_extracts_live_score_and_clock():
    event = {
        "id": "401",
        "date": "2026-04-22T02:00:00Z",
        "competitions": [
            {
                "status": {
                    "period": 3,
                    "displayClock": "4:22",
                    "type": {"state": "in", "name": "STATUS_IN_PROGRESS", "description": "In Progress"},
                },
                "competitors": [
                    {
                        "homeAway": "away",
                        "score": "68",
                        "team": {"displayName": "Los Angeles Lakers", "abbreviation": "LAL"},
                    },
                    {
                        "homeAway": "home",
                        "score": "72",
                        "team": {"displayName": "Golden State Warriors", "abbreviation": "GSW"},
                    },
                ],
            }
        ],
    }

    out = normalize_espn_nba_event(event)

    assert out is not None
    assert out.provider_event_id == "401"
    assert out.status == "live"
    assert out.period_label == "Q3"
    assert out.clock == "4:22"
    assert out.away.score == 68
    assert out.home.short_name == "GSW"


@pytest.mark.asyncio
async def test_build_live_snapshots_returns_game_and_supported_prop_progress():
    rows = [
        {
            "id": "bet-1",
            "surface": "player_props",
            "event": "Los Angeles Lakers @ Golden State Warriors",
            "result": "pending",
            "clv_sport_key": "basketball_nba",
            "source_market_key": "player_assists",
            "participant_name": "LeBron James",
            "selection_side": "over",
            "line_value": 4,
            "commence_time": "2026-04-22T02:00:00Z",
        }
    ]

    out = await build_live_snapshots_for_rows(
        rows,
        now=datetime(2026, 4, 22, 3, 15, tzinfo=timezone.utc),
        providers={"fake": FakeLiveProvider()},
    )

    snapshot = out.snapshots_by_bet_id["bet-1"]
    assert out.active_bet_count == 1
    assert snapshot.status == "live"
    assert snapshot.event is not None
    assert snapshot.event.home.short_name == "GSW"
    assert snapshot.player_stat is not None
    assert snapshot.player_stat.stat_key == "AST"
    assert snapshot.player_stat.value == 2
    assert snapshot.provider.cache_hit is True


@pytest.mark.asyncio
async def test_build_live_snapshots_marks_unsupported_sport_unavailable():
    rows = [
        {
            "id": "bet-2",
            "surface": "straight_bets",
            "event": "Boston Bruins @ New York Rangers",
            "result": "pending",
            "clv_sport_key": "hockey_nhl",
            "commence_time": "2026-04-22T02:00:00Z",
        }
    ]

    out = await build_live_snapshots_for_rows(
        rows,
        now=datetime(2026, 4, 22, 3, 15, tzinfo=timezone.utc),
        providers={"fake": FakeLiveProvider()},
    )

    snapshot = out.snapshots_by_bet_id["bet-2"]
    assert snapshot.status == "unavailable"
    assert snapshot.provider.unavailable_reason == "unsupported_sport_or_provider"

