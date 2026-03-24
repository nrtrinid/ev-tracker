import importlib
from .test_utils import reload_service_module


def _reload_odds_api():
    mod = reload_service_module("odds_api")
    return importlib.reload(mod)


def test_odds_api_activity_snapshot_defaults_empty():
    mod = _reload_odds_api()

    snapshot = mod.get_odds_api_activity_snapshot()

    assert snapshot["summary"]["calls_last_hour"] == 0
    assert snapshot["summary"]["errors_last_hour"] == 0
    assert snapshot["summary"]["last_success_at"] is None
    assert snapshot["summary"]["last_error_at"] is None
    assert snapshot["recent_scans"] == []
    assert snapshot["recent_calls"] == []


def test_odds_api_activity_snapshot_tracks_recent_calls_and_grouped_scans():
    mod = _reload_odds_api()

    mod._append_odds_api_activity(
        source="manual_scan",
        endpoint="/sports/basketball_nba/odds",
        sport="basketball_nba",
        cache_hit=False,
        outbound_call_made=True,
        status_code=200,
        duration_ms=120.25,
        api_requests_remaining="183",
        error_type=None,
        error_message=None,
    )
    mod._append_odds_api_activity(
        source="manual_scan",
        endpoint="/sports/basketball_nba/scores",
        sport="basketball_nba",
        cache_hit=False,
        outbound_call_made=True,
        status_code=200,
        duration_ms=88.0,
        api_requests_remaining="182",
        error_type=None,
        error_message=None,
    )
    mod.append_scan_activity(
        scan_session_id="manual-1",
        source="manual_scan",
        surface="straight_bets",
        scan_scope="single_sport",
        requested_sport="basketball_nba",
        sport="basketball_nba",
        actor_label="ops@example.com",
        run_id=None,
        cache_hit=False,
        outbound_call_made=True,
        duration_ms=120.25,
        events_fetched=4,
        events_with_both_books=3,
        sides_count=8,
        api_requests_remaining="183",
        status_code=200,
        error_type=None,
        error_message=None,
    )
    mod.append_scan_activity(
        scan_session_id="manual-1",
        source="manual_scan",
        surface="straight_bets",
        scan_scope="single_sport",
        requested_sport="basketball_nba",
        sport="basketball_ncaab",
        actor_label="ops@example.com",
        run_id=None,
        cache_hit=True,
        outbound_call_made=False,
        duration_ms=0.0,
        events_fetched=2,
        events_with_both_books=1,
        sides_count=4,
        api_requests_remaining="183",
        status_code=200,
        error_type=None,
        error_message=None,
    )

    snapshot = mod.get_odds_api_activity_snapshot()

    assert snapshot["summary"]["calls_last_hour"] == 2
    assert snapshot["summary"]["errors_last_hour"] == 0
    assert snapshot["summary"]["last_success_at"] is not None
    assert snapshot["summary"]["last_error_at"] is None
    assert len(snapshot["recent_calls"]) == 1
    assert len(snapshot["recent_scans"]) == 1

    scan = snapshot["recent_scans"][0]
    assert scan["activity_kind"] == "scan_session"
    assert scan["source"] == "manual_scan"
    assert scan["surface"] == "straight_bets"
    assert scan["actor_label"] == "ops@example.com"
    assert scan["live_call_count"] == 1
    assert scan["cache_hit_count"] == 1
    assert scan["total_events_fetched"] == 6
    assert scan["total_sides"] == 12
    assert len(scan["details"]) == 2

    newest = snapshot["recent_calls"][0]
    assert newest["activity_kind"] == "raw_call"
    assert newest["source"] == "manual_scan"
    assert newest["endpoint"] == "/sports/basketball_nba/scores"
    assert "_ts_epoch" not in newest
