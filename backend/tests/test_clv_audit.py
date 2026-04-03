from types import SimpleNamespace

from .test_utils import ensure_supabase_stub, reload_service_module


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, _fields):
        return self

    def not_(self):
        return self

    def is_(self, _field, _value):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _NotProxy:
    def __init__(self, query):
        self._query = query

    def is_(self, _field, _value):
        return self._query


class _TableQuery:
    def __init__(self, rows):
        self._rows = rows
        self.not_ = _NotProxy(self)

    def select(self, _fields):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _DB:
    def __init__(self, *, bets, research, pickem=None):
        self._bets = bets
        self._research = research
        self._pickem = pickem or []

    def table(self, name):
        if name == "bets":
            return _TableQuery(self._bets)
        if name == "scan_opportunities":
            return _TableQuery(self._research)
        if name == "pickem_research_observations":
            return _TableQuery(self._pickem)
        raise AssertionError(name)


def test_build_clv_audit_snapshot_counts_pending_valid_and_invalid_rows():
    ensure_supabase_stub()
    mod = reload_service_module("clv_audit")

    db = _DB(
        bets=[
            {
                "id": "bet-missing",
                "surface": "straight_bets",
                "event": "A @ B",
                "sportsbook": "DraftKings",
                "commence_time": "2026-03-31T22:00:00Z",
                "created_at": "2026-03-31T18:00:00Z",
                "odds_american": -110,
                "latest_pinnacle_odds": None,
                "latest_pinnacle_updated_at": None,
                "pinnacle_odds_at_close": None,
                "clv_updated_at": None,
            },
            {
                "id": "bet-latest-only",
                "surface": "player_props",
                "event": "B @ C",
                "sportsbook": "FanDuel",
                "commence_time": "2026-03-31T22:00:00Z",
                "created_at": "2026-03-31T17:30:00Z",
                "odds_american": 105,
                "latest_pinnacle_odds": -112,
                "latest_pinnacle_updated_at": "2026-03-31T21:40:00Z",
                "pinnacle_odds_at_close": None,
                "clv_updated_at": None,
            },
            {
                "id": "bet-valid",
                "surface": "straight_bets",
                "event": "C @ D",
                "sportsbook": "FanDuel",
                "commence_time": "2026-03-31T22:00:00Z",
                "created_at": "2026-03-31T17:00:00Z",
                "odds_american": -110,
                "latest_pinnacle_odds": -120,
                "latest_pinnacle_updated_at": "2026-03-31T21:45:00Z",
                "pinnacle_odds_at_close": -120,
                "clv_updated_at": "2026-03-31T21:45:00Z",
            },
            {
                "id": "bet-outside-window",
                "surface": "straight_bets",
                "event": "E @ F",
                "sportsbook": "BetMGM",
                "commence_time": "2026-03-31T22:00:00Z",
                "created_at": "2026-03-31T16:00:00Z",
                "odds_american": -118,
                "latest_pinnacle_odds": -130,
                "latest_pinnacle_updated_at": "2026-03-31T20:00:00Z",
                "pinnacle_odds_at_close": -130,
                "clv_updated_at": "2026-03-31T20:00:00Z",
            },
        ],
        research=[
            {
                "id": "opp-latest-only",
                "surface": "player_props",
                "event": "Road @ Home",
                "sportsbook": "FanDuel",
                "commence_time": "2026-03-31T22:00:00Z",
                "first_seen_at": "2026-03-31T18:40:00Z",
                "first_book_odds": 120,
                "latest_reference_odds": 145,
                "latest_reference_updated_at": "2026-03-31T21:41:00Z",
                "reference_odds_at_close": None,
                "close_opposing_reference_odds": None,
                "close_captured_at": None,
            },
            {
                "id": "opp-valid",
                "surface": "player_props",
                "event": "Road @ Home",
                "sportsbook": "FanDuel",
                "commence_time": "2026-03-31T22:00:00Z",
                "first_seen_at": "2026-03-31T18:30:00Z",
                "first_book_odds": 120,
                "latest_reference_odds": 150,
                "latest_reference_updated_at": "2026-03-31T21:45:00Z",
                "reference_odds_at_close": 150,
                "close_opposing_reference_odds": -105,
                "close_captured_at": "2026-03-31T21:45:00Z",
            }
        ],
    )

    snapshot = mod.build_clv_audit_snapshot(
        db,
        retry_supabase=lambda fn, **_: fn(),
        load_scheduler_job_snapshot=lambda **_: {"jit_clv": {"run_id": "jit-1"}},
        utc_now_iso=lambda: "2026-03-31T22:05:00Z",
    )

    assert snapshot["generated_at"] == "2026-03-31T22:05:00Z"
    assert snapshot["inventory"]["reason_codes"]
    assert snapshot["job_runs"]["stale_jobs"]["jit_clv"]["scheduled"] is True
    assert snapshot["job_runs"]["stale_jobs"]["clv_finalize"]["scheduled"] is True
    assert snapshot["bets"]["tracked_count"] == 4
    assert snapshot["bets"]["pending_count"] == 2
    assert snapshot["bets"]["valid_count"] == 1
    assert snapshot["bets"]["invalid_count"] == 1
    assert snapshot["bets"]["missing_close_count"] == 1
    assert snapshot["bets"]["latest_only_count"] == 1
    assert snapshot["bets"]["outside_window_count"] == 1
    assert snapshot["bets"]["rescue_eligible_count"] == 1
    assert snapshot["bets"]["by_surface"][0]["count"] >= 1
    assert snapshot["bets"]["sample"]["latest_only"][0]["id"] == "bet-latest-only"
    assert snapshot["bets"]["sample"]["valid"][0]["clv_ev_percent"] is not None
    assert snapshot["research_opportunities"]["valid_count"] == 1
    assert snapshot["research_opportunities"]["latest_only_count"] == 1
    assert snapshot["research_opportunities"]["rescue_eligible_count"] == 1
    assert snapshot["pickem_research"]["tracked_count"] == 0
    assert snapshot["rescueability"]["rescue_eligible_count"] == 2
