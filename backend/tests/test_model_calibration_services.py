from services.model_calibration import (
    get_model_calibration_summary,
    update_scan_opportunity_model_evaluations_close_snapshot,
)


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table_name, *, mode="select", payload=None, filters=None):
        self._db = db
        self._table_name = table_name
        self._mode = mode
        self._payload = payload or {}
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

    def execute(self):
        rows = self._db.tables[self._table_name]
        matched = [row for row in rows if all(predicate(row) for predicate in self._filters)]
        if self._mode == "select":
            return _Resp([dict(row) for row in matched])
        for row in matched:
            row.update(self._payload)
        return _Resp([])


class _DB:
    def __init__(self, rows=None):
        self.tables = {
            "scan_opportunity_model_evaluations": list(rows or []),
        }

    def table(self, name):
        assert name == "scan_opportunity_model_evaluations"
        return _Query(self, name)


def test_update_scan_opportunity_model_evaluations_close_snapshot_populates_paired_close_metrics():
    db = _DB(
        rows=[
            {
                "id": "eval-1",
                "opportunity_key": "opp-1",
                "model_key": "props_v1_live",
                "first_true_prob": 0.52,
                "last_true_prob": 0.52,
                "first_book_odds": 105,
                "last_book_odds": 105,
            }
        ]
    )

    updated = update_scan_opportunity_model_evaluations_close_snapshot(
        db,
        opportunity_key="opp-1",
        close_reference_odds=-112,
        close_opposing_reference_odds=-108,
        close_captured_at="2026-03-30T18:40:00Z",
    )

    assert updated == 1
    row = db.tables["scan_opportunity_model_evaluations"][0]
    assert row["close_reference_odds"] == -112
    assert row["close_opposing_reference_odds"] == -108
    assert row["close_quality"] == "paired"
    assert row["close_true_prob"] is not None
    assert row["first_clv_ev_percent"] is not None
    assert row["first_brier_score"] is not None
    assert row["first_log_loss"] is not None


def test_get_model_calibration_summary_builds_release_gate_and_breakdowns():
    db = _DB(
        rows=[
            {
                "opportunity_key": "opp-1",
                "model_key": "props_v1_live",
                "capture_role": "live",
                "surface": "player_props",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "team": "Denver Nuggets",
                "sportsbook": "FanDuel",
                "sportsbook_key": "fanduel",
                "market": "player_points",
                "event_id": "evt-1",
                "player_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "first_seen_at": "2026-03-30T12:00:00Z",
                "last_seen_at": "2026-03-30T12:05:00Z",
                "first_true_prob": 0.52,
                "last_true_prob": 0.52,
                "first_reference_odds": -108,
                "last_reference_odds": -108,
                "first_ev_percentage": 6.2,
                "last_ev_percentage": 6.2,
                "first_confidence_score": 0.54,
                "last_confidence_score": 0.54,
                "first_reference_bookmaker_count": 2,
                "last_reference_bookmaker_count": 2,
                "first_interpolation_mode": "exact",
                "last_interpolation_mode": "exact",
                "close_reference_odds": -112,
                "close_opposing_reference_odds": -108,
                "close_true_prob": 0.5092,
                "close_quality": "paired",
                "close_captured_at": "2026-03-30T18:40:00Z",
                "first_clv_ev_percent": 4.37,
                "last_clv_ev_percent": 4.37,
                "first_beat_close": True,
                "last_beat_close": True,
                "first_brier_score": 0.000117,
                "last_brier_score": 0.000117,
                "first_log_loss": 0.692,
                "last_log_loss": 0.692,
            },
            {
                "opportunity_key": "opp-1",
                "model_key": "props_v2_shadow",
                "capture_role": "shadow",
                "surface": "player_props",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "team": "Denver Nuggets",
                "sportsbook": "FanDuel",
                "sportsbook_key": "fanduel",
                "market": "player_points",
                "event_id": "evt-1",
                "player_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "first_seen_at": "2026-03-30T12:00:00Z",
                "last_seen_at": "2026-03-30T12:05:00Z",
                "first_true_prob": 0.53,
                "last_true_prob": 0.53,
                "first_reference_odds": -111,
                "last_reference_odds": -111,
                "first_ev_percentage": 7.0,
                "last_ev_percentage": 7.0,
                "first_confidence_score": 0.71,
                "last_confidence_score": 0.71,
                "first_reference_bookmaker_count": 3,
                "last_reference_bookmaker_count": 3,
                "first_interpolation_mode": "mixed",
                "last_interpolation_mode": "mixed",
                "close_reference_odds": -112,
                "close_opposing_reference_odds": -108,
                "close_true_prob": 0.5092,
                "close_quality": "paired",
                "close_captured_at": "2026-03-30T18:40:00Z",
                "first_clv_ev_percent": 4.37,
                "last_clv_ev_percent": 4.37,
                "first_beat_close": True,
                "last_beat_close": True,
                "first_brier_score": 0.000433,
                "last_brier_score": 0.000433,
                "first_log_loss": 0.6934,
                "last_log_loss": 0.6934,
            },
        ]
    )

    summary = get_model_calibration_summary(db)

    assert summary.captured_count == 2
    assert summary.valid_close_count == 2
    assert summary.paired_close_count == 2
    assert summary.fallback_close_count == 0
    assert summary.by_model[0].valid_close_count >= 1
    assert summary.by_interpolation_mode[0].key in {"exact", "mixed"}
    assert summary.recent_comparisons[0].baseline_model_key == "props_v1_live"
    assert summary.recent_comparisons[0].candidate_model_key == "props_v2_shadow"
    assert summary.release_gate.candidate_model_key == "props_v2_shadow"
    assert summary.release_gate.eligible is False
    assert summary.release_gate.passes is False
