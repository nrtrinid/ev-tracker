from datetime import datetime, timezone

import pytest

from .test_utils import reload_service_module


def _reload_odds_api():
    mod = reload_service_module("odds_api")
    mod._cache.clear()
    mod._locks.clear()
    return mod


def _cached_payload(now_ts: float) -> dict:
    return {
        "sides": [{"event_id": "cached-evt"}],
        "events_fetched": 1,
        "events_with_both_books": 1,
        "api_requests_remaining": "99",
        "fetched_at": now_ts,
    }


def _fresh_payload() -> dict:
    return {
        "sides": [{"event_id": "fresh-evt"}],
        "events_fetched": 2,
        "events_with_both_books": 2,
        "api_requests_remaining": "98",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["manual_scan", "ops_trigger_board_drop", "scheduled_board_drop"])
async def test_get_cached_or_scan_bypasses_cache_for_manual_and_board_drop_sources(monkeypatch, source):
    mod = _reload_odds_api()
    sport = "basketball_nba"
    now = datetime.now(timezone.utc).timestamp()
    cached_payload = _cached_payload(now)
    fresh_payload = _fresh_payload()

    mod._cache[sport] = dict(cached_payload)

    stored_payloads = []
    scan_calls = []

    monkeypatch.setattr(mod, "get_scan_cache", lambda _sport: dict(cached_payload), raising=True)
    monkeypatch.setattr(mod, "set_scan_cache", lambda *args: stored_payloads.append(args), raising=True)

    async def _fake_scan(scan_sport: str, source: str = "unknown"):
        scan_calls.append((scan_sport, source))
        return dict(fresh_payload)

    monkeypatch.setattr(mod, "scan_all_sides", _fake_scan, raising=True)

    result = await mod.get_cached_or_scan(sport, source=source)

    assert result["cache_hit"] is False
    assert result["sides"] == fresh_payload["sides"]
    assert scan_calls == [(sport, source)]
    assert stored_payloads


@pytest.mark.asyncio
async def test_get_cached_or_scan_uses_warm_cache_for_non_bypass_source(monkeypatch):
    mod = _reload_odds_api()
    sport = "basketball_nba"
    now = datetime.now(timezone.utc).timestamp()
    cached_payload = _cached_payload(now)

    mod._cache[sport] = dict(cached_payload)

    monkeypatch.setattr(mod, "get_scan_cache", lambda _sport: None, raising=True)

    async def _boom_scan(*_args, **_kwargs):
        raise AssertionError("scan should not run for warm non-bypass cache")

    monkeypatch.setattr(mod, "scan_all_sides", _boom_scan, raising=True)

    result = await mod.get_cached_or_scan(sport, source="ops_snapshot")

    assert result["cache_hit"] is True
    assert result["sides"] == cached_payload["sides"]