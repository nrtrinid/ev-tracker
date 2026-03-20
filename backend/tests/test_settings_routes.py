from types import SimpleNamespace

from routes.settings_routes import (
    build_settings_update_payload,
    get_settings_impl,
    update_settings_impl,
)


def test_build_settings_update_payload_includes_only_present_fields():
    settings = SimpleNamespace(
        k_factor=0.65,
        default_stake=None,
        preferred_sportsbooks=["DraftKings"],
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
        "k_factor_mode": "baseline",
        "k_factor_smoothing": 700.0,
        "k_factor_clamp_max": 0.9,
    }


class _FakeDB:
    def __init__(self):
        self.updated_payload = None
        self.updated_user_id = None

    def table(self, name):
        assert name == "settings"
        return self

    def update(self, payload):
        self.updated_payload = payload
        return self

    def eq(self, field, value):
        assert field == "user_id"
        self.updated_user_id = value
        return self

    def execute(self):
        return {"ok": True}


def test_get_settings_impl_uses_callbacks():
    db = _FakeDB()
    calls = []

    out = get_settings_impl(
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, user_id: {"id": user_id},
        build_settings_response=lambda _db, user_id, settings: calls.append((user_id, settings)) or {"ok": True},
    )

    assert out == {"ok": True}
    assert calls == [("u1", {"id": "u1"})]


def test_update_settings_impl_updates_when_payload_present_and_returns_built_response():
    db = _FakeDB()
    settings_reads = []

    def _get_user_settings(_db, user_id):
        settings_reads.append(user_id)
        return {"k_factor": 0.5}

    out = update_settings_impl(
        settings_update=SimpleNamespace(dummy=True),
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=_get_user_settings,
        build_settings_response=lambda _db, _user_id, settings: {"settings": settings},
        build_update_payload=lambda _settings: {"k_factor": 0.7},
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
    )

    assert out == {"settings": {"k_factor": 0.5}}
    assert settings_reads == ["u1", "u1"]
    assert db.updated_user_id == "u1"
    assert db.updated_payload == {
        "k_factor": 0.7,
        "updated_at": "2026-03-19T00:00:00Z",
    }


def test_update_settings_impl_skips_db_update_when_payload_empty():
    db = _FakeDB()

    update_settings_impl(
        settings_update=SimpleNamespace(dummy=True),
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, _user_id: {"k_factor": 0.5},
        build_settings_response=lambda _db, _user_id, settings: settings,
        build_update_payload=lambda _settings: {},
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
    )

    assert db.updated_payload is None
    assert db.updated_user_id is None
