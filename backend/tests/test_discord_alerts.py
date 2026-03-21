import importlib

import pytest
from .test_utils import reload_service_module


def _reload_discord_alerts():
    mod = reload_service_module("discord_alerts")
    return importlib.reload(mod)


@pytest.mark.parametrize(
    ("ev", "odds", "expected"),
    [
        (1.5, 500, True),
        (1.49, 500, False),
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


def test_make_alert_key_prefers_event_id_when_present():
    mod = _reload_discord_alerts()
    side = {
        "sport": "basketball_nba",
        "commence_time": "2026-03-17T01:00:00Z",
        "event": "Away @ Home",
        "sportsbook": "FanDuel",
        "team": "Home",
        "event_id": "evt_123",
    }
    key = mod.make_alert_key(side)
    assert key == "basketball_nba|id:evt_123|FanDuel|Home"


def test_build_scanner_deeplink_includes_event_id_when_available():
    mod = _reload_discord_alerts()
    side = {
        "sport": "basketball_nba",
        "event": "Away @ Home",
        "team": "Home",
        "sportsbook": "FanDuel",
        "event_id": "evt_123",
    }
    link = mod.build_scanner_deeplink(side)
    assert "event_id=evt_123" in link


def test_build_discord_payload_tiers():
    mod = _reload_discord_alerts()

    solid_payload = mod.build_discord_payload(
        {
            "sport": "basketball_nba",
            "event": "Away @ Home",
            "team": "Home",
            "sportsbook": "FanDuel",
            "book_odds": 120,
            "ev_percentage": 2.2,
        }
    )
    solid_embed = solid_payload["embeds"][0]
    assert "Solid Edge" in solid_embed["title"]
    assert any(f["name"] == "Tier" and f["value"] == "Solid Edge" for f in solid_embed["fields"])

    high_payload = mod.build_discord_payload(
        {
            "sport": "basketball_nba",
            "event": "Away @ Home",
            "team": "Home",
            "sportsbook": "FanDuel",
            "book_odds": 120,
            "ev_percentage": 3.1,
        }
    )
    high_embed = high_payload["embeds"][0]
    assert "HIGH EDGE" in high_embed["title"]
    assert any(f["name"] == "Tier" and f["value"] == "HIGH EDGE" for f in high_embed["fields"])


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

