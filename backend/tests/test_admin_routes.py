from .test_utils import ensure_supabase_stub

ensure_supabase_stub()

import asyncio

from models import FullScanResponse, ResearchOpportunitySummaryResponse
from routes.admin_routes import (
    admin_refresh_markets_impl,
    backfill_ev_locks_impl,
    research_opportunities_summary_impl,
    summarize_full_scan_for_admin,
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, _fields):
        return self

    def eq(self, _field, _value):
        return self

    def is_(self, _field, _value):
        return self

    def in_(self, _field, _values):
        return self

    def execute(self):
        return _Result(self._rows)


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "bets"
        return _Query(self._rows)


def test_backfill_ev_locks_impl_counts_successes_and_logs_failures():
    rows = [
        {"id": "a"},
        {"id": "b"},
        {"id": "c"},
    ]
    db = _DB(rows)
    warnings = []
    locked_ids = []

    def _lock_ev_for_row(_db, bet_id, _user_id, _row, _settings):
        if bet_id == "b":
            raise RuntimeError("boom")
        locked_ids.append(bet_id)

    out = backfill_ev_locks_impl(
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, _user_id: {"k_factor": 0.5},
        retry_supabase=lambda fn: fn(),
        ev_lock_promo_types=["bonus_bet"],
        lock_ev_for_row=_lock_ev_for_row,
        log_warning=lambda *args: warnings.append(args),
    )

    assert out == {"backfilled": 2, "total_eligible": 3}
    assert locked_ids == ["a", "c"]
    assert len(warnings) == 1
    assert warnings[0][0] == "backfill_ev_lock.failed bet_id=%s err=%s"
    assert warnings[0][1] == "b"


def test_summarize_full_scan_for_admin_counts_sides_and_copies_fields():
    resp = FullScanResponse(
        surface="straight_bets",
        sport="all",
        sides=[],
        events_fetched=12,
        events_with_both_books=7,
        api_requests_remaining="900",
        scanned_at="2026-03-28T12:00:00+00:00",
    )
    s = summarize_full_scan_for_admin(resp)
    assert s.surface == "straight_bets"
    assert s.sport == "all"
    assert s.events_fetched == 12
    assert s.events_with_both_books == 7
    assert s.total_sides == 0
    assert s.scanned_at == "2026-03-28T12:00:00+00:00"
    assert s.api_requests_remaining == "900"


def test_admin_refresh_markets_impl_runs_scans_in_order():
    calls: list[str] = []

    async def fake_run(surf: str) -> FullScanResponse:
        calls.append(surf)
        return FullScanResponse(
            surface=surf,  # type: ignore[arg-type]
            sport="all",
            sides=[],
            events_fetched=1,
            events_with_both_books=1,
        )

    out = asyncio.run(
        admin_refresh_markets_impl(
            surfaces=["straight_bets", "player_props"],
            user={"id": "u"},
            run_scan=fake_run,
        )
    )
    assert calls == ["straight_bets", "player_props"]
    assert len(out.results) == 2
    assert out.results[0].total_sides == 0
    assert out.results[1].surface == "player_props"


def test_research_opportunities_summary_impl_delegates_to_summary_builder():
    db = object()
    expected = ResearchOpportunitySummaryResponse(
        captured_count=4,
        open_count=2,
        close_captured_count=2,
        pending_close_count=2,
        valid_close_count=2,
        invalid_close_count=0,
        valid_close_coverage_pct=None,
        invalid_close_rate_pct=None,
        clv_ready_count=2,
        beat_close_pct=50.0,
        avg_clv_percent=0.8,
        by_surface=[],
        by_source=[],
        by_sportsbook=[],
        by_edge_bucket=[],
        by_odds_bucket=[],
        recent_opportunities=[],
    )

    out = research_opportunities_summary_impl(
        get_db=lambda: db,
        get_summary=lambda provided_db: expected if provided_db is db else None,
    )

    assert out == expected
