from types import SimpleNamespace

import pytest

from routes import analytics_routes


@pytest.mark.asyncio
async def test_ingest_analytics_event_injects_authenticated_user_email(monkeypatch):
    captured = {}

    monkeypatch.setattr(analytics_routes, "_optional_user_from_authorization", lambda _auth: _resolved_user())
    monkeypatch.setattr(analytics_routes, "capture_analytics_event", lambda **kwargs: captured.update(kwargs) or True)

    payload = analytics_routes.AnalyticsEventIngestRequest(
        event_name="board_viewed",
        session_id="session-1",
        properties={"surface": "scan", "user_email": "spoofed@example.com"},
    )

    response = await analytics_routes.ingest_analytics_event(
        payload=payload,
        x_session_id=None,
        authorization="Bearer token",
    )

    assert response["ok"] is True
    assert response["inserted"] is True
    assert captured["user_id"] == "user-123"
    assert captured["properties"]["surface"] == "scan"
    assert captured["properties"]["user_email"] == "real@example.com"


@pytest.mark.asyncio
async def test_ingest_analytics_event_does_not_add_email_for_anonymous(monkeypatch):
    captured = {}

    monkeypatch.setattr(analytics_routes, "_optional_user_from_authorization", lambda _auth: _anonymous_user())
    monkeypatch.setattr(analytics_routes, "capture_analytics_event", lambda **kwargs: captured.update(kwargs) or True)

    payload = analytics_routes.AnalyticsEventIngestRequest(
        event_name="board_viewed",
        session_id="session-2",
        properties={"surface": "scan"},
    )

    response = await analytics_routes.ingest_analytics_event(
        payload=payload,
        x_session_id=None,
        authorization=None,
    )

    assert response["ok"] is True
    assert response["inserted"] is True
    assert captured["user_id"] is None
    assert "user_email" not in captured["properties"]


@pytest.mark.asyncio
async def test_optional_user_from_authorization_extracts_id_and_email(monkeypatch):
    dummy_user = SimpleNamespace(id="abc-123", email="person@example.com")
    dummy_response = SimpleNamespace(user=dummy_user)

    async def _fake_threadpool(func, token):
        return func(token)

    monkeypatch.setattr(
        analytics_routes,
        "get_db",
        lambda: SimpleNamespace(auth=SimpleNamespace(get_user=lambda _token: dummy_response)),
    )
    monkeypatch.setattr(analytics_routes, "run_in_threadpool", _fake_threadpool)

    user_id, user_email = await analytics_routes._optional_user_from_authorization("Bearer abc")

    assert user_id == "abc-123"
    assert user_email == "person@example.com"


async def _resolved_user():
    return "user-123", "real@example.com"


async def _anonymous_user():
    return None, None
