from .test_utils import ensure_supabase_stub

ensure_supabase_stub()

from models import BetCreate, BetUpdate, PromoType
from services import bet_crud


class _Result:
    def __init__(self, data):
        self.data = data


class _CreateBetsQuery:
    def __init__(self, row: dict):
        self._row = row
        self.select_attempted = False

    def insert(self, _payload):
        return self

    def select(self, _fields):
        self.select_attempted = True
        return self

    def eq(self, _field, _value):
        return self

    def execute(self):
        if self.select_attempted:
            raise AssertionError("create_bet_impl should not re-read the inserted row")
        return _Result([self._row])


class _CreateDB:
    def __init__(self, row: dict):
        self.bets = _CreateBetsQuery(row)

    def table(self, name: str):
        assert name == "bets"
        return self.bets


class _UpdateBetsQuery:
    def __init__(self, row: dict):
        self._row = row
        self._operation = None
        self.last_payload = None

    def update(self, payload):
        self._operation = "update"
        self.last_payload = payload
        return self

    def select(self, _fields):
        self._operation = "select"
        return self

    def eq(self, _field, _value):
        return self

    def execute(self):
        if self._operation == "select":
            raise AssertionError("update_bet_impl should not re-read the updated row")
        return _Result([self._row])


class _UpdateDB:
    def __init__(self, row: dict):
        self.bets = _UpdateBetsQuery(row)

    def table(self, name: str):
        assert name == "bets"
        return self.bets


def test_create_bet_impl_avoids_fresh_select_for_standard_bet(monkeypatch):
    inserted_row = {"id": "bet-1", "promo_type": PromoType.STANDARD.value}
    db = _CreateDB(inserted_row)

    monkeypatch.setattr(bet_crud, "get_user_settings", lambda *_args: {"k_factor": 0.78})
    monkeypatch.setattr(bet_crud, "build_bet_response", lambda row, _k_factor: row)

    out = bet_crud.create_bet_impl(
        db,
        {"id": "user-1"},
        BetCreate(
            sport="NBA",
            event="Lakers ML",
            market="ML",
            sportsbook="DraftKings",
            promo_type=PromoType.STANDARD,
            odds_american=-110,
            stake=25,
        ),
    )

    assert out["id"] == "bet-1"


def test_update_bet_impl_avoids_fresh_select_after_lock_update(monkeypatch):
    updated_row = {"id": "bet-2", "promo_type": PromoType.BONUS_BET.value}
    db = _UpdateDB(updated_row)

    monkeypatch.setattr(bet_crud, "get_user_settings", lambda *_args: {"k_factor": 0.78})
    monkeypatch.setattr(
        bet_crud,
        "_lock_ev_for_row",
        lambda _db, _bet_id, _user_id, row, _settings: {
            **row,
            "ev_total_locked": 12.34,
        },
    )
    monkeypatch.setattr(bet_crud, "build_bet_response", lambda row, _k_factor: row)

    out = bet_crud.update_bet_impl(
        db,
        {"id": "user-1"},
        "bet-2",
        BetUpdate(stake=30),
    )

    assert out["id"] == "bet-2"
    assert out["ev_total_locked"] == 12.34


def test_update_bet_impl_allows_explicit_null_for_clearable_fields(monkeypatch):
    updated_row = {"id": "bet-3", "promo_type": PromoType.STANDARD.value}
    db = _UpdateDB(updated_row)

    monkeypatch.setattr(bet_crud, "get_user_settings", lambda *_args: {"k_factor": 0.78})
    monkeypatch.setattr(bet_crud, "_lock_ev_for_row", lambda *_args: updated_row)
    monkeypatch.setattr(bet_crud, "build_bet_response", lambda row, _k_factor: row)

    out = bet_crud.update_bet_impl(
        db,
        {"id": "user-1"},
        "bet-3",
        BetUpdate(
            payout_override=None,
            opposing_odds=None,
            notes=None,
            boost_percent=None,
            winnings_cap=None,
        ),
    )

    assert out["id"] == "bet-3"
    assert db.bets.last_payload["payout_override"] is None
    assert db.bets.last_payload["opposing_odds"] is None
    assert db.bets.last_payload["notes"] is None
    assert db.bets.last_payload["boost_percent"] is None
    assert db.bets.last_payload["winnings_cap"] is None
