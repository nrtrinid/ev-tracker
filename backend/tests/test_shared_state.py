import importlib
from .test_utils import reload_service_module


def _reload_shared_state(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    mod = reload_service_module("shared_state")
    return importlib.reload(mod)


def test_mark_once_dedupes_within_ttl(monkeypatch):
    mod = _reload_shared_state(monkeypatch)

    assert mod.mark_once("k1", ttl_seconds=60) is True
    assert mod.mark_once("k1", ttl_seconds=60) is False


def test_fixed_window_rate_limit(monkeypatch):
    mod = _reload_shared_state(monkeypatch)

    allowed = [
        mod.allow_fixed_window_rate_limit("u1", max_requests=2, window_seconds=60),
        mod.allow_fixed_window_rate_limit("u1", max_requests=2, window_seconds=60),
        mod.allow_fixed_window_rate_limit("u1", max_requests=2, window_seconds=60),
    ]
    assert allowed == [True, True, False]


def test_scan_cache_round_trip(monkeypatch):
    mod = _reload_shared_state(monkeypatch)

    payload = {"sides": [1, 2], "fetched_at": 123.0}
    mod.set_scan_cache("basketball_nba", payload, ttl_seconds=300)
    loaded = mod.get_scan_cache("basketball_nba")
    assert loaded == payload
