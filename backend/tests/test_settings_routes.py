from types import SimpleNamespace
from fastapi import HTTPException

from .test_utils import ensure_supabase_stub

ensure_supabase_stub()

from models import OnboardingEventRequest
from routes.settings_routes import (
    apply_onboarding_event_impl,
    build_settings_update_payload,
    get_onboarding_state_impl,
    get_settings_impl,
    update_settings_impl,
)


def test_build_settings_update_payload_includes_only_present_fields():
    settings = SimpleNamespace(
        k_factor=0.65,
        default_stake=None,
        preferred_sportsbooks=["DraftKings"],
        kelly_multiplier=0.25,
        bankroll_override=1500.0,
        use_computed_bankroll=False,
        k_factor_mode="baseline",
        k_factor_min_stake=None,
        k_factor_smoothing=700.0,
        k_factor_clamp_min=None,
        k_factor_clamp_max=0.9,
    )

    payload = build_settings_update_payload(settings)

    assert payload == {
        "k_factor": 0.65,
        "preferred_sportsbooks": ["DraftKings"],
        "kelly_multiplier": 0.25,
        "bankroll_override": 1500.0,
        "use_computed_bankroll": False,
        "k_factor_mode": "baseline",
        "k_factor_smoothing": 700.0,
        "k_factor_clamp_max": 0.9,
    }


def test_build_settings_update_payload_rejects_direct_onboarding_blob_updates():
    settings = SimpleNamespace(
        k_factor=None,
        default_stake=None,
        preferred_sportsbooks=None,
        kelly_multiplier=None,
        bankroll_override=None,
        use_computed_bankroll=None,
        k_factor_mode=None,
        k_factor_min_stake=None,
        k_factor_smoothing=None,
        k_factor_clamp_min=None,
        k_factor_clamp_max=None,
        onboarding_state={"version": 1, "completed": [], "dismissed": []},
    )

    try:
        build_settings_update_payload(settings)
    except ValueError as exc:
        assert "onboarding_state updates must use /onboarding/events" in str(exc)
    else:
        raise AssertionError("Expected ValueError for direct onboarding_state update")


class _FakeDB:
    def __init__(self):
        self.updated_payload = None
        self.updated_user_id = None
        self.updated_payloads = []
        self.updated_user_ids = []

    def table(self, name):
        assert name == "settings"
        return self

    def update(self, payload):
        self.updated_payload = payload
        self.updated_payloads.append(payload)
        return self

    def eq(self, field, value):
        assert field == "user_id"
        self.updated_user_id = value
        self.updated_user_ids.append(value)
        return self

    def execute(self):
        return {"ok": True}


def test_get_settings_impl_uses_callbacks():
    db = _FakeDB()
    calls = []
    onboarding_state = {
        "version": 2,
        "completed": [],
        "dismissed": [],
        "last_seen_at": "2026-03-19T00:00:00Z",
    }

    out = get_settings_impl(
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, user_id: {"id": user_id, "onboarding_state": onboarding_state},
        build_settings_response=lambda _db, user_id, settings: calls.append((user_id, settings)) or {"ok": True},
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
    )

    assert out == {"ok": True}
    assert calls == [("u1", {"id": "u1", "onboarding_state": onboarding_state})]


def test_update_settings_impl_updates_when_payload_present_and_returns_built_response():
    db = _FakeDB()
    settings_reads = []

    def _get_user_settings(_db, user_id):
        settings_reads.append(user_id)
        return {
            "k_factor": 0.5,
            "onboarding_state": {
                "version": 2,
                "completed": [],
                "dismissed": [],
                "last_seen_at": "2026-03-19T00:00:00Z",
            },
        }

    out = update_settings_impl(
        settings_update=SimpleNamespace(dummy=True),
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=_get_user_settings,
        build_settings_response=lambda _db, _user_id, settings: {"settings": settings},
        build_update_payload=lambda _settings: {"k_factor": 0.7},
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
    )

    assert out == {
        "settings": {
            "k_factor": 0.5,
            "onboarding_state": {
                "version": 2,
                "completed": [],
                "dismissed": [],
                "last_seen_at": "2026-03-19T00:00:00Z",
            },
        }
    }
    assert settings_reads == ["u1", "u1"]
    assert db.updated_user_id == "u1"
    assert db.updated_payloads == [
        {
            "k_factor": 0.7,
            "updated_at": "2026-03-19T00:00:00Z",
        }
    ]


def test_update_settings_impl_skips_db_update_when_payload_empty():
    db = _FakeDB()

    update_settings_impl(
        settings_update=SimpleNamespace(dummy=True),
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, _user_id: {
            "k_factor": 0.5,
            "onboarding_state": {
                "version": 2,
                "completed": [],
                "dismissed": [],
                "last_seen_at": "2026-03-19T00:00:00Z",
            },
        },
        build_settings_response=lambda _db, _user_id, settings: settings,
        build_update_payload=lambda _settings: {},
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
    )

    assert db.updated_payload is None
    assert db.updated_user_id is None


def test_get_onboarding_state_impl_resets_legacy_state_to_v2_and_persists():
    db = _FakeDB()

    out = get_onboarding_state_impl(
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, _user_id: {
            "onboarding_state": {
                "version": 1,
                "completed": ["tutorial_scanner_straight_bets"],
                "dismissed": [],
                "last_seen_at": None,
            }
        },
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
    )

    assert out == {
        "version": 2,
        "completed": [],
        "dismissed": [],
        "last_seen_at": "2026-03-19T00:00:00Z",
    }
    assert db.updated_payloads == [
        {
            "onboarding_state": {
                "version": 2,
                "completed": [],
                "dismissed": [],
                "last_seen_at": "2026-03-19T00:00:00Z",
            },
            "updated_at": "2026-03-19T00:00:00Z",
        }
    ]


def test_apply_onboarding_event_impl_applies_complete_and_persists():
    db = _FakeDB()

    out = apply_onboarding_event_impl(
        event=OnboardingEventRequest(event="complete_step", step="tutorial_scanner_straight_bets"),
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, _user_id: {
            "onboarding_state": {
                "version": 2,
                "completed": [],
                "dismissed": [],
                "last_seen_at": "2026-03-18T00:00:00Z",
            }
        },
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
    )

    assert out == {
        "version": 2,
        "completed": ["tutorial_scanner_straight_bets"],
        "dismissed": [],
        "last_seen_at": "2026-03-19T00:00:00Z",
    }
    assert db.updated_payloads == [
        {
            "onboarding_state": {
                "version": 2,
                "completed": ["tutorial_scanner_straight_bets"],
                "dismissed": [],
                "last_seen_at": "2026-03-19T00:00:00Z",
            },
            "updated_at": "2026-03-19T00:00:00Z",
        }
    ]


def test_apply_onboarding_event_impl_rejects_missing_step_for_complete():
    db = _FakeDB()

    try:
        apply_onboarding_event_impl(
            event=OnboardingEventRequest(event="complete_step", step=None),
            user={"id": "u1"},
            get_db=lambda: db,
            get_user_settings=lambda _db, _user_id: {
                "onboarding_state": {
                    "version": 2,
                    "completed": [],
                    "dismissed": [],
                    "last_seen_at": "2026-03-18T00:00:00Z",
                }
            },
            utc_now_iso=lambda: "2026-03-19T00:00:00Z",
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "step is required" in str(exc.detail)
    else:
        raise AssertionError("Expected onboarding complete_step to reject missing step")
