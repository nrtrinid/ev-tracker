"""Shared fixtures for backend unit tests and integration test helpers."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient

from calculations import DEFAULT_VIG
from .test_utils import ensure_supabase_stub

__all__ = ["DEFAULT_VIG"]


# Test user for integration tests. Must exist in auth.users when using a real test Supabase
# (create in Supabase Auth and set TEST_USER_ID, or use this default if that UUID exists).
TEST_USER_ID = os.getenv("TEST_USER_ID", "00000000-0000-0000-0000-000000000001")


async def fake_get_current_user():
    """Override for integration tests: return fixed user so we don't need a real JWT."""
    return {"id": TEST_USER_ID, "email": "test@example.com"}


# ---------- Integration-only fixtures (lazy-import main so unit tests don't load DB) ----------


@pytest.fixture
def public_client():
    """TestClient with no auth override. Use for unauthenticated behavior (e.g. 401)."""
    ensure_supabase_stub()
    from main import app
    client = TestClient(app)
    return client


@pytest.fixture
def auth_client():
    """TestClient with get_current_user overridden to return fixed test user."""
    ensure_supabase_stub()
    from main import app
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = fake_get_current_user
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def run_id():
    """Short unique string per test for isolating created data (event/notes)."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
def tracker(auth_client):
    """Tracks created bet and transaction IDs; teardown deletes them via API."""
    class Tracker:
        def __init__(self):
            self.bet_ids = []
            self.tx_ids = []

    t = Tracker()
    yield t
    for bet_id in t.bet_ids:
        try:
            auth_client.delete(f"/bets/{bet_id}")
        except Exception:
            pass
    for tx_id in t.tx_ids:
        try:
            auth_client.delete(f"/transactions/{tx_id}")
        except Exception:
            pass
