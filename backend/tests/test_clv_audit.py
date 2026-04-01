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
    def __init__(self, *, bets, research):
        self._bets = bets
        self._research = research

    def table(self, name):
        if name == "bets":
            return _TableQuery(self._bets)
        if name == "scan_opportunities":
            return _TableQuery(self._research)
        raise AssertionError(name)


def test_build_clv_audit_snapshot_counts_pending_valid_and_invalid_rows():
    ensure_supabase_stub()
    mod = reload_service_module("clv_audit")

    db = _DB(
        bets=[
            {
                "id": "bet-pending",
                "surface": "straight_bets",
                "event": "A @ B",
                "sportsbook": "DraftKings",
                "commence_time": "2026-03-31T22:00:00Z",
                "created_at": "2026-03-31T18:00:00Z",
                "pinnacle_odds_at_close": None,
                "clv_updated_at": None,
                "clv_ev_percent": None,
                "beat_close": None,
            },
            {
                "id": "bet-valid",
                "surface": "straight_bets",
                "event": "C @ D",
                "sportsbook": "FanDuel",
                "commence_time": "2026-03-31T22:00:00Z",
                "created_at": "2026-03-31T17:00:00Z",
                "pinnacle_odds_at_close": -120,
                "clv_updated_at": "2026-03-31T21:45:00Z",
                "clv_ev_percent": 1.1,
                "beat_close": True,
            },
            {
                "id": "bet-invalid",
                "surface": "straight_bets",
                "event": "E @ F",
                "sportsbook": "BetMGM",
                "commence_time": "2026-03-31T22:00:00Z",
                "created_at": "2026-03-31T16:00:00Z",
                "pinnacle_odds_at_close": -130,
                "clv_updated_at": "2026-03-31T20:00:00Z",
                "clv_ev_percent": 0.4,
                "beat_close": True,
            },
        ],
        research=[
            {
                "id": "opp-valid",
                "surface": "player_props",
                "event": "Road @ Home",
                "sportsbook": "FanDuel",
                "commence_time": "2026-03-31T22:00:00Z",
                "first_seen_at": "2026-03-31T18:30:00Z",
                "reference_odds_at_close": 150,
                "close_captured_at": "2026-03-31T21:45:00Z",
                "clv_ev_percent": 0.7,
                "beat_close": True,
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
    assert snapshot["bets"]["tracked_count"] == 3
    assert snapshot["bets"]["pending_count"] == 1
    assert snapshot["bets"]["valid_count"] == 1
    assert snapshot["bets"]["invalid_count"] == 1
    assert snapshot["research_opportunities"]["valid_count"] == 1
