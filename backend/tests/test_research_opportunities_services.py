from services.research_opportunities import (
    capture_scan_opportunities,
    get_research_opportunities_summary,
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
                row["id"] = f"opp-{self._db._next_id}"
                self._db._next_id += 1
            rows.append(row)
            inserted.append(row)
        return _Resp(inserted)


class _DB:
    def __init__(self, rows=None, *, missing_table=False):
        self.tables = {"scan_opportunities": list(rows or [])}
        self._next_id = len(self.tables["scan_opportunities"]) + 1
        self._missing_table = missing_table

    def table(self, name):
        assert name == "scan_opportunities"
        if self._missing_table:
            raise RuntimeError("PGRST205 scan_opportunities schema cache stale")
        return _Query(self, name)


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


def test_capture_scan_opportunities_inserts_only_positive_ev_straight_ml_sides():
    db = _DB()

    out = capture_scan_opportunities(
        db,
        sides=[
            _side(),
            _side(event_id="evt-neg", team="Away", ev_percentage=0),
            _side(event_id="evt-prop", surface="player_props", team="Prop Player"),
            _side(event_id="evt-spread", market_key="spreads", team="Spread Side"),
        ],
        source="manual_scan",
        captured_at="2026-03-23T18:00:00Z",
    )

    assert out == {"eligible_seen": 1, "inserted": 1, "updated": 0}
    assert len(db.tables["scan_opportunities"]) == 1

    row = db.tables["scan_opportunities"][0]
    assert row["opportunity_key"] == "straight_bets|basketball_nba|id:evt-1|ml|home|draftkings"
    assert row["market"] == "ML"
    assert row["first_source"] == "manual_scan"
    assert row["seen_count"] == 1
    assert row["latest_reference_odds"] == -120.0


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
                "first_seen_at": "2026-03-23T18:05:00Z",
                "last_seen_at": "2026-03-23T18:07:00Z",
                "commence_time": "2026-03-23T20:00:00Z",
                "sport": "basketball_nba",
                "event": "Away @ Home",
                "team": "Home",
                "sportsbook": "DraftKings",
                "market": "ML",
                "event_id": "evt-1",
                "first_source": "manual_scan",
                "last_source": "manual_scan",
                "seen_count": 1,
                "first_ev_percentage": 0.75,
                "first_book_odds": 140,
                "best_book_odds": 150,
                "latest_reference_odds": 120,
                "reference_odds_at_close": 115,
                "clv_ev_percent": 1.2,
                "beat_close": True,
            },
            {
                "opportunity_key": "opp-2",
                "first_seen_at": "2026-03-23T18:10:00Z",
                "last_seen_at": "2026-03-23T18:12:00Z",
                "commence_time": "2026-03-23T21:00:00Z",
                "sport": "basketball_nba",
                "event": "Road @ Favorite",
                "team": "Road",
                "sportsbook": "FanDuel",
                "market": "ML",
                "event_id": "evt-2",
                "first_source": "scheduled_scan",
                "last_source": "scheduled_scan",
                "seen_count": 2,
                "first_ev_percentage": 2.6,
                "first_book_odds": 320,
                "best_book_odds": 340,
                "latest_reference_odds": 290,
                "reference_odds_at_close": 300,
                "clv_ev_percent": -0.4,
                "beat_close": False,
            },
            {
                "opportunity_key": "opp-3",
                "first_seen_at": "2026-03-23T18:20:00Z",
                "last_seen_at": "2026-03-23T18:21:00Z",
                "commence_time": "2026-03-23T22:00:00Z",
                "sport": "basketball_ncaab",
                "event": "Dog @ Favorite",
                "team": "Dog",
                "sportsbook": "DraftKings",
                "market": "ML",
                "event_id": "evt-3",
                "first_source": "ops_trigger_scan",
                "last_source": "ops_trigger_scan",
                "seen_count": 1,
                "first_ev_percentage": 4.5,
                "first_book_odds": 550,
                "best_book_odds": 550,
                "latest_reference_odds": 500,
                "reference_odds_at_close": None,
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
    assert summary.beat_close_pct == 50.0
    assert summary.avg_clv_percent == 0.4

    assert [item.key for item in summary.by_source] == ["manual_scan", "scheduled_scan", "ops_trigger_scan"]
    assert summary.by_source[0].captured_count == 1
    assert [item.key for item in summary.by_edge_bucket] == ["0.5-1%", "2-4%", "4%+"]
    assert [item.key for item in summary.by_odds_bucket] == ["<= +150", "+301 to +500", "+501+"]

    assert summary.recent_opportunities[0].opportunity_key == "opp-3"
    assert summary.recent_opportunities[0].first_source == "ops_trigger_scan"
    assert summary.recent_opportunities[1].beat_close is False


def test_get_research_opportunities_summary_returns_empty_when_table_missing():
    summary = get_research_opportunities_summary(_DB(missing_table=True))

    assert summary.captured_count == 0
    assert summary.open_count == 0
    assert summary.close_captured_count == 0
    assert summary.recent_opportunities == []
