from datetime import UTC, datetime, timedelta

import pytest

from .test_utils import import_main_for_tests


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self.selected_fields = None
        self.eq_calls = []

    def select(self, fields):
        self.selected_fields = fields
        return self

    def eq(self, field, value):
        self.eq_calls.append((field, value))
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows})()


class _FakeDB:
    def __init__(self, rows):
        self.query = _FakeQuery(rows)

    def table(self, name):
        assert name == "bets"
        return self.query


def test_player_props_surface_supports_only_nba(monkeypatch):
    main = import_main_for_tests(monkeypatch)

    assert main._scanner_supported_sports("player_props") == ["basketball_nba"]


def test_compute_k_user_filters_bonus_bets_in_python(monkeypatch):
    main = import_main_for_tests(monkeypatch)
    now = datetime.now(UTC)
    db = _FakeDB(
        [
            {
                "stake": 100.0,
                "result": "win",
                "win_payout": 80.0,
                "payout_override": None,
                "promo_type": "bonus_bet",
                "created_at": now.isoformat(),
            },
            {
                "stake": 50.0,
                "result": "loss",
                "win_payout": 0.0,
                "payout_override": None,
                "promo_type": "bonus_bet",
                "created_at": now.isoformat(),
            },
            {
                "stake": 20.0,
                "result": "pending",
                "win_payout": 10.0,
                "payout_override": None,
                "promo_type": "bonus_bet",
                "created_at": now.isoformat(),
            },
            {
                "stake": 40.0,
                "result": "win",
                "win_payout": 30.0,
                "payout_override": None,
                "promo_type": "standard",
                "created_at": now.isoformat(),
            },
            {
                "stake": 60.0,
                "result": "win",
                "win_payout": 45.0,
                "payout_override": None,
                "promo_type": "bonus_bet",
                "created_at": (now - timedelta(days=1200)).isoformat(),
            },
        ]
    )

    out = main.compute_k_user(db, "user-1")

    assert (
        db.query.selected_fields
        == "promo_type,result,created_at,stake,payout_override,win_payout"
    )
    assert db.query.eq_calls == [("user_id", "user-1")]
    assert out["bonus_stake_settled"] == pytest.approx(150.0, abs=0.01)
    assert out["k_obs"] == pytest.approx(80.0 / 150.0, abs=1e-6)
