from services.paper_autolog_runner import execute_longshot_autolog


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db):
        self._db = db
        self._eq_filters = []
        self._in_filters = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq_filters.append((field, value))
        return self

    def in_(self, field, values):
        self._in_filters.append((field, set(values)))
        return self

    def limit(self, _n):
        return self

    def insert(self, payload):
        self._db.rows.append(dict(payload))
        return self

    def execute(self):
        rows = list(self._db.rows)
        for field, value in self._eq_filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self._in_filters:
            rows = [r for r in rows if r.get(field) in values]
        return _Result(rows)


class _DB:
    def __init__(self):
        self.rows = []

    def table(self, name):
        assert name == "bets"
        return _Query(self)


def test_execute_longshot_autolog_runs_end_to_end_with_caps_and_summary():
    db = _DB()
    sides = [
        {
            "sport": "basketball_nba",
            "ev_percentage": 1.0,
            "book_odds": 110,
            "commence_time": "2026-03-19T20:00:00Z",
            "team": "A",
            "sportsbook": "DraftKings",
            "pinnacle_odds": 100,
            "true_prob": 0.5,
        },
        {
            "sport": "basketball_ncaab",
            "ev_percentage": 12.0,
            "book_odds": 700,
            "commence_time": "2026-03-19T21:00:00Z",
            "team": "B",
            "sportsbook": "FanDuel",
            "pinnacle_odds": 650,
            "true_prob": 0.2,
        },
    ]

    out = execute_longshot_autolog(
        db=db,
        run_id="run-1",
        user_id="u1",
        sides=sides,
        supported_sports={"basketball_nba", "basketball_ncaab"},
        low_edge_cohort="low",
        high_edge_cohort="high",
        low_edge_ev_min=0.5,
        low_edge_ev_max=1.5,
        low_edge_odds_min=-200,
        low_edge_odds_max=300,
        high_edge_ev_min=10.0,
        high_edge_odds_min=700,
        max_total=5,
        max_low=2,
        max_high=3,
        paper_stake=10.0,
        pending_result_value="pending",
        now_iso="2026-03-19T00:00:00Z",
        today_iso="2026-03-19",
    )

    assert out["run_id"] == "run-1"
    assert out["eligible_seen"] == 2
    assert out["inserted_total"] == 2
    assert out["inserted_by_cohort"] == {"low": 1, "high": 1}
    assert len(db.rows) == 2
