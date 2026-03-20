import importlib

import pytest
from .test_utils import reload_service_module


def _reload_discord_alerts():
    mod = reload_service_module("discord_alerts")
    return importlib.reload(mod)


@pytest.mark.parametrize(
    ("ev", "odds", "expected"),
    [
        (3.0, 500, True),
        (2.99, 500, False),
        (3.0, 501, False),
        (10.0, -110, True),
    ],
)
def test_should_alert_thresholds(ev, odds, expected):
    mod = _reload_discord_alerts()
    assert mod.should_alert({"ev_percentage": ev, "book_odds": odds}) is expected


def test_make_alert_key_stable_fields():
    mod = _reload_discord_alerts()
    side = {
        "sport": "basketball_nba",
        "commence_time": "2026-03-17T01:00:00Z",
        "event": "Away @ Home",
        "sportsbook": "FanDuel",
        "team": "Home",
        # noise fields should not affect the key
        "ev_percentage": 9.9,
        "book_odds": 120,
    }
    k1 = mod.make_alert_key(side)
    side["ev_percentage"] = 1.0
    k2 = mod.make_alert_key(side)
    assert k1 == k2


def test_schedule_alerts_dedupes(monkeypatch):
    mod = _reload_discord_alerts()
    mod.ALERTED_KEYS.clear()

    created = []

    def fake_create_task(_coro):
        created.append(_coro)
        # Prevent "coroutine was never awaited" warnings in unit tests.
        try:
            _coro.close()
        except Exception:
            pass
        class DummyTask:  # noqa: D401
            pass
        return DummyTask()

    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task, raising=True)

    good = {
        "sport": "basketball_nba",
        "commence_time": "t",
        "event": "A @ B",
        "sportsbook": "DraftKings",
        "team": "A",
        "ev_percentage": 3.0,
        "book_odds": 200,
    }
    # same key, different EV should still dedupe
    dup = {**good, "ev_percentage": 8.0}

    scheduled = mod.schedule_alerts([good, dup])
    assert scheduled == 1
    assert len(created) == 1


@pytest.mark.asyncio
async def test_send_discord_webhook_noop_without_env(monkeypatch, capsys):
    mod = _reload_discord_alerts()
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    mod._warned_missing_webhook = False

    await mod.send_discord_webhook({"content": "hi"})
    out = capsys.readouterr().out
    assert "DISCORD_WEBHOOK_URL not set" in out

