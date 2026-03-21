import importlib
from datetime import datetime, timedelta, timezone

import pytest

from .test_utils import ensure_supabase_stub, reload_service_module


def _reload_odds_api():
    ensure_supabase_stub()
    mod = reload_service_module("odds_api")
    return importlib.reload(mod)


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, mode="select", payload=None):
        self._db = db
        self._mode = mode
        self._payload = payload or {}
        self._eq_filters = {}

    @property
    def not_(self):
        return self

    def select(self, _fields):
        return self

    def eq(self, key, value):
        self._eq_filters[key] = value
        return self

    def is_(self, _key, _value):
        return self

    def gt(self, _key, _value):
        return self

    def lte(self, _key, _value):
        return self

    def update(self, payload):
        return _Query(self._db, mode="update", payload=payload)

    def execute(self):
        if self._mode == "select":
            return _Resp([dict(row) for row in self._db.rows])

        target_id = self._eq_filters.get("id")
        for row in self._db.rows:
            if target_id is None or row.get("id") == target_id:
                row.update(self._payload)
                self._db.updates.append({"id": row.get("id"), **self._payload})
        return _Resp([])


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def table(self, name):
        assert name == "bets"
        return _Query(self)


def _bookmaker_event(book_key, home, away, home_price, away_price):
    return {
        "key": book_key,
        "markets": [{
            "key": "h2h",
            "outcomes": [
                {"name": home, "price": home_price},
                {"name": away, "price": away_price},
            ],
        }],
    }


def test_update_clv_snapshots_prefers_event_id_over_time():
    mod = _reload_odds_api()
    db = _DB([
        {
            "id": 10,
            "result": "pending",
            "clv_team": "Team A",
            "commence_time": "2026-03-18T02:00:00Z",
            "clv_event_id": "evt_100",
        }
    ])

    sides = [
        {
            "event_id": "evt_100",
            "commence_time": "2026-03-18T05:00:00Z",
            "team": "Team A",
            "pinnacle_odds": -105,
        },
        {
            "commence_time": "2026-03-18T02:00:00Z",
            "team": "Team A",
            "pinnacle_odds": -120,
        },
    ]

    updated = mod.update_clv_snapshots(sides, db)
    assert updated == 1
    assert db.rows[0]["pinnacle_odds_at_close"] == -105


def test_update_clv_snapshots_falls_back_to_time_team_when_id_misses():
    mod = _reload_odds_api()
    db = _DB([
        {
            "id": 20,
            "result": "pending",
            "clv_team": "Team B",
            "commence_time": "2026-03-18T03:00:00Z",
            "clv_event_id": "evt_missing",
        }
    ])

    sides = [
        {
            "commence_time": "2026-03-18T03:00:00Z",
            "team": "Team B",
            "pinnacle_odds": 140,
        }
    ]

    updated = mod.update_clv_snapshots(sides, db)
    assert updated == 1
    assert db.rows[0]["pinnacle_odds_at_close"] == 140


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_prefers_event_id(monkeypatch):
    mod = _reload_odds_api()
    start_soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB([
        {
            "id": 30,
            "result": "pending",
            "clv_sport_key": "basketball_nba",
            "clv_team": "Team C",
            "commence_time": start_soon,
            "clv_event_id": "evt_300",
            "pinnacle_odds_at_close": None,
        }
    ])

    async def _fake_fetch_odds(_sport_key, source="jit_clv"):
        event = {
            "id": "evt_300",
            "home_team": "Team C",
            "away_team": "Team D",
            "commence_time": "2030-01-01T00:00:00Z",
            "bookmakers": [
                _bookmaker_event(mod.SHARP_BOOK, "Team C", "Team D", -110, 100),
            ],
        }
        return [event], None

    monkeypatch.setattr(mod, "fetch_odds", _fake_fetch_odds)

    updated = await mod.run_jit_clv_snatcher(db)
    assert updated == 1
    assert db.rows[0]["pinnacle_odds_at_close"] == -110
