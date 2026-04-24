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
        self._order_by: list[tuple[str, bool]] = []
        self._range: tuple[int, int] | None = None

    def select(self, _fields):
        return self

    def order(self, key, desc=False):
        self._order_by.append((key, bool(desc)))
        return self

    def range(self, start, end):
        self._range = (int(start), int(end))
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
            for key, desc in reversed(self._order_by):
                matched.sort(key=lambda row: row.get(key), reverse=desc)
            if self._range is None:
                matched = matched[:1000]
            else:
                start, end = self._range
                matched = matched[start:end + 1]
            return _Resp([dict(row) for row in matched])
        for row in matched:
            row.update(self._payload)
        return _Resp([])


class _DB:
    def __init__(self, rows=None, candidate_rows=None, weight_rows=None):
        self.tables = {
            "scan_opportunity_model_evaluations": list(rows or []),
            "player_prop_model_candidate_observations": list(candidate_rows or []),
            "player_prop_model_weights": list(weight_rows or []),
        }

    def table(self, name):
        assert name in self.tables
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


def test_update_scan_opportunity_model_evaluations_close_snapshot_updates_candidate_observations():
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
        ],
        candidate_rows=[
            {
                "id": "candidate-1",
                "candidate_set_key": "manual_scan:2026-03-30T12:00:00Z",
                "model_key": "props_v2_shadow",
                "opportunity_key": "opp-1",
                "true_prob": 0.53,
                "book_odds": 105,
            }
        ],
    )

    updated = update_scan_opportunity_model_evaluations_close_snapshot(
        db,
        opportunity_key="opp-1",
        close_reference_odds=-112,
        close_opposing_reference_odds=-108,
        close_captured_at="2026-03-30T18:40:00Z",
    )

    assert updated == 1
    candidate = db.tables["player_prop_model_candidate_observations"][0]
    assert candidate["close_reference_odds"] == -112
    assert candidate["close_opposing_reference_odds"] == -108
    assert candidate["close_quality"] == "paired"
    assert candidate["clv_ev_percent"] is not None
    assert candidate["brier_score"] is not None
    assert candidate["log_loss"] is not None


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
    assert summary.paired_close_count == 1
    assert summary.fallback_close_count == 0
    assert summary.by_model[0].valid_close_count >= 1
    assert all(item.paired_close_count == 1 for item in summary.by_model)
    assert summary.by_interpolation_mode[0].key in {"exact", "mixed"}
    assert summary.recent_comparisons[0].baseline_model_key == "props_v1_live"
    assert summary.recent_comparisons[0].candidate_model_key == "props_v2_shadow"
    assert summary.release_gate.candidate_model_key == "props_v2_shadow"
    assert summary.release_gate.eligible is False
    assert summary.release_gate.passes is False
    assert summary.release_gate.verdict == "not_enough_sample"
    assert summary.release_gate.brier_delta == 0.000316
    assert summary.release_gate.log_loss_delta == 0.0014
    assert summary.release_gate.avg_true_prob_delta_pct_points == 1.0
    assert summary.release_gate.avg_abs_true_prob_delta_pct_points == 1.0
    assert summary.release_gate.max_abs_true_prob_delta_pct_points == 1.0
    assert summary.release_gate.identical_true_prob_count == 0
    assert summary.release_gate.identical_true_prob_pct == 0.0
    assert summary.release_gate.avg_ev_delta_pct_points == 0.8
    assert summary.release_gate.brier_baseline_better_count == 1
    assert summary.release_gate.log_loss_baseline_better_count == 1


def test_get_model_calibration_summary_pages_past_postgrest_default_limit():
    rows = []
    for idx in range(501):
        opportunity_key = f"opp-{idx:04d}"
        rows.append(
            {
                "opportunity_key": opportunity_key,
                "model_key": "props_v1_live",
                "capture_role": "live",
                "surface": "player_props",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "team": "Denver Nuggets",
                "sportsbook": "FanDuel",
                "sportsbook_key": "fanduel",
                "market": "player_points",
                "event_id": f"evt-{idx}",
                "player_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "first_seen_at": f"2026-03-30T12:{idx % 60:02d}:00Z",
                "last_seen_at": f"2026-03-30T12:{idx % 60:02d}:30Z",
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
            }
        )
        rows.append(
            {
                "opportunity_key": opportunity_key,
                "model_key": "props_v2_shadow",
                "capture_role": "shadow",
                "surface": "player_props",
                "sport": "basketball_nba",
                "event": "Nuggets @ Suns",
                "team": "Denver Nuggets",
                "sportsbook": "FanDuel",
                "sportsbook_key": "fanduel",
                "market": "player_points",
                "event_id": f"evt-{idx}",
                "player_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "first_seen_at": f"2026-03-30T12:{idx % 60:02d}:00Z",
                "last_seen_at": f"2026-03-30T12:{idx % 60:02d}:30Z",
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
                "first_brier_score": 0.000100,
                "last_brier_score": 0.000100,
                "first_log_loss": 0.691,
                "last_log_loss": 0.691,
            }
        )

    summary = get_model_calibration_summary(_DB(rows=rows))

    assert summary.captured_count == 1002
    assert summary.valid_close_count == 1002
    assert summary.paired_close_count == 501
    assert summary.release_gate.eligible is True
    assert summary.release_gate.passes is True
    assert summary.release_gate.verdict == "promote"
    assert summary.release_gate.brier_delta == -0.000017
    assert summary.release_gate.log_loss_delta == -0.001
    assert summary.release_gate.avg_clv_delta_pct_points == 0.0
    assert summary.release_gate.beat_close_delta_pct_points == 0.0
    assert summary.release_gate.brier_candidate_better_count == 501
    assert summary.release_gate.log_loss_candidate_better_count == 501


def test_get_model_calibration_summary_holds_neutral_for_deadband_ties():
    rows = []
    for idx in range(200):
        base = {
            "opportunity_key": f"opp-{idx:04d}",
            "capture_role": "live",
            "surface": "player_props",
            "sport": "basketball_nba",
            "event": "Nuggets @ Suns",
            "team": "Denver Nuggets",
            "sportsbook": "FanDuel",
            "sportsbook_key": "fanduel",
            "market": "player_points",
            "event_id": f"evt-{idx}",
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
        }
        rows.append(
            {
                **base,
                "model_key": "props_v1_live",
                "first_brier_score": 0.000486,
                "last_brier_score": 0.000486,
                "first_log_loss": 0.686101,
                "last_log_loss": 0.686101,
            }
        )
        rows.append(
            {
                **base,
                "model_key": "props_v2_shadow",
                "capture_role": "shadow",
                "first_true_prob": 0.520001,
                "last_true_prob": 0.520001,
                "first_brier_score": 0.000487,
                "last_brier_score": 0.000487,
                "first_log_loss": 0.686102,
                "last_log_loss": 0.686102,
            }
        )

    summary = get_model_calibration_summary(_DB(rows=rows))

    assert summary.release_gate.eligible is True
    assert summary.release_gate.passes is False
    assert summary.release_gate.verdict == "hold_neutral"
    assert summary.release_gate.neutral_within_deadband is True
    assert summary.release_gate.brier_delta == 0.000001
    assert summary.release_gate.log_loss_delta == 0.000001


def test_get_model_calibration_summary_reports_shadow_candidate_overlap_and_weights():
    candidate_rows = [
        {
            "candidate_set_key": "manual_scan:2026-04-01T12:00:00Z",
            "source": "manual_scan",
            "captured_at": "2026-04-01T12:00:00Z",
            "model_key": "props_v1_live",
            "opportunity_key": "opp-a",
            "rank_overall": 1,
            "cohort": "displayed_default",
            "ev_percentage": 4.0,
        },
        {
            "candidate_set_key": "manual_scan:2026-04-01T12:00:00Z",
            "source": "manual_scan",
            "captured_at": "2026-04-01T12:00:00Z",
            "model_key": "props_v1_live",
            "opportunity_key": "opp-b",
            "rank_overall": 2,
            "cohort": "displayed_default",
            "ev_percentage": 2.0,
        },
        {
            "candidate_set_key": "manual_scan:2026-04-01T12:00:00Z",
            "source": "manual_scan",
            "captured_at": "2026-04-01T12:00:00Z",
            "model_key": "props_v2_shadow",
            "opportunity_key": "opp-b",
            "rank_overall": 1,
            "cohort": "displayed_default",
            "ev_percentage": 3.5,
        },
        {
            "candidate_set_key": "manual_scan:2026-04-01T12:00:00Z",
            "source": "manual_scan",
            "captured_at": "2026-04-01T12:00:00Z",
            "model_key": "props_v2_shadow",
            "opportunity_key": "opp-c",
            "rank_overall": 2,
            "cohort": "displayed_default",
            "ev_percentage": 5.0,
            "clv_ev_percent": 1.2,
            "beat_close": True,
            "brier_score": 0.0002,
            "log_loss": 0.69,
        },
    ]
    weight_rows = [
        {
            "model_family": "props_v2",
            "market_key": "player_points",
            "sportsbook_key": "fanduel",
            "updated_at": "2026-04-01T13:00:00Z",
        },
        {
            "model_family": "props_v2",
            "market_key": "player_rebounds",
            "sportsbook_key": "draftkings",
            "updated_at": "2026-04-01T13:05:00Z",
        },
    ]

    summary = get_model_calibration_summary(
        _DB(rows=[], candidate_rows=candidate_rows, weight_rows=weight_rows)
    )
    shadow = summary.shadow_candidate_set

    assert shadow.latest_candidate_set_key == "manual_scan:2026-04-01T12:00:00Z"
    assert shadow.v1_only_count == 1
    assert shadow.v2_only_count == 1
    assert shadow.both_count == 1
    assert shadow.overlap_pct == 33.33
    assert shadow.top_25_overlap_pct == 50.0
    assert shadow.avg_ev_delta_pct_points == 1.5
    assert shadow.avg_rank_delta == -1.0
    assert shadow.v2_only_displayed_count == 1
    assert shadow.v2_only_valid_close_count == 1
    assert shadow.v2_only_avg_clv_percent == 1.2
    assert shadow.weight_status.override_count == 2
    assert shadow.weight_status.markets_covered == 2
    assert shadow.weight_status.default_only is False
