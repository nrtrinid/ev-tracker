import importlib


def _reload_odds_api():
    import services.odds_api as mod
    return importlib.reload(mod)


def test_odds_api_activity_snapshot_defaults_empty():
    mod = _reload_odds_api()

    snapshot = mod.get_odds_api_activity_snapshot()

    assert snapshot["summary"]["calls_last_hour"] == 0
    assert snapshot["summary"]["errors_last_hour"] == 0
    assert snapshot["summary"]["last_success_at"] is None
    assert snapshot["summary"]["last_error_at"] is None
    assert snapshot["recent_calls"] == []


def test_odds_api_activity_snapshot_tracks_recent_calls_and_errors():
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
        source="cron_scan",
        endpoint="/sports/basketball_nba/odds",
        sport="basketball_nba",
        cache_hit=False,
        outbound_call_made=True,
        status_code=500,
        duration_ms=410.0,
        api_requests_remaining=None,
        error_type="HTTPStatusError",
        error_message="Server error",
    )

    snapshot = mod.get_odds_api_activity_snapshot()

    assert snapshot["summary"]["calls_last_hour"] == 2
    assert snapshot["summary"]["errors_last_hour"] == 1
    assert snapshot["summary"]["last_success_at"] is not None
    assert snapshot["summary"]["last_error_at"] is not None
    assert len(snapshot["recent_calls"]) == 2

    newest = snapshot["recent_calls"][0]
    assert newest["source"] == "cron_scan"
    assert newest["status_code"] == 500
    assert newest["error_type"] == "HTTPStatusError"
    assert "_ts_epoch" not in newest
