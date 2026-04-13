import asyncio
import types

from services.pickem_research import (
    capture_pickem_research_observations,
    get_pickem_research_summary,
    settle_pickem_research_observations,
    update_pickem_research_close_snapshots,
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

    def select(self, _fields):
        return self

    def in_(self, key, values):
        value_set = set(values)
        self._filters.append(lambda row: row.get(key) in value_set)
        return self

    def eq(self, key, value):
        self._filters.append(lambda row: row.get(key) == value)
        return self

    def update(self, payload):
        return _Query(
            self._db,
            self._table_name,
            mode="update",
            payload=payload,
            filters=self._filters,
        )

    def insert(self, payload):
        return _Query(self._db, self._table_name, mode="insert", payload=payload)

    def execute(self):
        rows = self._db.tables[self._table_name]
        matched = [row for row in rows if all(predicate(row) for predicate in self._filters)]

        if self._mode == "select":
            return _Resp([dict(row) for row in matched])

        if self._mode == "update":
            for row in matched:
                row.update(self._payload)
            return _Resp([])

        payload = self._payload if isinstance(self._payload, list) else [self._payload]
        inserted = []
        for item in payload:
            row = dict(item)
            if "id" not in row:
                row["id"] = f"{self._table_name}-{self._db._next_id}"
                self._db._next_id += 1
            rows.append(row)
            inserted.append(row)
        return _Resp(inserted)


class _DB:
    def __init__(self, rows=None):
        self.tables = {
            "pickem_research_observations": list(rows or []),
        }
        self._next_id = len(self.tables["pickem_research_observations"]) + 1

    def table(self, name):
        assert name == "pickem_research_observations"
        return _Query(self, name)


def _card(
    *,
    comparison_key="evt-1|nikola-jokic|player_points|24.5",
    event_id="evt-1",
    consensus_side="over",
    consensus_over_prob=0.67,
    consensus_under_prob=0.33,
    line_value=24.5,
    exact_line_bookmaker_count=3,
    confidence_label="high",
    best_over_sportsbook="FanDuel",
    best_over_odds=105,
    best_under_sportsbook="DraftKings",
    best_under_odds=-125,
):
    return {
        "comparison_key": comparison_key,
        "event_id": event_id,
        "sport": "basketball_nba",
        "event": "Nuggets @ Suns",
        "commence_time": "2026-04-02T01:00:00Z",
        "player_name": "Nikola Jokic",
        "team": "Denver Nuggets",
        "opponent": "Phoenix Suns",
        "market_key": "player_points",
        "market": "player_points",
        "line_value": line_value,
        "exact_line_bookmakers": ["FanDuel", "DraftKings", "BetMGM"],
        "exact_line_bookmaker_count": exact_line_bookmaker_count,
        "consensus_over_prob": consensus_over_prob,
        "consensus_under_prob": consensus_under_prob,
        "consensus_side": consensus_side,
        "confidence_label": confidence_label,
        "best_over_sportsbook": best_over_sportsbook,
        "best_over_odds": best_over_odds,
        "best_under_sportsbook": best_under_sportsbook,
        "best_under_odds": best_under_odds,
    }


def test_capture_pickem_research_observations_inserts_then_updates_same_daily_key():
    db = _DB()

    first = capture_pickem_research_observations(
        db,
        cards=[_card()],
        source="cron_board_drop",
        captured_at="2026-04-01T15:30:00Z",
    )
    second = capture_pickem_research_observations(
        db,
        cards=[_card(best_over_odds=110, confidence_label="elite")],
        source="ops_trigger_board_drop",
        captured_at="2026-04-01T15:35:00Z",
    )

    assert first == {"eligible_seen": 1, "inserted": 1, "updated": 0}
    assert second == {"eligible_seen": 1, "inserted": 0, "updated": 1}
    assert len(db.tables["pickem_research_observations"]) == 1

    row = db.tables["pickem_research_observations"][0]
    assert row["first_source"] == "cron_board_drop"
    assert row["last_source"] == "ops_trigger_board_drop"
    assert row["first_display_probability"] == 0.67
    assert row["last_selected_market_odds"] == 110.0
    assert row["last_confidence_label"] == "elite"
    assert row["surfaced_count"] == 2
    assert row["calibration_bucket"] == "65-70%"


def test_capture_pickem_research_observations_chunks_large_key_batches():
    class _ChunkingQuery(_Query):
        def in_(self, key, values):
            assert len(list(values)) <= 200
            return super().in_(key, values)

    class _ChunkingDB(_DB):
        def table(self, name):
            assert name == "pickem_research_observations"
            return _ChunkingQuery(self, name)

    db = _ChunkingDB()
    cards = [
        _card(
            comparison_key=f"evt-{idx}|nikola-jokic|player_points|24.5",
            event_id=f"evt-{idx}",
        )
        for idx in range(205)
    ]

    summary = capture_pickem_research_observations(
        db,
        cards=cards,
        source="cron_board_drop",
        captured_at="2026-04-01T15:30:00Z",
    )

    assert summary == {"eligible_seen": 205, "inserted": 205, "updated": 0}
    assert len(db.tables["pickem_research_observations"]) == 205


def test_update_pickem_research_close_snapshots_populates_latest_and_close_metrics(monkeypatch):
    db = _DB(
        rows=[
            {
                "id": "pickem-1",
                "observation_key": "board_pickem_consensus|2026-04-01|evt-1|over",
                "sport": "basketball_nba",
                "commence_time": "2026-04-02T01:00:00Z",
                "event_id": "evt-1",
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "first_fair_odds_american": -203.0,
                "last_fair_odds_american": -203.0,
                "close_reference_odds": None,
                "close_captured_at": None,
            }
        ]
    )

    monkeypatch.setattr(
        "services.clv_tracking.build_prop_reference_snapshots",
        lambda _sides: ({"evt-1": {}}, {}),
    )
    monkeypatch.setattr(
        "services.clv_tracking.build_prop_reference_pair_snapshots",
        lambda _sides: ({"evt-1": {}}, {}),
    )
    monkeypatch.setattr(
        "services.clv_tracking.lookup_prop_reference_odds",
        lambda **_kwargs: -110.0,
    )
    monkeypatch.setattr(
        "services.clv_tracking.lookup_prop_opposing_reference_odds",
        lambda **_kwargs: -110.0,
    )
    monkeypatch.setattr(
        "services.clv_tracking.should_capture_close_snapshot",
        lambda *_args, **_kwargs: True,
    )

    updated = update_pickem_research_close_snapshots(
        db,
        sides=[{"sport": "basketball_nba"}],
        allow_close=True,
    )

    assert updated["latest_updated"] == 1
    assert updated["close_updated"] == 1
    row = db.tables["pickem_research_observations"][0]
    assert row["latest_reference_odds"] == -110.0
    assert row["close_reference_odds"] == -110.0
    assert row["close_opposing_reference_odds"] == -110.0
    assert row["close_quality"] == "paired"
    assert row["close_true_prob"] is not None
    assert row["close_edge_pct"] is not None


def test_get_pickem_research_summary_builds_bucketed_validation_metrics():
    db = _DB(
        rows=[
            {
                "observation_key": "board_pickem_consensus|2026-04-01|evt-1|over",
                "comparison_key": "evt-1|jokic|player_points|24.5",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "commence_time": "2026-04-02T01:00:00Z",
                "market": "player_points",
                "market_key": "player_points",
                "event_id": "evt-1",
                "player_name": "Nikola Jokic",
                "team": "Denver Nuggets",
                "opponent": "Phoenix Suns",
                "selection_side": "over",
                "line_value": 24.5,
                "calibration_bucket": "65-70%",
                "first_source": "cron_board_drop",
                "last_source": "cron_board_drop",
                "surfaced_count": 1,
                "first_seen_at": "2026-04-01T15:30:00Z",
                "last_seen_at": "2026-04-01T15:30:00Z",
                "first_display_probability": 0.67,
                "last_display_probability": 0.67,
                "first_fair_odds_american": -203.0,
                "last_fair_odds_american": -203.0,
                "first_books_matched_count": 3,
                "last_books_matched_count": 3,
                "first_confidence_label": "high",
                "last_confidence_label": "high",
                "ev_basis": "best_market_price",
                "first_selected_sportsbook": "FanDuel",
                "last_selected_sportsbook": "FanDuel",
                "first_selected_market_odds": 105.0,
                "last_selected_market_odds": 105.0,
                "first_projected_edge_pct": 4.0,
                "last_projected_edge_pct": 4.0,
                "close_true_prob": 0.64,
                "close_quality": "paired",
                "close_captured_at": "2026-04-01T23:40:00Z",
                "close_edge_pct": -1.2,
                "actual_result": "win",
                "settled_at": "2026-04-02T05:00:00Z",
            },
            {
                "observation_key": "board_pickem_consensus|2026-04-01|evt-2|over",
                "comparison_key": "evt-2|booker|player_points|27.5",
                "sport": "basketball_nba",
                "event": "Suns @ Lakers",
                "commence_time": "2026-04-02T03:00:00Z",
                "market": "player_points",
                "market_key": "player_points",
                "event_id": "evt-2",
                "player_name": "Devin Booker",
                "team": "Phoenix Suns",
                "opponent": "Los Angeles Lakers",
                "selection_side": "over",
                "line_value": 27.5,
                "calibration_bucket": "60-65%",
                "first_source": "cron_board_drop",
                "last_source": "cron_board_drop",
                "surfaced_count": 1,
                "first_seen_at": "2026-04-01T15:45:00Z",
                "last_seen_at": "2026-04-01T15:45:00Z",
                "first_display_probability": 0.62,
                "last_display_probability": 0.62,
                "first_fair_odds_american": -163.0,
                "last_fair_odds_american": -163.0,
                "first_books_matched_count": 2,
                "last_books_matched_count": 2,
                "first_confidence_label": "solid",
                "last_confidence_label": "solid",
                "ev_basis": "unpriced",
                "first_selected_sportsbook": None,
                "last_selected_sportsbook": None,
                "first_selected_market_odds": None,
                "last_selected_market_odds": None,
                "first_projected_edge_pct": None,
                "last_projected_edge_pct": None,
                "close_true_prob": 0.59,
                "close_quality": "paired",
                "close_captured_at": "2026-04-02T01:20:00Z",
                "close_edge_pct": -0.8,
                "actual_result": None,
                "settled_at": None,
            },
        ]
    )

    summary = get_pickem_research_summary(db)

    assert summary.captured_count == 2
    assert summary.close_ready_count == 2
    assert summary.settled_count == 1
    assert summary.decisive_count == 1
    assert summary.pending_result_count == 1
    assert summary.auto_settle_pending_count == 1
    assert summary.manual_result_count == 0
    assert summary.manual_only_sports == []
    assert summary.expected_hit_rate_pct == 67.0
    assert summary.actual_hit_rate_pct == 100.0
    assert [item.key for item in summary.by_probability_bucket] == ["60-65%", "65-70%"]
    assert summary.by_market[0].key == "player_points"
    assert summary.by_books_matched[0].key == "2 books"
    assert summary.by_ev_basis[0].key in {"best_market_price", "unpriced"}
    assert summary.recent_observations[0].comparison_key == "evt-2|booker|player_points|27.5"


def test_get_pickem_research_summary_counts_supported_mlb_rows_as_auto_settle_pending():
    db = _DB(
        rows=[
            {
                "observation_key": "board_pickem_consensus|2026-04-01|evt-mlb|over",
                "comparison_key": "evt-mlb|betts|batter_hits|1.5",
                "sport": "baseball_mlb",
                "event": "Padres @ Dodgers",
                "commence_time": "2026-04-02T03:00:00Z",
                "market": "batter_hits",
                "market_key": "batter_hits",
                "event_id": "evt-mlb",
                "player_name": "Mookie Betts",
                "team": "Los Angeles Dodgers",
                "opponent": "San Diego Padres",
                "selection_side": "over",
                "line_value": 1.5,
                "calibration_bucket": "60-65%",
                "first_source": "cron_board_drop",
                "last_source": "cron_board_drop",
                "surfaced_count": 1,
                "first_seen_at": "2026-04-01T15:45:00Z",
                "last_seen_at": "2026-04-01T15:45:00Z",
                "first_display_probability": 0.62,
                "last_display_probability": 0.62,
                "first_fair_odds_american": -163.0,
                "last_fair_odds_american": -163.0,
                "first_books_matched_count": 2,
                "last_books_matched_count": 2,
                "first_confidence_label": "solid",
                "last_confidence_label": "solid",
                "ev_basis": "best_market_price",
                "first_selected_sportsbook": "DraftKings",
                "last_selected_sportsbook": "DraftKings",
                "first_selected_market_odds": -110.0,
                "last_selected_market_odds": -110.0,
                "first_projected_edge_pct": 2.4,
                "last_projected_edge_pct": 2.4,
                "close_true_prob": 0.61,
                "close_quality": "paired",
                "close_captured_at": "2026-04-02T01:20:00Z",
                "close_edge_pct": -0.3,
                "actual_result": None,
                "settled_at": None,
            },
        ]
    )

    summary = get_pickem_research_summary(db)

    assert summary.pending_result_count == 1
    assert summary.auto_settle_pending_count == 1
    assert summary.manual_result_count == 0
    assert summary.manual_only_sports == []


def test_get_pickem_research_summary_still_flags_unsupported_mlb_markets_as_manual_only():
    db = _DB(
        rows=[
            {
                "observation_key": "board_pickem_consensus|2026-04-01|evt-mlb|over",
                "comparison_key": "evt-mlb|betts|batter_walks|0.5",
                "sport": "baseball_mlb",
                "event": "Padres @ Dodgers",
                "commence_time": "2026-04-02T03:00:00Z",
                "market": "batter_walks",
                "market_key": "batter_walks",
                "event_id": "evt-mlb",
                "player_name": "Mookie Betts",
                "team": "Los Angeles Dodgers",
                "opponent": "San Diego Padres",
                "selection_side": "over",
                "line_value": 0.5,
                "calibration_bucket": "60-65%",
                "first_source": "cron_board_drop",
                "last_source": "cron_board_drop",
                "surfaced_count": 1,
                "first_seen_at": "2026-04-01T15:45:00Z",
                "last_seen_at": "2026-04-01T15:45:00Z",
                "first_display_probability": 0.62,
                "last_display_probability": 0.62,
                "first_fair_odds_american": -163.0,
                "last_fair_odds_american": -163.0,
                "first_books_matched_count": 2,
                "last_books_matched_count": 2,
                "first_confidence_label": "solid",
                "last_confidence_label": "solid",
                "ev_basis": "best_market_price",
                "first_selected_sportsbook": "DraftKings",
                "last_selected_sportsbook": "DraftKings",
                "first_selected_market_odds": -110.0,
                "last_selected_market_odds": -110.0,
                "first_projected_edge_pct": 2.4,
                "last_projected_edge_pct": 2.4,
                "close_true_prob": 0.61,
                "close_quality": "paired",
                "close_captured_at": "2026-04-02T01:20:00Z",
                "close_edge_pct": -0.3,
                "actual_result": None,
                "settled_at": None,
            },
        ]
    )

    summary = get_pickem_research_summary(db)

    assert summary.pending_result_count == 1
    assert summary.auto_settle_pending_count == 0
    assert summary.manual_result_count == 1
    assert summary.manual_only_sports == ["baseball_mlb"]


def test_settle_pickem_research_observations_grades_nba_rows(monkeypatch):
    db = _DB(
        rows=[
            {
                "id": "pickem-1",
                "sport": "basketball_nba",
                "event_id": "evt-1",
                "commence_time": "2026-03-31T01:00:00Z",
                "team": "Denver Nuggets",
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "line_value": 24.5,
                "selection_side": "over",
                "actual_result": None,
            }
        ]
    )

    monkeypatch.setattr(
        "services.odds_api._select_completed_event_for_bet",
        lambda _bet, completed_events: (completed_events[0], "matched"),
    )
    async def _fake_fetch_boxscore_provider_events_for_rows(*_args, **_kwargs):
        return {"basketball_nba": []}
    monkeypatch.setattr(
        "services.prop_settler.fetch_boxscore_provider_events_for_rows",
        _fake_fetch_boxscore_provider_events_for_rows,
    )
    async def _fake_resolve_boxscore_event_id(*_args, **_kwargs):
        return types.SimpleNamespace(provider_event_id="espn-1")
    monkeypatch.setattr("services.prop_settler.resolve_boxscore_event_id", _fake_resolve_boxscore_event_id)
    async def _fake_fetch_boxscore_summary(_sport, _provider_event_id):
        return {"boxscore": True}
    monkeypatch.setattr("services.prop_settler.fetch_boxscore_summary", _fake_fetch_boxscore_summary)
    monkeypatch.setattr(
        "services.prop_settler.build_player_stat_map",
        lambda _summary, sport="basketball_nba": {"Nikola Jokic": {"PTS": 31}},
    )
    monkeypatch.setattr("services.prop_settler.grade_prop", lambda *_args, **_kwargs: ("win", {"player_match": "exact"}))

    settled, skipped = asyncio.run(
        settle_pickem_research_observations(
            db,
            {"basketball_nba": [{"id": "evt-1", "home_team": "Phoenix Suns", "away_team": "Denver Nuggets"}]},
            "2026-04-01T12:00:00Z",
            source="auto_settle",
        )
    )

    assert settled == 1
    assert skipped["db_update_failed"] == 0
    row = db.tables["pickem_research_observations"][0]
    assert row["actual_result"] == "win"
    assert row["settled_at"] == "2026-04-01T12:00:00Z"


def test_settle_pickem_research_observations_marks_unsupported_mlb_rows_manual_only():
    db = _DB(
        rows=[
            {
                "id": "pickem-mlb-1",
                "sport": "baseball_mlb",
                "event_id": "evt-mlb-1",
                "commence_time": "2026-03-31T01:00:00Z",
                "team": "Los Angeles Dodgers",
                "player_name": "Mookie Betts",
                "market_key": "batter_walks",
                "line_value": 0.5,
                "selection_side": "over",
                "actual_result": None,
            }
        ]
    )

    settled, skipped = asyncio.run(
        settle_pickem_research_observations(
            db,
            {"baseball_mlb": [{"id": "evt-mlb-1", "home_team": "Los Angeles Dodgers", "away_team": "San Diego Padres"}]},
            "2026-04-01T12:00:00Z",
            source="auto_settle",
        )
    )

    assert settled == 0
    assert skipped["manual_settlement_required"] == 1
    assert skipped["unsupported_sport"] == 0
    row = db.tables["pickem_research_observations"][0]
    assert row["actual_result"] is None
    assert row.get("settled_at") is None


def test_settle_pickem_research_observations_grades_supported_mlb_rows(monkeypatch):
    db = _DB(
        rows=[
            {
                "id": "pickem-mlb-1",
                "sport": "baseball_mlb",
                "event_id": "evt-mlb-1",
                "commence_time": "2026-03-31T01:00:00Z",
                "team": "Los Angeles Dodgers",
                "player_name": "Mookie Betts",
                "market_key": "batter_hits",
                "line_value": 1.5,
                "selection_side": "over",
                "actual_result": None,
            }
        ]
    )

    monkeypatch.setattr(
        "services.odds_api._select_completed_event_for_bet",
        lambda _bet, completed_events: (completed_events[0], "matched"),
    )
    async def _fake_fetch_boxscore_provider_events_for_rows(*_args, **_kwargs):
        return {"baseball_mlb": []}
    monkeypatch.setattr(
        "services.prop_settler.fetch_boxscore_provider_events_for_rows",
        _fake_fetch_boxscore_provider_events_for_rows,
    )
    async def _fake_resolve_boxscore_event_id(*_args, **_kwargs):
        return types.SimpleNamespace(provider_event_id="mlb-1")
    monkeypatch.setattr("services.prop_settler.resolve_boxscore_event_id", _fake_resolve_boxscore_event_id)
    async def _fake_fetch_boxscore_summary(_sport, _provider_event_id):
        return {"teams": True}
    monkeypatch.setattr("services.prop_settler.fetch_boxscore_summary", _fake_fetch_boxscore_summary)
    monkeypatch.setattr(
        "services.prop_settler.build_player_stat_map",
        lambda _summary, sport="baseball_mlb": {"Mookie Betts": {"B_H": 2}},
    )
    monkeypatch.setattr("services.prop_settler.grade_prop", lambda *_args, **_kwargs: ("win", {"player_match": "exact"}))

    settled, skipped = asyncio.run(
        settle_pickem_research_observations(
            db,
            {"baseball_mlb": [{"id": "evt-mlb-1", "home_team": "Los Angeles Dodgers", "away_team": "San Diego Padres"}]},
            "2026-04-01T12:00:00Z",
            source="auto_settle",
        )
    )

    assert settled == 1
    assert skipped["db_update_failed"] == 0
    assert skipped["manual_settlement_required"] == 0
    row = db.tables["pickem_research_observations"][0]
    assert row["actual_result"] == "win"
    assert row["settled_at"] == "2026-04-01T12:00:00Z"
