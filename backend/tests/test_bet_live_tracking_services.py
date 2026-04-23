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
from services.mlb_live import _enrich_mlb_event_with_linescore, _match_event_for_candidate


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


def _mlb_event(
    *,
    provider_event_id: str = "mlb-1",
    start_time: datetime | None = None,
) -> LiveEventSnapshot:
    return LiveEventSnapshot(
        provider="fake_mlb",
        provider_event_id=provider_event_id,
        sport_key="baseball_mlb",
        status="live",
        status_detail="Bottom 7th",
        period_label="B7",
        clock=None,
        start_time=start_time or datetime(2026, 4, 22, 23, 10, tzinfo=timezone.utc),
        last_updated=datetime(2026, 4, 23, 1, 15, tzinfo=timezone.utc),
        away=LiveTeamScore(name="New York Yankees", short_name="NYY", score=3, home_away="away"),
        home=LiveTeamScore(name="Boston Red Sox", short_name="BOS", score=2, home_away="home"),
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


class FakeMlbLiveProvider:
    provider_name = "fake_mlb"

    _stat_map = {
        "pitcher_strikeouts": ("P_SO", 4.0),
        "pitcher_strikeouts_alternate": ("P_SO", 4.0),
        "batter_total_bases": ("B_TB", 3.0),
        "batter_total_bases_alternate": ("B_TB", 3.0),
        "batter_hits": ("B_H", 2.0),
        "batter_hits_alternate": ("B_H", 2.0),
        "batter_hits_runs_rbis": ("B_H_R_RBI", 4.0),
    }

    def supports_sport(self, sport_key: str | None) -> bool:
        return sport_key == "baseball_mlb"

    async def lookup_events(self, candidates: list[LiveBetCandidate], *, now=None):
        event = _mlb_event()
        out: dict[str, ProviderLookupResult] = {}
        for candidate in candidates:
            if candidate.bet_id == "bet-ambiguous":
                out[candidate.bet_id] = ProviderLookupResult(
                    candidate=candidate,
                    event=None,
                    confidence="ambiguous",
                    unavailable_reason="ambiguous_provider_event_match",
                    cache_hit=True,
                )
                continue
            out[candidate.bet_id] = ProviderLookupResult(
                candidate=candidate,
                event=event,
                confidence="matchup_plus_time",
                cache_hit=True,
            )
        return out

    async def get_player_stat_snapshots(self, requests: list[LivePlayerStatRequest]):
        out: dict[str, ProviderPlayerStatResult] = {}
        for request in requests:
            market_key = request.candidate.market_key or ""
            stat_details = self._stat_map.get(market_key)
            if stat_details is None:
                out[request.candidate.bet_id] = ProviderPlayerStatResult(
                    request=request,
                    stat=None,
                    unavailable_reason="unsupported_prop_market",
                    cache_hit=True,
                )
                continue
            stat_key, value = stat_details
            line_value = request.candidate.line_value
            progress_ratio = None
            if line_value is not None and line_value > 0:
                progress_ratio = max(0.0, min(1.0, value / line_value))
            out[request.candidate.bet_id] = ProviderPlayerStatResult(
                request=request,
                stat=LivePlayerStatSnapshot(
                    participant_name=request.candidate.participant_name or "",
                    stat_key=stat_key,
                    stat_label=stat_key,
                    value=value,
                    line_value=line_value,
                    selection_side=request.candidate.selection_side,
                    progress_ratio=progress_ratio,
                    match_kind="exact",
                ),
                cache_hit=True,
            )
        return out


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


@pytest.mark.asyncio
async def test_build_live_snapshots_returns_mlb_live_game_status():
    rows = [
        {
            "id": "bet-mlb-game",
            "surface": "straight_bets",
            "event": "New York Yankees @ Boston Red Sox",
            "result": "pending",
            "clv_sport_key": "baseball_mlb",
            "commence_time": "2026-04-22T23:10:00Z",
        }
    ]

    out = await build_live_snapshots_for_rows(
        rows,
        now=datetime(2026, 4, 23, 1, 15, tzinfo=timezone.utc),
        providers={"fake_mlb": FakeMlbLiveProvider()},
    )

    snapshot = out.snapshots_by_bet_id["bet-mlb-game"]
    assert out.active_bet_count == 1
    assert snapshot.status == "live"
    assert snapshot.event is not None
    assert snapshot.event.status_detail == "Bottom 7th"
    assert snapshot.event.period_label == "B7"
    assert snapshot.event.away.short_name == "NYY"
    assert snapshot.event.home.score == 2
    assert snapshot.player_stat is None
    assert snapshot.provider.primary_provider == "fake_mlb"
    assert snapshot.provider.confidence == "matchup_plus_time"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("market_key", "line_value", "expected_stat_key", "expected_value", "expected_ratio"),
    [
        ("pitcher_strikeouts", 5.0, "P_SO", 4.0, 0.8),
        ("pitcher_strikeouts_alternate", 5.0, "P_SO", 4.0, 0.8),
        ("batter_total_bases", 4.0, "B_TB", 3.0, 0.75),
        ("batter_total_bases_alternate", 4.0, "B_TB", 3.0, 0.75),
        ("batter_hits", 2.5, "B_H", 2.0, 0.8),
        ("batter_hits_alternate", 2.5, "B_H", 2.0, 0.8),
        ("batter_hits_runs_rbis", 5.0, "B_H_R_RBI", 4.0, 0.8),
    ],
)
async def test_build_live_snapshots_returns_safe_mlb_prop_progress_for_supported_markets(
    market_key: str,
    line_value: float,
    expected_stat_key: str,
    expected_value: float,
    expected_ratio: float,
):
    rows = [
        {
            "id": f"bet-{market_key}",
            "surface": "player_props",
            "event": "New York Yankees @ Boston Red Sox",
            "result": "pending",
            "clv_sport_key": "baseball_mlb",
            "source_market_key": market_key,
            "participant_name": "Aaron Judge",
            "selection_side": "over",
            "line_value": line_value,
            "commence_time": "2026-04-22T23:10:00Z",
        }
    ]

    out = await build_live_snapshots_for_rows(
        rows,
        now=datetime(2026, 4, 23, 1, 15, tzinfo=timezone.utc),
        providers={"fake_mlb": FakeMlbLiveProvider()},
    )

    snapshot = out.snapshots_by_bet_id[f"bet-{market_key}"]
    assert snapshot.status == "live"
    assert snapshot.event is not None
    assert snapshot.event.period_label == "B7"
    assert snapshot.player_stat is not None
    assert snapshot.player_stat.participant_name == "Aaron Judge"
    assert snapshot.player_stat.stat_key == expected_stat_key
    assert snapshot.player_stat.value == expected_value
    assert snapshot.player_stat.line_value == line_value
    assert snapshot.player_stat.selection_side == "over"
    assert snapshot.player_stat.progress_ratio == pytest.approx(expected_ratio)
    assert snapshot.player_stat.match_kind == "exact"


@pytest.mark.asyncio
async def test_build_live_snapshots_marks_ambiguous_mlb_doubleheader_unavailable():
    rows = [
        {
            "id": "bet-ambiguous",
            "surface": "straight_bets",
            "event": "New York Yankees @ Boston Red Sox",
            "result": "pending",
            "clv_sport_key": "baseball_mlb",
            "commence_time": "2026-04-22T23:10:00Z",
        }
    ]

    out = await build_live_snapshots_for_rows(
        rows,
        now=datetime(2026, 4, 23, 1, 15, tzinfo=timezone.utc),
        providers={"fake_mlb": FakeMlbLiveProvider()},
    )

    snapshot = out.snapshots_by_bet_id["bet-ambiguous"]
    assert snapshot.status == "unavailable"
    assert snapshot.event is None
    assert snapshot.provider.primary_provider == "fake_mlb"
    assert snapshot.provider.unavailable_reason == "ambiguous_provider_event_match"
    assert snapshot.provider.confidence == "ambiguous"
    assert snapshot.provider.cache_hit is True


def test_match_event_for_candidate_prefers_clearer_mlb_doubleheader_start_time():
    candidate = LiveBetCandidate(
        bet_id="bet-mlb-clear",
        sport_key="baseball_mlb",
        event_name="New York Yankees @ Boston Red Sox",
        commence_time="2026-04-22T23:10:00Z",
        source_event_id=None,
        clv_event_id=None,
        away_team="New York Yankees",
        home_team="Boston Red Sox",
        market_key=None,
        participant_name=None,
        participant_id=None,
        selection_side=None,
        line_value=None,
    )
    early = _mlb_event(
        provider_event_id="mlb-early",
        start_time=datetime(2026, 4, 22, 20, 30, tzinfo=timezone.utc),
    )
    late = _mlb_event(
        provider_event_id="mlb-late",
        start_time=datetime(2026, 4, 22, 23, 0, tzinfo=timezone.utc),
    )

    event, confidence, reason = _match_event_for_candidate(candidate, [early, late])

    assert event is not None
    assert event.provider_event_id == "mlb-late"
    assert confidence == "matchup_plus_time"
    assert reason is None


def test_match_event_for_candidate_marks_close_mlb_doubleheader_as_ambiguous():
    candidate = LiveBetCandidate(
        bet_id="bet-mlb-ambiguous",
        sport_key="baseball_mlb",
        event_name="New York Yankees @ Boston Red Sox",
        commence_time="2026-04-22T23:10:00Z",
        source_event_id=None,
        clv_event_id=None,
        away_team="New York Yankees",
        home_team="Boston Red Sox",
        market_key=None,
        participant_name=None,
        participant_id=None,
        selection_side=None,
        line_value=None,
    )
    first = _mlb_event(
        provider_event_id="mlb-first",
        start_time=datetime(2026, 4, 22, 22, 20, tzinfo=timezone.utc),
    )
    second = _mlb_event(
        provider_event_id="mlb-second",
        start_time=datetime(2026, 4, 22, 23, 0, tzinfo=timezone.utc),
    )

    event, confidence, reason = _match_event_for_candidate(candidate, [first, second])

    assert event is None
    assert confidence == "ambiguous"
    assert reason == "ambiguous_provider_event_match"


def test_enrich_mlb_event_with_linescore_adds_compact_inning_context():
    event = _mlb_event()
    linescore = {
        "_live_fetched_at": "2026-04-23T01:16:00Z",
        "currentInning": 7,
        "currentInningOrdinal": "7th",
        "inningHalf": "Bottom",
        "teams": {
            "away": {"runs": 3},
            "home": {"runs": 2},
        },
    }

    enriched = _enrich_mlb_event_with_linescore(event, linescore)

    assert enriched.period_label == "B7"
    assert enriched.status_detail == "Bottom 7th"
    assert enriched.away.score == 3
    assert enriched.home.score == 2
    assert enriched.last_updated == datetime(2026, 4, 23, 1, 16, tzinfo=timezone.utc)
