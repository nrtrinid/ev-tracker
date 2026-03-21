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


def test_get_webhook_and_role_alert_routing(monkeypatch):
    """Test that alert messages route to dedicated alert webhook when set."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://alert-webhook")
    monkeypatch.setenv("DISCORD_ALERT_MENTION_ROLE_ID", "alert-role")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)
    
    webhook, role = mod._get_webhook_and_role("alert")
    assert webhook == "https://alert-webhook"
    assert role == "alert-role"


def test_get_webhook_and_role_heartbeat_routing(monkeypatch):
    """Test that heartbeat messages route to dedicated debug webhook when set."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_DEBUG_WEBHOOK_URL", "https://debug-webhook")
    monkeypatch.setenv("DISCORD_DEBUG_MENTION_ROLE_ID", "debug-role")
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)
    
    webhook, role = mod._get_webhook_and_role("heartbeat")
    assert webhook == "https://debug-webhook"
    assert role == "debug-role"


def test_get_webhook_and_role_test_routing(monkeypatch):
    """Test that test messages route to dedicated debug webhook when set."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_DEBUG_WEBHOOK_URL", "https://debug-webhook")
    monkeypatch.setenv("DISCORD_DEBUG_MENTION_ROLE_ID", "debug-role")
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)
    
    webhook, role = mod._get_webhook_and_role("test")
    assert webhook == "https://debug-webhook"
    assert role == "debug-role"


def test_get_webhook_and_role_alert_fallback_to_primary(monkeypatch):
    """Test that alert messages fall back to primary webhook when alert webhook not set."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)
    monkeypatch.setenv("DISCORD_DEBUG_WEBHOOK_URL", "https://debug-webhook")
    monkeypatch.setenv("DISCORD_DEBUG_MENTION_ROLE_ID", "debug-role")
    
    webhook, role = mod._get_webhook_and_role("alert")
    assert webhook == "https://primary-webhook"
    assert role == "primary-role"


def test_get_webhook_and_role_heartbeat_fallback_to_primary(monkeypatch):
    """Test that heartbeat messages fall back to primary webhook when debug webhook not set."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)
    
    webhook, role = mod._get_webhook_and_role("heartbeat")
    assert webhook == "https://primary-webhook"
    assert role == "primary-role"


def test_get_webhook_and_role_unknown_type_fallback(monkeypatch):
    """Test that unknown message types fall back to primary webhook."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    
    webhook, role = mod._get_webhook_and_role("unknown_type")
    assert webhook == "https://primary-webhook"
    assert role == "primary-role"


def test_with_role_mention_custom_role(monkeypatch):
    """Test that _with_role_mention uses provided role_id parameter."""
    mod = _reload_discord_alerts()
    
    monkeypatch.delenv("DISCORD_MENTION_ROLE_ID", raising=False)
    
    payload = {"content": "Hello"}
    result = mod._with_role_mention(payload, role_id="custom-role-123")
    assert "<@&custom-role-123>" in result["content"]
    assert "Hello" in result["content"]


def test_with_role_mention_fallback_to_env(monkeypatch):
    """Test that _with_role_mention falls back to environment variable when no role_id provided."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "env-role-456")
    
    payload = {"content": "Hello"}
    result = mod._with_role_mention(payload, role_id=None)
    assert "<@&env-role-456>" in result["content"]
    assert "Hello" in result["content"]


def test_with_role_mention_no_role_set(monkeypatch):
    """Test that _with_role_mention leaves payload unchanged when no role is set."""
    mod = _reload_discord_alerts()
    
    monkeypatch.delenv("DISCORD_MENTION_ROLE_ID", raising=False)
    
    payload = {"content": "Hello"}
    result = mod._with_role_mention(payload, role_id=None)
    assert result["content"] == "Hello"

