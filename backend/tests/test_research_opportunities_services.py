from services.research_opportunities import (
    capture_scan_opportunities,
    get_research_opportunities_summary,
    is_missing_scan_opportunities_column_error,
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
        self._fields = ""
        self._order_by: list[tuple[str, bool]] = []
        self._range: tuple[int, int] | None = None

    def select(self, fields):
        self._fields = str(fields or "")
        return self

    def order(self, key, desc=False):
        self._order_by.append((key, bool(desc)))
        return self

    def range(self, start, end):
        self._range = (int(start), int(end))
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
        if (
            self._mode == "select"
            and self._table_name == "scan_opportunities"
            and self._db._missing_model_key_columns
            and ("first_model_key" in self._fields or "last_model_key" in self._fields)
        ):
            raise RuntimeError("column scan_opportunities.first_model_key does not exist")
        rows = self._db.tables[self._table_name]
        matched = [row for row in rows if all(predicate(row) for predicate in self._filters)]

        if self._mode == "select":
            for key, desc in reversed(self._order_by):
                matched.sort(key=lambda row: row.get(key), reverse=desc)
            if self._range is None:
                matched = matched[:1000]
            else:
                start, end = self._range
                matched = matched[start:end + 1]
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
    def __init__(self, rows=None, *, missing_table=False, missing_model_key_columns=False):
        self.tables = {
            "scan_opportunities": list(rows or []),
            "scan_opportunity_model_evaluations": [],
        }
        self._next_id = len(self.tables["scan_opportunities"]) + 1
        self._missing_table = missing_table
        self._missing_model_key_columns = missing_model_key_columns

    def table(self, name):
        assert name in {"scan_opportunities", "scan_opportunity_model_evaluations"}
        if self._missing_table and name == "scan_opportunities":
            raise RuntimeError("PGRST205 scan_opportunities schema cache stale")
        return _Query(self, name)


class _PostgrestLikeColumnError(Exception):
    def __init__(self, message: str, *, code: str = "42703"):
        super().__init__(message)
        self.message = message
        self.code = code


def _side(
    *,
    event_id="evt-1",
    surface="straight_bets",
    market_key="h2h",
    sportsbook="DraftKings",
    sport="basketball_nba",
    event="Away @ Home",
    commence_time="2026-03-23T20:00:00Z",
    team="Home",
    pinnacle_odds=-120,
    book_odds=150,
    ev_percentage=2.5,
):
    return {
        "event_id": event_id,
        "surface": surface,
        "market_key": market_key,
        "sportsbook": sportsbook,
        "sport": sport,
        "event": event,
        "commence_time": commence_time,
        "team": team,
        "pinnacle_odds": pinnacle_odds,
        "book_odds": book_odds,
        "ev_percentage": ev_percentage,
    }


def _prop_side(
    *,
    event_id="evt-prop-1",
    sportsbook="FanDuel",
    sport="basketball_nba",
    event="Nuggets @ Suns",
    commence_time="2026-03-23T20:00:00Z",
    market_key="player_points",
    market="player_points",
    player_name="Nikola Jokic",
    team="Denver Nuggets",
    selection_side="over",
    line_value=24.5,
    reference_odds=-108,
    book_odds=105,
    true_prob=0.5192,
    ev_percentage=6.6,
):
    return {
        "event_id": event_id,
        "surface": "player_props",
        "market_key": market_key,
        "sportsbook": sportsbook,
        "sport": sport,
        "event": event,
        "commence_time": commence_time,
        "market": market,
        "player_name": player_name,
        "team": team,
        "selection_side": selection_side,
        "line_value": line_value,
        "reference_odds": reference_odds,
        "book_odds": book_odds,
        "true_prob": true_prob,
        "ev_percentage": ev_percentage,
    }


def test_capture_scan_opportunities_inserts_positive_ev_straight_and_prop_sides():
    db = _DB()

    out = capture_scan_opportunities(
        db,
        sides=[
            _side(),
            _side(event_id="evt-neg", team="Away", ev_percentage=0),
            _prop_side(),
            _side(event_id="evt-spread", market_key="spreads", team="Spread Side"),
        ],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )

    assert out == {"eligible_seen": 2, "inserted": 2, "updated": 0}
    assert len(db.tables["scan_opportunities"]) == 2

    straight_row = next(row for row in db.tables["scan_opportunities"] if row["surface"] == "straight_bets")
    assert straight_row["opportunity_key"] == "straight_bets|basketball_nba|id:evt-1|ml|home|draftkings"
    assert straight_row["market"] == "ML"
    assert straight_row["first_source"] == "manual_scan"
    assert straight_row["first_model_key"] == "straight_h2h_live"
    assert straight_row["seen_count"] == 1
    assert straight_row["latest_reference_odds"] == -120.0

    prop_row = next(row for row in db.tables["scan_opportunities"] if row["surface"] == "player_props")
    assert prop_row["opportunity_key"] == "player_props|basketball_nba|id:evt-prop-1|player_points|nikola jokic|over|24.5|fanduel"
    assert prop_row["market"] == "player_points"
    assert prop_row["player_name"] == "Nikola Jokic"
    assert prop_row["source_market_key"] == "player_points"
    assert prop_row["selection_side"] == "over"
    assert prop_row["line_value"] == 24.5
    assert prop_row["first_model_key"] == "props_v1_live"
    assert prop_row["latest_reference_odds"] == -108.0
    assert len(db.tables["scan_opportunity_model_evaluations"]) == 1
    evaluation_row = db.tables["scan_opportunity_model_evaluations"][0]
    assert evaluation_row["opportunity_key"] == prop_row["opportunity_key"]
    assert evaluation_row["model_key"] == "props_v1_live"
    assert evaluation_row["capture_role"] == "live"
    assert evaluation_row["first_interpolation_mode"] == "exact"


def test_capture_scan_opportunities_updates_last_and_best_without_overwriting_first_fields():
    db = _DB()

    first = capture_scan_opportunities(
        db,
        sides=[_side(book_odds=150, pinnacle_odds=130, ev_percentage=1.5)],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )
    second = capture_scan_opportunities(
        db,
        sides=[_side(book_odds=170, pinnacle_odds=140, ev_percentage=3.25)],
        source="scheduled_scan",
        captured_at="2026-03-23T18:10:00Z",
    )
    third = capture_scan_opportunities(
        db,
        sides=[_side(book_odds=140, pinnacle_odds=120, ev_percentage=1.0)],
        source="ops_trigger_scan",
        captured_at="2026-03-23T18:20:00Z",
    )

    assert first == {"eligible_seen": 1, "inserted": 1, "updated": 0}
    assert second == {"eligible_seen": 1, "inserted": 0, "updated": 1}
    assert third == {"eligible_seen": 1, "inserted": 0, "updated": 1}

    row = db.tables["scan_opportunities"][0]
    assert row["first_source"] == "manual_scan"
    assert row["first_seen_at"] == "2026-03-23T18:00:00Z"
    assert row["first_book_odds"] == 150.0
    assert row["first_model_key"] == "straight_h2h_live"
    assert row["last_model_key"] == "straight_h2h_live"
    assert row["last_source"] == "ops_trigger_scan"
    assert row["last_seen_at"] == "2026-03-23T18:20:00Z"
    assert row["last_book_odds"] == 140.0
    assert row["last_reference_odds"] == 120.0
    assert row["seen_count"] == 3
    assert row["best_book_odds"] == 170.0
    assert row["best_reference_odds"] == 140.0
    assert row["best_ev_percentage"] == 3.25
    assert row["best_seen_at"] == "2026-03-23T18:10:00Z"
    assert row["latest_reference_odds"] == 120.0


def test_capture_scan_opportunities_writes_live_and_shadow_prop_model_evaluations():
    db = _DB()
    side = _prop_side()
    side["active_model_key"] = "props_v1_live"
    side["model_evaluations"] = [
        {
            "model_key": "props_v1_live",
            "reference_source": "market_weighted_consensus",
            "reference_odds": -108,
            "true_prob": 0.5192,
            "raw_true_prob": 0.5192,
            "reference_bookmakers": ["bovada", "betonlineag"],
            "reference_bookmaker_count": 2,
            "filtered_reference_count": 2,
            "exact_reference_count": 2,
            "interpolated_reference_count": 0,
            "interpolation_mode": "exact",
            "reference_inputs_json": "[]",
            "confidence_label": "solid",
            "confidence_score": 0.54,
            "prob_std": 0.011,
            "book_odds": 105,
            "book_decimal": 2.05,
            "ev_percentage": 6.6,
            "base_kelly_fraction": 0.03,
            "shrink_factor": 0.0,
            "sportsbook_key": "fanduel",
            "market_key": "player_points",
        },
        {
            "model_key": "props_v2_shadow",
            "reference_source": "market_logit_consensus_v2",
            "reference_odds": -111,
            "true_prob": 0.5263,
            "raw_true_prob": 0.5321,
            "reference_bookmakers": ["bovada", "betonlineag", "betmgm"],
            "reference_bookmaker_count": 3,
            "filtered_reference_count": 3,
            "exact_reference_count": 2,
            "interpolated_reference_count": 1,
            "interpolation_mode": "mixed",
            "reference_inputs_json": "[{}]",
            "confidence_label": "high",
            "confidence_score": 0.71,
            "prob_std": 0.008,
            "book_odds": 105,
            "book_decimal": 2.05,
            "ev_percentage": 8.1,
            "base_kelly_fraction": 0.04,
            "shrink_factor": 0.12,
            "sportsbook_key": "fanduel",
            "market_key": "player_points",
        },
    ]

    out = capture_scan_opportunities(
        db,
        sides=[side],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )

    assert out == {"eligible_seen": 1, "inserted": 1, "updated": 0}
    assert len(db.tables["scan_opportunity_model_evaluations"]) == 2
    roles = {row["model_key"]: row["capture_role"] for row in db.tables["scan_opportunity_model_evaluations"]}
    assert roles == {
        "props_v1_live": "live",
        "props_v2_shadow": "shadow",
    }
    shadow = next(row for row in db.tables["scan_opportunity_model_evaluations"] if row["model_key"] == "props_v2_shadow")
    assert shadow["first_interpolation_mode"] == "mixed"
    assert shadow["first_shrink_factor"] == 0.12
    assert shadow["first_reference_bookmaker_count"] == 3


def test_capture_scan_opportunities_uses_commence_time_fallback_when_event_id_missing():
    db = _DB()

    capture_scan_opportunities(
        db,
        sides=[_side(event_id=None, commence_time="2026-03-23T22:00:00Z", team="Away")],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )

    row = db.tables["scan_opportunities"][0]
    assert row["opportunity_key"] == "straight_bets|basketball_nba|time:2026-03-23T22:00:00Z|ml|away|draftkings"
    assert row["event_id"] is None


def test_capture_scan_opportunities_uses_exact_line_prop_identity_for_keying():
    db = _DB()

    first = capture_scan_opportunities(
        db,
        sides=[_prop_side(line_value=24.5, selection_side="over")],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )
    second = capture_scan_opportunities(
        db,
        sides=[
            _prop_side(line_value=25.5, selection_side="over"),
            _prop_side(line_value=24.5, selection_side="under"),
            _prop_side(line_value=24.5, selection_side="over", market_key="player_rebounds", market="player_rebounds"),
        ],
        source="scheduled_scan",
        captured_at="2026-03-23T18:10:00Z",
    )

    assert first == {"eligible_seen": 1, "inserted": 1, "updated": 0}
    assert second == {"eligible_seen": 3, "inserted": 3, "updated": 0}
    assert len(db.tables["scan_opportunities"]) == 4


def test_capture_scan_opportunities_rejects_props_missing_exact_line_identity_fields():
    db = _DB()

    out = capture_scan_opportunities(
        db,
        sides=[
            _prop_side(player_name=""),
            _prop_side(market_key="", market=""),
            _prop_side(selection_side=""),
            _prop_side(line_value=None),
            _prop_side(reference_odds=None),
        ],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )

    assert out == {"eligible_seen": 0, "inserted": 0, "updated": 0}
    assert db.tables["scan_opportunities"] == []


def test_capture_scan_opportunities_dedupes_repeated_keys_within_one_batch():
    db = _DB()

    out = capture_scan_opportunities(
        db,
        sides=[
            _side(book_odds=140, pinnacle_odds=120, ev_percentage=1.1),
            _side(book_odds=180, pinnacle_odds=145, ev_percentage=3.5),
            _side(book_odds=160, pinnacle_odds=130, ev_percentage=2.0),
        ],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )

    assert out == {"eligible_seen": 3, "inserted": 1, "updated": 0}
    row = db.tables["scan_opportunities"][0]
    assert row["seen_count"] == 1
    assert row["last_book_odds"] == 160.0
    assert row["last_reference_odds"] == 130.0
    assert row["best_book_odds"] == 180.0
    assert row["best_reference_odds"] == 145.0
    assert row["best_ev_percentage"] == 3.5


def test_get_research_opportunities_summary_aggregates_breakdowns_and_recent_rows():
    db = _DB(
        rows=[
            {
                "opportunity_key": "opp-1",
                "surface": "straight_bets",
                "first_seen_at": "2026-03-23T18:05:00Z",
                "last_seen_at": "2026-03-23T18:07:00Z",
                "commence_time": "2026-03-23T20:00:00Z",
                "sport": "basketball_nba",
                "event": "Away @ Home",
                "team": "Home",
                "sportsbook": "DraftKings",
                "market": "ML",
                "source_market_key": "h2h",
                "event_id": "evt-1",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 0.75,
                "first_book_odds": 140,
                "best_book_odds": 150,
                "latest_reference_odds": 120,
                "reference_odds_at_close": 115,
                "close_captured_at": "2026-03-23T19:45:00Z",
                "clv_ev_percent": 1.2,
                "beat_close": True,
            },
            {
                "opportunity_key": "opp-2",
                "surface": "player_props",
                "first_seen_at": "2026-03-23T18:10:00Z",
                "last_seen_at": "2026-03-23T18:12:00Z",
                "commence_time": "2026-03-23T21:00:00Z",
                "sport": "basketball_nba",
                "event": "Road @ Favorite",
                "team": "Pacers",
                "sportsbook": "FanDuel",
                "market": "player_points",
                "event_id": "evt-2",
                "player_name": "Tyrese Haliburton",
                "source_market_key": "player_points",
                "selection_side": "over",
                "line_value": 21.5,
                "first_source": "scheduled_scan",
                "last_source": "scheduled_scan",
                "seen_count": 2,
                "first_ev_percentage": 2.6,
                "first_book_odds": 320,
                "best_book_odds": 340,
                "latest_reference_odds": 290,
                "reference_odds_at_close": 300,
                "close_captured_at": "2026-03-23T20:45:00Z",
                "clv_ev_percent": -0.4,
                "beat_close": False,
            },
            {
                "opportunity_key": "opp-3",
                "surface": "straight_bets",
                "first_seen_at": "2026-03-23T18:20:00Z",
                "last_seen_at": "2026-03-23T18:21:00Z",
                "commence_time": "2026-03-23T22:00:00Z",
                "sport": "basketball_ncaab",
                "event": "Dog @ Favorite",
                "team": "Dog",
                "sportsbook": "DraftKings",
                "market": "ML",
                "source_market_key": "spreads",
                "event_id": "evt-3",
                "first_source": "ops_trigger_scan",
                "last_source": "ops_trigger_scan",
                "seen_count": 1,
                "first_ev_percentage": 4.5,
                "first_book_odds": 550,
                "best_book_odds": 550,
                "latest_reference_odds": 500,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
        ]
    )

    summary = get_research_opportunities_summary(db)

    assert summary.captured_count == 3
    assert summary.open_count == 1
    assert summary.close_captured_count == 2
    assert summary.clv_ready_count == 2
    assert summary.pending_close_count == 1
    assert summary.valid_close_count == 2
    assert summary.invalid_close_count == 0
    assert summary.aggregate_status == "sample_too_small"
    assert summary.suppressed_by_sample_size is True
    assert summary.min_valid_close_threshold == 10
    assert summary.beat_close_pct is None
    assert summary.avg_clv_percent is None

    assert [item.key for item in summary.by_surface] == ["straight_bets", "player_props"]
    assert summary.by_surface[0].captured_count == 2
    assert [item.key for item in summary.by_market] == ["NBA | ML", "NBA | player_points", "NCAAB | Spreads"]
    assert summary.by_market[0].captured_count == 1
    assert [item.key for item in summary.by_source] == [
        "Daily Drop (Scheduled)",
        "Daily Drop (Ops Trigger)",
        "Daily Drop (Manual QA)",
    ]
    assert summary.by_source[0].captured_count == 1
    assert [item.key for item in summary.by_edge_bucket] == ["0.5-1%", "2-4%", "4%+"]
    assert [item.key for item in summary.by_drop_time] == ["First Look", "Daily Drop"]
    assert summary.by_drop_time[0].captured_count == 3
    assert summary.by_drop_time[1].captured_count == 0
    assert [item.key for item in summary.by_event_day] == ["Same day", "Later day", "Unknown"]
    assert summary.by_event_day[0].captured_count == 3
    assert summary.by_event_day[1].captured_count == 0
    assert [item.key for item in summary.by_odds_bucket] == ["<= +150", "+301 to +500", "+501+"]

    assert summary.recent_opportunities[0].opportunity_key == "opp-3"
    assert summary.recent_opportunities[0].first_source == "Daily Drop (Ops Trigger)"
    assert summary.recent_opportunities[1].surface == "player_props"
    assert summary.recent_opportunities[1].player_name == "Tyrese Haliburton"
    assert summary.recent_opportunities[1].selection_side == "over"
    assert summary.recent_opportunities[1].line_value == 21.5
    assert summary.status_buckets[0].status == "pending"
    assert summary.status_buckets[0].count == 1
    assert summary.status_buckets[1].status == "valid"
    assert summary.status_buckets[1].count == 2


def test_get_research_opportunities_summary_pages_past_postgrest_default_limit():
    rows = []
    for idx in range(1004):
        rows.append(
            {
                "opportunity_key": f"opp-{idx:04d}",
                "surface": "player_props" if idx % 2 else "straight_bets",
                "first_seen_at": "2026-03-23T18:05:00Z",
                "last_seen_at": "2026-03-23T18:07:00Z",
                "commence_time": "2026-03-23T20:00:00Z",
                "sport": "basketball_nba",
                "event": "Away @ Home",
                "team": "Home",
                "sportsbook": "DraftKings",
                "market": "player_points" if idx % 2 else "ML",
                "event_id": f"evt-{idx}",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 1.25,
                "first_book_odds": 140,
                "best_book_odds": 150,
                "latest_reference_odds": 120,
                "reference_odds_at_close": 115,
                "close_captured_at": "2026-03-23T19:45:00Z",
                "clv_ev_percent": 1.2,
                "beat_close": True,
            }
        )

    summary = get_research_opportunities_summary(_DB(rows=rows))

    assert summary.captured_count == 1004
    assert summary.valid_close_count == 1004
    assert summary.by_market[0].key == "NBA | ML"
    assert summary.by_market[0].captured_count == 502
    assert [item.key for item in summary.by_drop_time] == ["First Look", "Daily Drop"]
    assert summary.by_drop_time[0].captured_count == 1004


def test_get_research_opportunities_summary_by_market_includes_straight_market_keys_and_sport_tags():
    db = _DB(
        rows=[
            {
                "opportunity_key": "opp-h2h",
                "surface": "straight_bets",
                "first_seen_at": "2026-03-23T18:05:00Z",
                "last_seen_at": "2026-03-23T18:07:00Z",
                "commence_time": "2026-03-23T20:00:00Z",
                "sport": "basketball_nba",
                "event": "Away @ Home",
                "team": "Home",
                "sportsbook": "DraftKings",
                "market": "ML",
                "source_market_key": "h2h",
                "event_id": "evt-1",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 1.5,
                "first_book_odds": 140,
                "best_book_odds": 150,
                "latest_reference_odds": 120,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
            {
                "opportunity_key": "opp-spreads",
                "surface": "straight_bets",
                "first_seen_at": "2026-03-23T18:06:00Z",
                "last_seen_at": "2026-03-23T18:08:00Z",
                "commence_time": "2026-03-23T20:00:00Z",
                "sport": "basketball_nba",
                "event": "Away @ Home",
                "team": "Home",
                "sportsbook": "DraftKings",
                "market": "ML",
                "source_market_key": "spreads",
                "event_id": "evt-1",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 1.8,
                "first_book_odds": 140,
                "best_book_odds": 150,
                "latest_reference_odds": 120,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
            {
                "opportunity_key": "opp-totals",
                "surface": "straight_bets",
                "first_seen_at": "2026-03-23T18:07:00Z",
                "last_seen_at": "2026-03-23T18:09:00Z",
                "commence_time": "2026-03-23T20:00:00Z",
                "sport": "basketball_nba",
                "event": "Away @ Home",
                "team": "Home",
                "sportsbook": "DraftKings",
                "market": "ML",
                "source_market_key": "totals",
                "event_id": "evt-1",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 2.1,
                "first_book_odds": 140,
                "best_book_odds": 150,
                "latest_reference_odds": 120,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
            {
                "opportunity_key": "opp-pk",
                "surface": "player_props",
                "first_seen_at": "2026-03-23T18:10:00Z",
                "last_seen_at": "2026-03-23T18:12:00Z",
                "commence_time": "2026-03-23T21:00:00Z",
                "sport": "baseball_mlb",
                "event": "Road @ Favorite",
                "team": "Yankees",
                "sportsbook": "FanDuel",
                "market": "pitcher_strikeouts",
                "event_id": "evt-2",
                "player_name": "Gerrit Cole",
                "source_market_key": "pitcher_strikeouts",
                "selection_side": "over",
                "line_value": 6.5,
                "first_source": "scheduled_scan",
                "last_source": "scheduled_scan",
                "seen_count": 2,
                "first_ev_percentage": 2.6,
                "first_book_odds": 320,
                "best_book_odds": 340,
                "latest_reference_odds": 290,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
            {
                "opportunity_key": "opp-bk",
                "surface": "player_props",
                "first_seen_at": "2026-03-23T18:11:00Z",
                "last_seen_at": "2026-03-23T18:13:00Z",
                "commence_time": "2026-03-23T21:00:00Z",
                "sport": "baseball_mlb",
                "event": "Road @ Favorite",
                "team": "Yankees",
                "sportsbook": "FanDuel",
                "market": "batter_strikeouts",
                "event_id": "evt-2",
                "player_name": "Aaron Judge",
                "source_market_key": "batter_strikeouts",
                "selection_side": "over",
                "line_value": 1.5,
                "first_source": "scheduled_scan",
                "last_source": "scheduled_scan",
                "seen_count": 2,
                "first_ev_percentage": 2.6,
                "first_book_odds": 320,
                "best_book_odds": 340,
                "latest_reference_odds": 290,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
        ]
    )

    summary = get_research_opportunities_summary(db)

    assert [item.key for item in summary.by_market] == [
        "NBA | ML",
        "NBA | Spreads",
        "NBA | Totals",
        "MLB | batter_strikeouts",
        "MLB | pitcher_strikeouts",
    ]


def test_get_research_opportunities_summary_buckets_events_after_scan_day():
    db = _DB(
        rows=[
            {
                "opportunity_key": "opp-same-day",
                "surface": "straight_bets",
                "first_seen_at": "2026-03-23T18:05:00Z",
                "last_seen_at": "2026-03-23T18:07:00Z",
                "commence_time": "2026-03-24T02:00:00Z",
                "sport": "basketball_nba",
                "event": "Away @ Home",
                "team": "Home",
                "sportsbook": "DraftKings",
                "market": "ML",
                "source_market_key": "h2h",
                "event_id": "evt-same",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 1.5,
                "first_book_odds": 140,
                "best_book_odds": 150,
                "latest_reference_odds": 120,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
            {
                "opportunity_key": "opp-later-day",
                "surface": "straight_bets",
                "first_seen_at": "2026-03-23T18:05:00Z",
                "last_seen_at": "2026-03-23T18:07:00Z",
                "commence_time": "2026-03-25T02:00:00Z",
                "sport": "basketball_nba",
                "event": "Road @ Favorite",
                "team": "Road",
                "sportsbook": "FanDuel",
                "market": "ML",
                "source_market_key": "h2h",
                "event_id": "evt-later",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 2.5,
                "first_book_odds": 160,
                "best_book_odds": 165,
                "latest_reference_odds": 130,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
            {
                "opportunity_key": "opp-unknown",
                "surface": "straight_bets",
                "first_seen_at": None,
                "last_seen_at": "2026-03-23T18:07:00Z",
                "commence_time": "2026-03-25T02:00:00Z",
                "sport": "basketball_nba",
                "event": "Dog @ Favorite",
                "team": "Dog",
                "sportsbook": "Caesars",
                "market": "ML",
                "source_market_key": "h2h",
                "event_id": "evt-unknown",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 3.5,
                "first_book_odds": 180,
                "best_book_odds": 185,
                "latest_reference_odds": 150,
                "reference_odds_at_close": None,
                "close_captured_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
        ]
    )

    summary = get_research_opportunities_summary(db)

    assert [item.key for item in summary.by_event_day] == ["Same day", "Later day", "Unknown"]
    assert [item.captured_count for item in summary.by_event_day] == [1, 1, 1]


def test_get_research_opportunities_summary_returns_empty_when_table_missing():
    summary = get_research_opportunities_summary(_DB(missing_table=True))

    assert summary.captured_count == 0
    assert summary.open_count == 0
    assert summary.close_captured_count == 0
    assert summary.pending_close_count == 0
    assert summary.valid_close_count == 0
    assert summary.invalid_close_count == 0
    assert summary.aggregate_status == "not_captured"
    assert summary.recent_opportunities == []


def test_capture_scan_opportunities_and_summary_work_without_model_key_columns():
    db = _DB(missing_model_key_columns=True)

    capture_scan_opportunities(
        db,
        sides=[_side(), _prop_side()],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )

    assert len(db.tables["scan_opportunities"]) == 2
    assert "first_model_key" not in db.tables["scan_opportunities"][0]
    assert "last_model_key" not in db.tables["scan_opportunities"][0]

    summary = get_research_opportunities_summary(db)

    assert summary.captured_count == 2
    assert summary.aggregate_status in {"pending_close", "not_captured"}


def test_missing_scan_opportunities_column_error_matches_postgrest_apierror_shape():
    err = _PostgrestLikeColumnError("column scan_opportunities.first_model_key does not exist")

    assert is_missing_scan_opportunities_column_error(err, "first_model_key", "last_model_key") is True
