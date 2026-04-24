import asyncio
import importlib

import pytest
import httpx
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


def test_build_board_drop_alert_payload():
    mod = _reload_discord_alerts()

    payload = mod.build_board_drop_alert_payload(
        window_label="Early-Look / Injury-Watch Scan",
        anchor_time_mst="09:30",
        result={
            "props_sides": 24,
            "straight_sides": 11,
            "featured_games_count": 9,
        },
    )

    embed = payload["embeds"][0]
    assert embed["title"] == "Trusted Beta Board Live"
    assert "09:30 MST" in embed["description"]
    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert fields["Player Props"] == "24"
    assert fields["Game Lines"] == "11"
    assert fields["Featured Games"] == "9"
    assert "Open EV Tracker" in fields["Open Board"]


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


def test_schedule_alerts_records_skip_telemetry(monkeypatch):
    mod = _reload_discord_alerts()
    mod.ALERTED_KEYS.clear()

    def fake_create_task(_coro):
        try:
            _coro.close()
        except Exception:
            pass

        class DummyTask:
            pass

        return DummyTask()

    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task, raising=True)
    monkeypatch.setattr(mod, "make_alert_key", lambda side: side["key"], raising=True)
    monkeypatch.setattr(mod, "should_alert", lambda side: bool(side.get("eligible")), raising=True)
    monkeypatch.setattr(
        mod,
        "mark_alert_if_new",
        lambda key, _ttl: key != "shared-dedupe",
        raising=True,
    )

    sides = [
        {"key": "good", "eligible": True},
        {"key": "shared-dedupe", "eligible": True},
        {"key": "threshold", "eligible": False},
        {"key": "good", "eligible": True},
    ]

    scheduled = mod.schedule_alerts(sides)
    stats = mod.get_last_schedule_stats()

    assert scheduled == 1
    assert stats["candidates_seen"] == 4
    assert stats["scheduled"] == 1
    assert stats["skipped_shared_dedupe"] == 1
    assert stats["skipped_threshold"] == 1
    assert stats["skipped_memory_dedupe"] == 1
    assert stats["skipped_total"] == 3


def test_schedule_alerts_supports_heartbeat_routing(monkeypatch):
    mod = _reload_discord_alerts()
    mod.ALERTED_KEYS.clear()

    seen_message_types: list[str] = []
    seen_delivery_contexts: list[str | None] = []

    async def fake_alert_for_side(_side, message_type="heartbeat", *, delivery_context=None):
        seen_message_types.append(message_type)
        seen_delivery_contexts.append(delivery_context)

    def fake_create_task(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

        class DummyTask:
            pass

        return DummyTask()

    monkeypatch.setattr(mod, "alert_for_side", fake_alert_for_side, raising=True)
    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task, raising=True)
    monkeypatch.setattr(mod, "should_alert", lambda _side: True, raising=True)
    monkeypatch.setattr(mod, "mark_alert_if_new", lambda *_args, **_kwargs: True, raising=True)

    side = {
        "sport": "basketball_nba",
        "commence_time": "t",
        "event": "A @ B",
        "sportsbook": "DraftKings",
        "team": "A",
        "ev_percentage": 3.0,
        "book_odds": 200,
    }

    scheduled = mod.schedule_alerts([side], message_type="heartbeat")
    assert scheduled == 1
    assert seen_message_types == ["heartbeat"]
    assert seen_delivery_contexts == [None]


def test_schedule_alerts_supports_scheduled_alert_context(monkeypatch):
    mod = _reload_discord_alerts()
    mod.ALERTED_KEYS.clear()

    seen: list[tuple[str, str | None]] = []

    async def fake_alert_for_side(_side, message_type="heartbeat", *, delivery_context=None):
        seen.append((message_type, delivery_context))

    def fake_create_task(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

        class DummyTask:
            pass

        return DummyTask()

    monkeypatch.setattr(mod, "alert_for_side", fake_alert_for_side, raising=True)
    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task, raising=True)
    monkeypatch.setattr(mod, "should_alert", lambda _side: True, raising=True)
    monkeypatch.setattr(mod, "mark_alert_if_new", lambda *_args, **_kwargs: True, raising=True)

    side = {
        "sport": "basketball_nba",
        "commence_time": "t",
        "event": "A @ B",
        "sportsbook": "DraftKings",
        "team": "A",
        "ev_percentage": 3.0,
        "book_odds": 200,
    }

    scheduled = mod.schedule_alerts(
        [side],
        message_type="alert",
        delivery_context="scheduled_board_drop",
    )
    assert scheduled == 1
    assert seen == [("alert", "scheduled_board_drop")]


@pytest.mark.asyncio
async def test_send_discord_webhook_default_routes_to_debug_without_env(monkeypatch, capsys):
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    mod._warned_missing_webhook = False

    delivery = await mod.send_discord_webhook({"content": "hi"})
    out = capsys.readouterr().out
    assert "DISCORD_DEBUG_WEBHOOK_URL not set" in out
    assert delivery["delivery_status"] == "disabled_no_webhook"
    assert delivery["message_type"] == "heartbeat"
    assert delivery["route_kind"] == "heartbeat_unconfigured"


@pytest.mark.asyncio
async def test_scheduled_alert_requires_dedicated_alert_webhook(monkeypatch, capsys):
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)

    monkeypatch.setattr(
        mod.httpx,
        "AsyncClient",
        lambda timeout: pytest.fail("scheduled alert should not post to legacy generic webhook"),
        raising=True,
    )

    delivery = await mod.send_discord_webhook(
        {"content": "hi"},
        message_type="alert",
        delivery_context="scheduled_board_drop",
    )
    out = capsys.readouterr().out
    assert "DISCORD_ALERT_WEBHOOK_URL not set" in out
    assert "DISCORD_WEBHOOK_URL not set" not in out
    assert delivery["delivery_status"] == "disabled_no_webhook"
    assert delivery["message_type"] == "alert"
    assert delivery["route_kind"] == "alert_unconfigured"
    assert delivery["webhook_source"] is None


@pytest.mark.asyncio
async def test_send_discord_webhook_alert_route_disabled_when_explicitly_disabled(monkeypatch, capsys):
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "0")
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://alert-webhook")

    delivery = await mod.send_discord_webhook(
        {"content": "hi"},
        message_type="alert",
        delivery_context="scheduled_board_drop",
    )
    out = capsys.readouterr().out

    assert "Alert route disabled" in out
    assert delivery["delivery_status"] == "disabled_no_webhook"
    assert delivery["route_kind"] == "alert_disabled"
    assert delivery["webhook_source"] is None


@pytest.mark.asyncio
async def test_send_discord_webhook_returns_delivery_metadata_on_success(monkeypatch):
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://alert-webhook")

    class FakeResponse:
        status_code = 204
        text = ""

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, _url, json):
            return FakeResponse()

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout: FakeClient(), raising=True)

    delivery = await mod.send_discord_webhook(
        {"content": "hi"},
        message_type="alert",
        delivery_context="scheduled_board_drop",
    )
    assert delivery["delivery_status"] == "delivered"
    assert delivery["status_code"] == 204
    assert delivery["webhook_source"] == "DISCORD_ALERT_WEBHOOK_URL"
    assert delivery["route_kind"] == "alert_dedicated"


@pytest.mark.asyncio
async def test_alert_without_scheduled_context_uses_debug_route(monkeypatch):
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://alert-webhook")
    monkeypatch.setenv("DISCORD_DEBUG_WEBHOOK_URL", "https://debug-webhook")
    posted_urls: list[str] = []

    class FakeResponse:
        status_code = 204
        text = ""

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            posted_urls.append(url)
            return FakeResponse()

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout: FakeClient(), raising=True)

    delivery = await mod.send_discord_webhook({"content": "manual"}, message_type="alert")

    assert posted_urls == ["https://debug-webhook"]
    assert delivery["requested_message_type"] == "alert"
    assert delivery["message_type"] == "heartbeat"
    assert delivery["alert_route_guarded"] is True
    assert delivery["route_kind"] == "heartbeat_dedicated"
    assert delivery["webhook_source"] == "DISCORD_DEBUG_WEBHOOK_URL"


@pytest.mark.asyncio
async def test_send_discord_webhook_heartbeat_does_not_use_primary_when_legacy_fallback_enabled(monkeypatch, capsys):
    mod = _reload_discord_alerts()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY", "1")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)

    monkeypatch.setattr(
        mod.httpx,
        "AsyncClient",
        lambda timeout: pytest.fail("heartbeat should not post to the primary Discord webhook"),
        raising=True,
    )

    delivery = await mod.send_discord_webhook({"content": "heartbeat"}, message_type="heartbeat")
    out = capsys.readouterr().out

    assert "DISCORD_DEBUG_WEBHOOK_URL not set" in out
    assert "DISCORD_WEBHOOK_URL not set" not in out
    assert delivery["delivery_status"] == "disabled_no_webhook"
    assert delivery["route_kind"] == "heartbeat_unconfigured"
    assert delivery["webhook_source"] is None


@pytest.mark.asyncio
async def test_send_discord_webhook_test_returns_debug_unconfigured_diagnostics(monkeypatch, capsys):
    mod = _reload_discord_alerts()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY", "1")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)

    monkeypatch.setattr(
        mod.httpx,
        "AsyncClient",
        lambda timeout: pytest.fail("test messages should not post to the primary Discord webhook"),
        raising=True,
    )

    delivery = await mod.send_discord_webhook({"content": "test"}, message_type="test")
    out = capsys.readouterr().out

    assert "DISCORD_DEBUG_WEBHOOK_URL not set" in out
    assert "DISCORD_WEBHOOK_URL not set" not in out
    assert delivery["delivery_status"] == "disabled_no_webhook"
    assert delivery["route_kind"] == "test_unconfigured"
    assert delivery["webhook_source"] is None


@pytest.mark.asyncio
async def test_send_discord_webhook_wraps_http_errors(monkeypatch):
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://alert-webhook")

    class FakeResponse:
        status_code = 429
        text = "rate limited"

        def raise_for_status(self):
            request = httpx.Request("POST", "https://alert-webhook")
            response = httpx.Response(429, request=request, text=self.text)
            raise httpx.HTTPStatusError("boom", request=request, response=response)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, _url, json):
            return FakeResponse()

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout: FakeClient(), raising=True)

    with pytest.raises(mod.DiscordDeliveryError) as exc_info:
        await mod.send_discord_webhook(
            {"content": "hi"},
            message_type="alert",
            delivery_context="scheduled_board_drop",
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.response_text == "rate limited"


def test_get_webhook_and_role_alert_routing(monkeypatch):
    """Test that alert messages route to dedicated alert webhook when set."""
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    
    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://alert-webhook")
    monkeypatch.setenv("DISCORD_ALERT_MENTION_ROLE_ID", "alert-role")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)
    
    webhook, role = mod._get_webhook_and_role("alert", delivery_context="scheduled_board_drop")
    assert webhook == "https://alert-webhook"
    assert role == "alert-role"


def test_describe_discord_delivery_target_alert_ignores_legacy_generic_webhook(monkeypatch):
    mod = _reload_discord_alerts()

    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)

    target = mod.describe_discord_delivery_target("alert", delivery_context="scheduled_board_drop")
    assert target["webhook_configured"] is False
    assert target["webhook_source"] is None
    assert target["route_kind"] == "alert_unconfigured"


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


def test_get_webhook_and_role_alert_does_not_fallback_to_primary(monkeypatch):
    """Legacy generic Discord vars must not feed scheduled alerts."""
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)
    monkeypatch.setenv("DISCORD_DEBUG_WEBHOOK_URL", "https://debug-webhook")
    monkeypatch.setenv("DISCORD_DEBUG_MENTION_ROLE_ID", "debug-role")
    
    webhook, role = mod._get_webhook_and_role("alert", delivery_context="scheduled_board_drop")
    assert webhook is None
    assert role is None


def test_get_webhook_and_role_alert_without_scheduled_context_uses_debug(monkeypatch):
    """Bare alert requests are deferred to the debug route."""
    mod = _reload_discord_alerts()
    monkeypatch.setenv("DISCORD_ENABLE_ALERT_ROUTE", "1")

    monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_URL", "https://alert-webhook")
    monkeypatch.setenv("DISCORD_ALERT_MENTION_ROLE_ID", "alert-role")
    monkeypatch.setenv("DISCORD_DEBUG_WEBHOOK_URL", "https://debug-webhook")
    monkeypatch.setenv("DISCORD_DEBUG_MENTION_ROLE_ID", "debug-role")

    webhook, role = mod._get_webhook_and_role("alert")
    assert webhook == "https://debug-webhook"
    assert role == "debug-role"

    target = mod.describe_discord_delivery_target("alert")
    assert target["requested_message_type"] == "alert"
    assert target["message_type"] == "heartbeat"
    assert target["alert_route_guarded"] is True
    assert target["route_kind"] == "heartbeat_dedicated"


def test_get_webhook_and_role_heartbeat_does_not_fallback_by_default(monkeypatch):
    """Heartbeat messages stay unconfigured without a dedicated debug webhook."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)
    monkeypatch.delenv("DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)
    
    webhook, role = mod._get_webhook_and_role("heartbeat")
    assert webhook is None
    assert role is None


def test_get_webhook_and_role_heartbeat_does_not_fallback_to_primary_when_opted_in(monkeypatch):
    """Legacy debug fallback flag must not send heartbeat traffic to the primary webhook."""
    mod = _reload_discord_alerts()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY", "1")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)

    webhook, role = mod._get_webhook_and_role("heartbeat")
    assert webhook is None
    assert role is None

    target = mod.describe_discord_delivery_target("heartbeat")
    assert target["webhook_configured"] is False
    assert target["webhook_source"] is None
    assert target["route_kind"] == "heartbeat_unconfigured"


def test_get_webhook_and_role_test_does_not_fallback_to_primary(monkeypatch):
    """Test messages must stay on the debug route even when heartbeat fallback is enabled."""
    mod = _reload_discord_alerts()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY", "1")
    monkeypatch.delenv("DISCORD_DEBUG_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_DEBUG_MENTION_ROLE_ID", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_ALERT_MENTION_ROLE_ID", raising=False)

    webhook, role = mod._get_webhook_and_role("test")
    assert webhook is None
    assert role is None

    target = mod.describe_discord_delivery_target("test")
    assert target["webhook_configured"] is False
    assert target["webhook_source"] is None
    assert target["route_kind"] == "test_unconfigured"


def test_get_webhook_and_role_unknown_type_uses_debug_route(monkeypatch):
    """Unknown message types must stay isolated to the debug route."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://primary-webhook")
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "primary-role")
    monkeypatch.setenv("DISCORD_DEBUG_WEBHOOK_URL", "https://debug-webhook")
    monkeypatch.setenv("DISCORD_DEBUG_MENTION_ROLE_ID", "debug-role")
    monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_URL", raising=False)
    
    webhook, role = mod._get_webhook_and_role("unknown_type")
    assert webhook == "https://debug-webhook"
    assert role == "debug-role"

    target = mod.describe_discord_delivery_target("unknown_type")
    assert target["webhook_configured"] is True
    assert target["webhook_source"] == "DISCORD_DEBUG_WEBHOOK_URL"
    assert target["route_kind"] == "unknown_dedicated"


def test_with_role_mention_custom_role(monkeypatch):
    """Test that _with_role_mention uses provided role_id parameter."""
    mod = _reload_discord_alerts()
    
    monkeypatch.delenv("DISCORD_MENTION_ROLE_ID", raising=False)
    
    payload = {"content": "Hello"}
    result = mod._with_role_mention(payload, role_id="custom-role-123")
    assert "<@&custom-role-123>" in result["content"]
    assert "Hello" in result["content"]


def test_with_role_mention_does_not_fallback_to_env(monkeypatch):
    """Role mentions must come from the resolved route config."""
    mod = _reload_discord_alerts()
    
    monkeypatch.setenv("DISCORD_MENTION_ROLE_ID", "env-role-456")
    
    payload = {"content": "Hello"}
    result = mod._with_role_mention(payload, role_id=None)
    assert result["content"] == "Hello"


def test_with_role_mention_no_role_set(monkeypatch):
    """Test that _with_role_mention leaves payload unchanged when no role is set."""
    mod = _reload_discord_alerts()
    
    monkeypatch.delenv("DISCORD_MENTION_ROLE_ID", raising=False)
    
    payload = {"content": "Hello"}
    result = mod._with_role_mention(payload, role_id=None)
    assert result["content"] == "Hello"


def test_schedule_alerts_logs_background_failures(monkeypatch, capsys):
    mod = _reload_discord_alerts()
    mod.ALERTED_KEYS.clear()

    async def fake_alert_for_side(_side, message_type="heartbeat", *, delivery_context=None):
        raise RuntimeError("boom")

    def fake_create_task(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

        class DummyTask:
            pass

        return DummyTask()

    monkeypatch.setattr(mod, "alert_for_side", fake_alert_for_side, raising=True)
    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task, raising=True)
    monkeypatch.setattr(mod, "should_alert", lambda _side: True, raising=True)
    monkeypatch.setattr(mod, "mark_alert_if_new", lambda *_args, **_kwargs: True, raising=True)

    side = {
        "sport": "basketball_nba",
        "commence_time": "t",
        "event": "A @ B",
        "sportsbook": "DraftKings",
        "team": "A",
        "ev_percentage": 3.0,
        "book_odds": 200,
    }

    scheduled = mod.schedule_alerts([side])
    assert scheduled == 1
    assert "Background heartbeat delivery failed" in capsys.readouterr().out
