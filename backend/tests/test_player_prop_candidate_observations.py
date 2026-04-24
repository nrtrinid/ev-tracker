from services.player_prop_candidate_observations import (
    PLAYER_PROP_MODEL_CANDIDATE_TABLE,
    capture_player_prop_model_candidate_observations,
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
        if self._mode == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for payload in payloads:
                row = {"id": f"row-{len(rows) + 1}", **payload}
                rows.append(row)
                inserted.append(dict(row))
            return _Resp(inserted)

        matched = [row for row in rows if all(predicate(row) for predicate in self._filters)]
        if self._mode == "select":
            return _Resp([dict(row) for row in matched])

        for row in matched:
            row.update(self._payload)
        return _Resp([])


class _DB:
    def __init__(self):
        self.tables = {PLAYER_PROP_MODEL_CANDIDATE_TABLE: []}

    def table(self, name):
        assert name == PLAYER_PROP_MODEL_CANDIDATE_TABLE
        return _Query(self, name)


def _side(*, ev_percentage: float, true_prob: float = 0.53):
    return {
        "surface": "player_props",
        "sport": "basketball_nba",
        "event": "Nuggets @ Suns",
        "event_id": "evt-1",
        "commence_time": "2026-04-01T02:00:00Z",
        "sportsbook": "FanDuel",
        "sportsbook_key": "fanduel",
        "market": "player_points",
        "market_key": "player_points",
        "player_name": "Nikola Jokic",
        "participant_id": "player-15",
        "selection_side": "over",
        "line_value": 24.5,
        "book_odds": 105,
        "book_decimal": 2.05,
        "reference_source": "market_median",
        "reference_odds": -110,
        "true_prob": true_prob,
        "raw_true_prob": true_prob,
        "ev_percentage": ev_percentage,
        "base_kelly_fraction": 0.02,
        "confidence_label": "solid",
        "confidence_score": 0.6,
        "prob_std": 0.01,
        "reference_bookmaker_count": 3,
        "filtered_reference_count": 3,
        "exact_reference_count": 2,
        "interpolated_reference_count": 1,
        "interpolation_mode": "mixed",
        "reference_bookmakers": ["betonlineag", "bovada", "betmgm"],
        "reference_inputs_json": [{"book_key": "betonlineag", "prob": 0.52}],
        "shrink_factor": 0.1,
    }


def test_capture_player_prop_model_candidate_observations_dedupes_by_set_model_opportunity():
    db = _DB()

    first = capture_player_prop_model_candidate_observations(
        db,
        candidate_sets={
            "props_v1_live": [_side(ev_percentage=2.2, true_prob=0.52)],
            "props_v2_shadow": [_side(ev_percentage=0.8, true_prob=0.53)],
        },
        source="manual_scan",
        captured_at="2026-04-01T12:00:00Z",
    )
    second = capture_player_prop_model_candidate_observations(
        db,
        candidate_sets={
            "props_v1_live": [_side(ev_percentage=3.0, true_prob=0.54)],
            "props_v2_shadow": [_side(ev_percentage=1.4, true_prob=0.55)],
        },
        source="manual_scan",
        captured_at="2026-04-01T12:00:00Z",
    )

    rows = db.tables[PLAYER_PROP_MODEL_CANDIDATE_TABLE]
    assert first == {"eligible_seen": 2, "inserted": 2, "updated": 0}
    assert second == {"eligible_seen": 2, "inserted": 0, "updated": 2}
    assert len(rows) == 2
    assert {row["model_key"] for row in rows} == {"props_v1_live", "props_v2_shadow"}
    assert {row["cohort"] for row in rows} == {"displayed_default"}
    assert all(row["candidate_set_key"] == "manual_scan:2026-04-01T12:00:00Z" for row in rows)
    assert next(row for row in rows if row["model_key"] == "props_v1_live")["true_prob"] == 0.54
