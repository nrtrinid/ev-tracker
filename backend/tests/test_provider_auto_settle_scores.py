import asyncio
import types
from datetime import datetime, timezone

from services.provider_scores import (
    ProviderCompletedEventsResult,
    normalize_espn_nba_completed_event,
    normalize_mlb_completed_event,
)


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table_name, *, mode="select", payload=None, filters=None):
        self._db = db
        self._table_name = table_name
        self._mode = mode
        self._payload = payload
        self._filters = list(filters or [])

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters.append(lambda row, field=field, value=value: row.get(field) == value)
        return self

    def lt(self, field, value):
        self._filters.append(lambda row, field=field, value=value: str(row.get(field) or "") < str(value))
        return self

    @property
    def not_(self):
        return self

    def is_(self, field, value):
        if str(value).strip().lower() == "null":
            self._filters.append(lambda row, field=field: row.get(field) is not None)
        return self

    def update(self, payload):
        return _Query(
            self._db,
            self._table_name,
            mode="update",
            payload=payload,
            filters=self._filters,
        )

    def execute(self):
        rows = self._db.tables.setdefault(self._table_name, [])
        matched = [row for row in rows if all(predicate(row) for predicate in self._filters)]
        if self._mode == "update":
            for row in matched:
                row.update(self._payload)
            return _Resp([])
        return _Resp([dict(row) for row in matched])


class _DB:
    def __init__(self, *, bets=None, pickem=None):
        self.tables = {
            "bets": list(bets or []),
            "pickem_research_observations": list(pickem or []),
        }

    def table(self, name):
        return _Query(self, name)


def _espn_final_event(*, final_at="2026-04-01T03:00:00Z"):
    return {
        "id": "401",
        "date": "2026-04-01T00:00:00Z",
        "final_at": final_at,
        "competitions": [
            {
                "status": {"type": {"completed": True}},
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {"displayName": "Los Angeles Lakers"},
                        "score": "120",
                    },
                    {
                        "homeAway": "away",
                        "team": {"displayName": "Boston Celtics"},
                        "score": "100",
                    },
                ],
            }
        ],
    }


def _mlb_final_game(*, final_at="2026-04-01T23:00:00Z"):
    return {
        "gamePk": 777,
        "gameDate": "2026-04-01T19:10:00Z",
        "final_at": final_at,
        "status": {"abstractGameState": "Final", "codedGameState": "F"},
        "teams": {
            "away": {
                "team": {"id": 135, "name": "San Diego Padres"},
                "score": 3,
            },
            "home": {
                "team": {"id": 119, "name": "Los Angeles Dodgers"},
                "score": 5,
            },
        },
    }


def test_normalize_espn_nba_completed_event_shape():
    event, reason = normalize_espn_nba_completed_event(
        _espn_final_event(),
        now=datetime(2026, 4, 1, 4, 0, tzinfo=timezone.utc),
        finality_delay_minutes=15,
    )

    assert reason is None
    assert event["id"] == "espn:401"
    assert event["source_provider"] == "espn"
    assert event["home_team"] == "Los Angeles Lakers"
    assert event["away_team"] == "Boston Celtics"
    assert event["completed"] is True
    assert event["scores"] == [
        {"name": "Los Angeles Lakers", "score": "120"},
        {"name": "Boston Celtics", "score": "100"},
    ]


def test_normalize_mlb_completed_event_shape():
    event, reason = normalize_mlb_completed_event(
        _mlb_final_game(),
        now=datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc),
        finality_delay_minutes=15,
    )

    assert reason is None
    assert event["id"] == "mlb_statsapi:777"
    assert event["source_provider"] == "mlb_statsapi"
    assert event["home_team"] == "Los Angeles Dodgers"
    assert event["away_team"] == "San Diego Padres"
    assert event["scores"] == [
        {"name": "Los Angeles Dodgers", "score": "5"},
        {"name": "San Diego Padres", "score": "3"},
    ]


def test_normalize_provider_completed_event_respects_finality_delay():
    event, reason = normalize_espn_nba_completed_event(
        _espn_final_event(final_at="2026-04-01T03:00:00Z"),
        now=datetime(2026, 4, 1, 3, 10, tzinfo=timezone.utc),
        finality_delay_minutes=15,
    )

    assert event is None
    assert reason == "finality_delay"


def test_build_provider_score_rows_excludes_manual_backlog_and_future_parlay_legs():
    from services.odds_api import _build_provider_score_rows

    rows = _build_provider_score_rows(
        standalone_bets=[
            {
                "market": "ML",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Los Angeles Lakers",
                "commence_time": "2026-04-01T00:00:00Z",
            },
            {
                "market": "Spread",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_nba",
                "commence_time": "2026-04-01T00:00:00Z",
            },
            {
                "market": "Over 0.5 Walks",
                "surface": "player_props",
                "clv_sport_key": "baseball_mlb",
                "source_market_key": "batter_walks",
                "participant_name": "Mookie Betts",
                "selection_side": "over",
                "line_value": 0.5,
                "commence_time": "2026-04-01T01:00:00Z",
            },
            {
                "market": "Over 1.5 Hits",
                "surface": "player_props",
                "clv_sport_key": "baseball_mlb",
                "clv_team": "Los Angeles Dodgers",
                "source_market_key": "batter_hits",
                "participant_name": "Mookie Betts",
                "selection_side": "over",
                "line_value": 1.5,
                "commence_time": "2026-04-01T02:00:00Z",
            },
        ],
        parlay_bets=[
            {
                "selection_meta": {
                    "legs": [
                        {
                            "surface": "straight_bets",
                            "sport": "baseball_mlb",
                            "team": "Los Angeles Dodgers",
                            "commenceTime": "2026-04-02T00:00:00Z",
                        },
                        {
                            "surface": "straight_bets",
                            "sport": "baseball_mlb",
                            "team": "Los Angeles Dodgers",
                            "commenceTime": "2026-04-20T00:00:00Z",
                        },
                    ]
                }
            }
        ],
        pickem_pending_rows=[
            {
                "sport": "basketball_nba",
                "market_key": "player_points",
                "team": "Los Angeles Lakers",
                "player_name": "LeBron James",
                "selection_side": "over",
                "line_value": 24.5,
                "commence_time": "2026-04-03T00:00:00Z",
            },
            {
                "sport": "basketball_nba",
                "market_key": "player_blocks",
                "team": "Los Angeles Lakers",
                "player_name": "LeBron James",
                "selection_side": "over",
                "line_value": 0.5,
                "commence_time": "2026-04-03T00:00:00Z",
            },
        ],
        now=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )

    assert rows == [
        {"sport": "basketball_nba", "commence_time": "2026-04-01T00:00:00Z"},
        {"sport": "baseball_mlb", "commence_time": "2026-04-01T02:00:00Z"},
        {"sport": "baseball_mlb", "commence_time": "2026-04-02T00:00:00Z"},
        {"sport": "basketball_nba", "commence_time": "2026-04-03T00:00:00Z"},
    ]


def test_run_auto_settler_provider_first_skips_odds_scores(monkeypatch):
    from services import odds_api

    db = _DB(
        bets=[
            {
                "id": "bet-1",
                "result": "pending",
                "market": "ML",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Los Angeles Lakers",
                "commence_time": "2026-04-01T00:05:00Z",
                "clv_event_id": "odds-api-event-id",
            }
        ]
    )

    async def _fake_provider_scores(*_args, **_kwargs):
        return ProviderCompletedEventsResult(
            completed_by_sport={
                "basketball_nba": [
                    {
                        "id": "espn:401",
                        "provider_event_id": "401",
                        "source_provider": "espn",
                        "home_team": "Los Angeles Lakers",
                        "away_team": "Boston Celtics",
                        "commence_time": "2026-04-01T00:00:00Z",
                        "completed": True,
                        "scores": [
                            {"name": "Los Angeles Lakers", "score": "120"},
                            {"name": "Boston Celtics", "score": "100"},
                        ],
                    }
                ]
            },
            telemetry={
                "score_source": "provider_first",
                "provider_score_supported_sports": ["basketball_nba"],
                "provider_score_fetch_errors": [],
                "provider_completed_events": {"basketball_nba": 1},
                "provider_completed_event_count": 1,
                "provider_finality_delay_skipped": {},
                "provider_skipped_events": {},
                "provider_fallback_sports": [],
                "odds_api_score_sports": [],
                "odds_api_completed_events": {},
            },
        )

    async def _fail_fetch_scores(*_args, **_kwargs):
        raise AssertionError("Odds API scores should not be fetched when provider finals match")

    monkeypatch.setenv("AUTO_SETTLE_SCORE_SOURCE", "provider_first")
    monkeypatch.setenv("AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS", "1")
    monkeypatch.setattr(
        "services.provider_scores.fetch_provider_completed_events_for_auto_settle",
        _fake_provider_scores,
    )
    monkeypatch.setattr(odds_api, "fetch_scores", _fail_fetch_scores)

    settled = asyncio.run(odds_api.run_auto_settler(db, source="test"))

    assert settled == 1
    assert db.tables["bets"][0]["result"] == "win"
    summary = odds_api.get_last_auto_settler_summary()
    assert summary["score_source_telemetry"]["provider_completed_events"]["basketball_nba"] == 1
    assert summary["score_source_telemetry"]["odds_api_score_sports"] == []


def test_run_auto_settler_falls_back_to_odds_when_provider_unresolved(monkeypatch):
    from services import odds_api

    db = _DB(
        bets=[
            {
                "id": "bet-1",
                "result": "pending",
                "market": "ML",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Los Angeles Lakers",
                "commence_time": "2026-04-01T00:00:00Z",
            }
        ]
    )
    score_calls: list[str] = []

    async def _fake_provider_scores(*_args, **_kwargs):
        return ProviderCompletedEventsResult(
            completed_by_sport={"basketball_nba": []},
            telemetry={
                "score_source": "provider_first",
                "provider_score_supported_sports": ["basketball_nba"],
                "provider_score_fetch_errors": [],
                "provider_completed_events": {"basketball_nba": 0},
                "provider_completed_event_count": 0,
                "provider_finality_delay_skipped": {},
                "provider_skipped_events": {"basketball_nba": {"not_final": 1}},
                "provider_fallback_sports": [],
                "odds_api_score_sports": [],
                "odds_api_completed_events": {},
            },
        )

    async def _fake_fetch_scores(sport, source="auto_settle"):
        score_calls.append(sport)
        return [
            {
                "id": "odds-event",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "commence_time": "2026-04-01T00:00:00Z",
                "completed": True,
                "scores": [
                    {"name": "Los Angeles Lakers", "score": "120"},
                    {"name": "Boston Celtics", "score": "100"},
                ],
            }
        ]

    monkeypatch.setenv("AUTO_SETTLE_SCORE_SOURCE", "provider_first")
    monkeypatch.setenv("AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS", "1")
    monkeypatch.setattr(
        "services.provider_scores.fetch_provider_completed_events_for_auto_settle",
        _fake_provider_scores,
    )
    monkeypatch.setattr(odds_api, "fetch_scores", _fake_fetch_scores)

    settled = asyncio.run(odds_api.run_auto_settler(db, source="test"))

    assert settled == 1
    assert score_calls == ["basketball_nba"]
    assert db.tables["bets"][0]["result"] == "win"
    summary = odds_api.get_last_auto_settler_summary()
    assert summary["score_source_telemetry"]["provider_fallback_sports"] == ["basketball_nba"]
    assert summary["score_source_telemetry"]["odds_api_completed_events"]["basketball_nba"] == 1


def test_run_auto_settler_does_not_bypass_provider_finality_delay(monkeypatch):
    from services import odds_api

    db = _DB(
        bets=[
            {
                "id": "bet-1",
                "result": "pending",
                "market": "ML",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Los Angeles Lakers",
                "commence_time": "2026-04-01T00:00:00Z",
            }
        ]
    )

    async def _fake_provider_scores(*_args, **_kwargs):
        return ProviderCompletedEventsResult(
            completed_by_sport={"basketball_nba": []},
            telemetry={
                "score_source": "provider_first",
                "provider_score_supported_sports": ["basketball_nba"],
                "provider_score_fetch_errors": [],
                "provider_completed_events": {"basketball_nba": 0},
                "provider_completed_event_count": 0,
                "provider_finality_delay_skipped": {"basketball_nba": 1},
                "provider_skipped_events": {"basketball_nba": {"finality_delay": 1}},
                "provider_fallback_sports": [],
                "odds_api_score_sports": [],
                "odds_api_completed_events": {},
            },
        )

    async def _fail_fetch_scores(*_args, **_kwargs):
        raise AssertionError("Odds API fallback should not bypass provider finality delay")

    monkeypatch.setenv("AUTO_SETTLE_SCORE_SOURCE", "provider_first")
    monkeypatch.setenv("AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS", "1")
    monkeypatch.setattr(
        "services.provider_scores.fetch_provider_completed_events_for_auto_settle",
        _fake_provider_scores,
    )
    monkeypatch.setattr(odds_api, "fetch_scores", _fail_fetch_scores)

    settled = asyncio.run(odds_api.run_auto_settler(db, source="test"))

    assert settled == 0
    assert db.tables["bets"][0]["result"] == "pending"
    summary = odds_api.get_last_auto_settler_summary()
    assert summary["score_source_telemetry"]["provider_fallback_sports"] == []
    assert summary["score_source_telemetry"]["provider_finality_delay_skipped"]["basketball_nba"] == 1


def test_run_auto_settler_uses_odds_scores_for_unsupported_sports(monkeypatch):
    from services import odds_api

    db = _DB(
        bets=[
            {
                "id": "bet-1",
                "result": "pending",
                "market": "ML",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_ncaab",
                "clv_team": "Duke Blue Devils",
                "commence_time": "2026-04-01T00:00:00Z",
            }
        ]
    )
    score_calls: list[str] = []

    async def _fake_provider_scores(*_args, **_kwargs):
        return ProviderCompletedEventsResult(
            completed_by_sport={},
            telemetry={
                "score_source": "provider_first",
                "provider_score_supported_sports": [],
                "provider_score_fetch_errors": [],
                "provider_completed_events": {},
                "provider_completed_event_count": 0,
                "provider_finality_delay_skipped": {},
                "provider_skipped_events": {},
                "provider_fallback_sports": [],
                "odds_api_score_sports": [],
                "odds_api_completed_events": {},
            },
        )

    async def _fake_fetch_scores(sport, source="auto_settle"):
        score_calls.append(sport)
        return [
            {
                "id": "odds-event",
                "home_team": "Duke Blue Devils",
                "away_team": "North Carolina Tar Heels",
                "commence_time": "2026-04-01T00:00:00Z",
                "completed": True,
                "scores": [
                    {"name": "Duke Blue Devils", "score": "82"},
                    {"name": "North Carolina Tar Heels", "score": "77"},
                ],
            }
        ]

    monkeypatch.setenv("AUTO_SETTLE_SCORE_SOURCE", "provider_first")
    monkeypatch.setattr(
        "services.provider_scores.fetch_provider_completed_events_for_auto_settle",
        _fake_provider_scores,
    )
    monkeypatch.setattr(odds_api, "fetch_scores", _fake_fetch_scores)

    settled = asyncio.run(odds_api.run_auto_settler(db, source="test"))

    assert settled == 1
    assert score_calls == ["basketball_ncaab"]
    assert db.tables["bets"][0]["result"] == "win"


def test_settle_standalone_prop_accepts_provider_completed_event(monkeypatch):
    from services.prop_settler import settle_standalone_props

    db = _DB(
        bets=[
            {
                "id": "prop-1",
                "result": "pending",
                "market": "Over 24.5 PTS",
                "surface": "player_props",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Denver Nuggets",
                "commence_time": "2026-04-01T00:05:00Z",
                "participant_name": "Nikola Jokic",
                "source_market_key": "player_points",
                "line_value": 24.5,
                "selection_side": "over",
            }
        ]
    )

    async def _fake_provider_events(*_args, **_kwargs):
        return {"basketball_nba": []}

    async def _fake_resolve(*_args, **_kwargs):
        return types.SimpleNamespace(provider_event_id="401", confidence_tier="matchup_plus_time")

    async def _fake_summary(*_args, **_kwargs):
        return {"boxscore": True}

    monkeypatch.setattr(
        "services.prop_settler.fetch_boxscore_provider_events_for_rows",
        _fake_provider_events,
    )
    monkeypatch.setattr("services.prop_settler.resolve_boxscore_event_id", _fake_resolve)
    monkeypatch.setattr("services.prop_settler.fetch_boxscore_summary", _fake_summary)
    monkeypatch.setattr(
        "services.prop_settler.build_player_stat_map",
        lambda _summary, sport="basketball_nba": {"nikolajokic": {"PTS": 31.0}},
    )

    settled, skipped = asyncio.run(
        settle_standalone_props(
            db,
            db.tables["bets"],
            {
                "basketball_nba": [
                    {
                        "id": "espn:401",
                        "provider_event_id": "401",
                        "source_provider": "espn",
                        "home_team": "Denver Nuggets",
                        "away_team": "Phoenix Suns",
                        "commence_time": "2026-04-01T00:00:00Z",
                        "completed": True,
                        "scores": [
                            {"name": "Denver Nuggets", "score": "115"},
                            {"name": "Phoenix Suns", "score": "101"},
                        ],
                    }
                ]
            },
            "2026-04-01T04:00:00Z",
            source="test",
            now=datetime(2026, 4, 1, 4, 0, tzinfo=timezone.utc),
        )
    )

    assert settled == 1
    assert skipped["no_match"] == 0
    assert db.tables["bets"][0]["result"] == "win"
