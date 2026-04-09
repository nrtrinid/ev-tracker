import importlib
from datetime import datetime, timedelta, timezone

import pytest

from .test_utils import ensure_supabase_stub, reload_service_module


def _reload_odds_api():
    ensure_supabase_stub()
    mod = reload_service_module("odds_api")
    return importlib.reload(mod)


def _reload_clv_tracking():
    ensure_supabase_stub()
    mod = reload_service_module("clv_tracking")
    return importlib.reload(mod)


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table_name, *, mode="select", payload=None, filters=None):
        self._db = db
        self._table_name = table_name
        self._mode = mode
        self._payload = payload or {}
        self._filters = list(filters or [])
        self._invert_next = False

    @property
    def not_(self):
        self._invert_next = True
        return self

    def _append_filter(self, predicate):
        if self._invert_next:
            original = predicate
            predicate = lambda row: not original(row)
            self._invert_next = False
        self._filters.append(predicate)
        return self

    def select(self, _fields):
        return self

    def eq(self, key, value):
        return self._append_filter(lambda row: row.get(key) == value)

    def in_(self, key, values):
        value_set = set(values)
        return self._append_filter(lambda row: row.get(key) in value_set)

    def is_(self, key, value):
        if value == "null":
            return self._append_filter(lambda row: row.get(key) is None)
        return self._append_filter(lambda row: row.get(key) == value)

    def gt(self, key, value):
        return self._append_filter(lambda row: row.get(key) is not None and row.get(key) > value)

    def lte(self, key, value):
        return self._append_filter(lambda row: row.get(key) is not None and row.get(key) <= value)

    def update(self, payload):
        return _Query(
            self._db,
            self._table_name,
            mode="update",
            payload=payload,
            filters=self._filters,
        )

    def execute(self):
        rows = self._db.tables[self._table_name]
        matched = [row for row in rows if all(predicate(row) for predicate in self._filters)]

        if self._mode == "select":
            return _Resp([dict(row) for row in matched])

        for row in matched:
            row.update(self._payload)
            self._db.updates[self._table_name].append({"id": row.get("id"), **self._payload})
        return _Resp([])


class _DB:
    def __init__(self, *, bets=None, scan_opportunities=None, missing_scan_opportunities=False):
        self.tables = {
            "bets": list(bets or []),
            "scan_opportunities": list(scan_opportunities or []),
        }
        self.updates = {"bets": [], "scan_opportunities": []}
        self.missing_scan_opportunities = missing_scan_opportunities

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"Unexpected table: {name}")
        if name == "scan_opportunities" and self.missing_scan_opportunities:
            raise RuntimeError("PGRST205 scan_opportunities schema cache stale")
        return _Query(self, name)


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


def test_update_clv_snapshots_prefers_event_id_and_updates_latest_only_outside_close_window():
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 10,
                "result": "pending",
                "clv_team": "Team A",
                "commence_time": commence_time,
                "clv_event_id": "evt_100",
                "clv_sport_key": "basketball_nba",
                "pinnacle_odds_at_close": None,
            }
        ]
    )

    sides = [
        {
            "event_id": "evt_100",
            "commence_time": "2030-03-18T05:00:00Z",
            "team": "Team A",
            "pinnacle_odds": -105,
        },
        {
            "commence_time": commence_time,
            "team": "Team A",
            "pinnacle_odds": -120,
        },
    ]

    updated = mod.update_clv_snapshots(sides, db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -105
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] is None


def test_update_clv_snapshots_falls_back_to_time_team_when_event_id_misses():
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 20,
                "result": "pending",
                "clv_team": "Team B",
                "commence_time": commence_time,
                "clv_event_id": "evt_missing",
                "clv_sport_key": "basketball_nba",
                "pinnacle_odds_at_close": None,
            }
        ]
    )

    sides = [
        {
            "commence_time": commence_time,
            "team": "Team B",
            "pinnacle_odds": 140,
        }
    ]

    updated = mod.update_clv_snapshots(sides, db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == 140
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] is None


def test_update_clv_snapshots_preserves_existing_close_and_refreshes_latest():
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 25,
                "result": "pending",
                "clv_team": "Team Locked",
                "commence_time": commence_time,
                "clv_event_id": "evt_locked",
                "clv_sport_key": "basketball_nba",
                "pinnacle_odds_at_close": 180,
            }
        ]
    )

    sides = [
        {
            "event_id": "evt_locked",
            "commence_time": commence_time,
            "team": "Team Locked",
            "pinnacle_odds": 125,
        }
    ]

    updated = mod.update_clv_snapshots(sides, db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == 125
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == 180


def test_update_clv_snapshots_can_capture_close_inside_window():
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 26,
                "result": "pending",
                "clv_team": "Team Close",
                "commence_time": commence_time,
                "clv_event_id": "evt_close",
                "clv_sport_key": "basketball_nba",
                "pinnacle_odds_at_close": None,
            }
        ]
    )

    sides = [
        {
            "event_id": "evt_close",
            "commence_time": commence_time,
            "team": "Team Close",
            "pinnacle_odds": -110,
        }
    ]

    updated = mod.update_clv_snapshots(sides, db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -110
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -110
    assert db.tables["bets"][0]["clv_updated_at"] is not None


def test_update_clv_snapshots_repairs_invalid_early_close_inside_window():
    mod = _reload_clv_tracking()
    now = datetime(2026, 3, 23, 18, 35, tzinfo=timezone.utc)
    commence_time = "2026-03-23T18:40:00Z"
    db = _DB(
        bets=[
            {
                "id": 27,
                "result": "pending",
                "clv_team": "Team Repair",
                "commence_time": commence_time,
                "clv_event_id": "evt_repair",
                "clv_sport_key": "basketball_nba",
                "odds_american": -118,
                "pinnacle_odds_at_close": -130,
                "clv_updated_at": "2026-03-22T22:37:00Z",
            }
        ]
    )

    counts = mod.update_bet_reference_snapshots(
        db,
        sides=[
            {
                "event_id": "evt_repair",
                "commence_time": commence_time,
                "team": "Team Repair",
                "pinnacle_odds": -119,
            }
        ],
        allow_close=True,
        now=now,
    )

    assert counts["latest_updated"] == 1
    assert counts["close_updated"] == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -119
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -119
    assert db.tables["bets"][0]["clv_updated_at"] == now.isoformat()


def test_update_scan_opportunity_reference_snapshots_updates_latest_without_close_outside_window():
    mod = _reload_clv_tracking()
    now = datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc)
    commence_time = "2026-03-23T15:00:00Z"
    db = _DB(
        scan_opportunities=[
            {
                "id": "opp-1",
                "sport": "basketball_nba",
                "team": "Team X",
                "commence_time": commence_time,
                "event_id": "evt-x",
                "first_book_odds": 155,
                "reference_odds_at_close": None,
            }
        ]
    )

    counts = mod.update_scan_opportunity_reference_snapshots(
        db,
        sides=[
            {
                "sport": "basketball_nba",
                "event_id": "evt-x",
                "commence_time": "2026-03-23T16:00:00Z",
                "team": "Team X",
                "pinnacle_odds": 135,
            }
        ],
        allow_close=True,
        now=now,
    )

    assert counts["latest_updated"] == 1
    assert counts["close_updated"] == 0
    assert db.tables["scan_opportunities"][0]["latest_reference_odds"] == 135
    assert db.tables["scan_opportunities"][0]["reference_odds_at_close"] is None


def test_update_scan_opportunity_reference_snapshots_updates_prop_latest_without_close_outside_window():
    mod = _reload_clv_tracking()
    now = datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc)
    commence_time = "2026-03-23T15:00:00Z"
    db = _DB(
        scan_opportunities=[
            {
                "id": "opp-prop-1",
                "surface": "player_props",
                "sport": "basketball_nba",
                "team": "Denver Nuggets",
                "commence_time": commence_time,
                "event_id": "evt-prop",
                "player_name": "Nikola Jokic",
                "source_market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "first_book_odds": 105,
                "reference_odds_at_close": None,
            }
        ]
    )

    counts = mod.update_scan_opportunity_reference_snapshots(
        db,
        sides=[
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop",
                "commence_time": "2026-03-23T16:00:00Z",
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "reference_odds": -112,
            }
        ],
        allow_close=True,
        now=now,
    )

    assert counts["latest_updated"] == 1
    assert counts["close_updated"] == 0
    assert db.tables["scan_opportunities"][0]["latest_reference_odds"] == -112
    assert db.tables["scan_opportunities"][0]["reference_odds_at_close"] is None


def test_update_scan_opportunity_reference_snapshots_captures_prop_close_inside_window_and_ignores_wrong_line():
    mod = _reload_clv_tracking()
    now = datetime(2026, 3, 23, 14, 50, tzinfo=timezone.utc)
    commence_time = "2026-03-23T15:00:00Z"
    db = _DB(
        scan_opportunities=[
            {
                "id": "opp-prop-2",
                "surface": "player_props",
                "sport": "basketball_nba",
                "team": "Denver Nuggets",
                "commence_time": commence_time,
                "event_id": "evt-prop-close",
                "player_name": "Nikola Jokic",
                "source_market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "first_book_odds": 105,
                "reference_odds_at_close": None,
            }
        ]
    )

    counts = mod.update_scan_opportunity_reference_snapshots(
        db,
        sides=[
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-close",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 25.5,
                "reference_odds": -115,
            },
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-close",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "reference_odds": -110,
            },
        ],
        allow_close=True,
        now=now,
    )

    assert counts["latest_updated"] == 1
    assert counts["close_updated"] == 1
    assert db.tables["scan_opportunities"][0]["latest_reference_odds"] == -110
    assert db.tables["scan_opportunities"][0]["reference_odds_at_close"] == -110
    assert db.tables["scan_opportunities"][0]["clv_ev_percent"] is not None
    assert db.tables["scan_opportunities"][0]["beat_close"] is not None


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_updates_bets_and_scan_opportunities(monkeypatch):
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 30,
                "result": "pending",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Team C",
                "commence_time": commence_time,
                "clv_event_id": "evt_300",
                "pinnacle_odds_at_close": None,
            }
        ],
        scan_opportunities=[
            {
                "id": "opp-300",
                "sport": "basketball_nba",
                "team": "Team D",
                "commence_time": commence_time,
                "event_id": "evt_300",
                "first_book_odds": 130,
                "reference_odds_at_close": None,
            }
        ],
    )

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

    assert updated == 2
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -110
    assert db.tables["scan_opportunities"][0]["reference_odds_at_close"] == 100
    assert db.tables["scan_opportunities"][0]["clv_ev_percent"] is not None
    assert db.tables["scan_opportunities"][0]["beat_close"] is not None


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_repairs_stale_close_snapshots(monkeypatch):
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 32,
                "result": "pending",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Team Repair",
                "commence_time": commence_time,
                "clv_event_id": "evt_repair_jit",
                "pinnacle_odds_at_close": -130,
                "clv_updated_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            }
        ],
        scan_opportunities=[
            {
                "id": "opp-repair",
                "sport": "basketball_nba",
                "team": "Team Repair Opp",
                "commence_time": commence_time,
                "event_id": "evt_repair_jit",
                "first_book_odds": 130,
                "reference_odds_at_close": 100,
                "close_captured_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            }
        ],
    )

    async def _fake_fetch_odds(_sport_key, source="jit_clv"):
        event = {
            "id": "evt_repair_jit",
            "home_team": "Team Repair",
            "away_team": "Team Repair Opp",
            "commence_time": commence_time,
            "bookmakers": [
                _bookmaker_event(mod.SHARP_BOOK, "Team Repair", "Team Repair Opp", -119, 101),
            ],
        }
        return [event], None

    monkeypatch.setattr(mod, "fetch_odds", _fake_fetch_odds)

    updated = await mod.run_jit_clv_snatcher(db)

    assert updated == 2
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -119
    assert db.tables["scan_opportunities"][0]["reference_odds_at_close"] == 101
    assert db.tables["bets"][0]["clv_updated_at"] is not None
    assert db.tables["scan_opportunities"][0]["close_captured_at"] is not None


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_still_updates_bets_when_scan_opportunities_table_is_missing(monkeypatch):
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 31,
                "result": "pending",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Team E",
                "commence_time": commence_time,
                "clv_event_id": "evt_301",
                "pinnacle_odds_at_close": None,
            }
        ],
        missing_scan_opportunities=True,
    )

    async def _fake_fetch_odds(_sport_key, source="jit_clv"):
        event = {
            "id": "evt_301",
            "home_team": "Team E",
            "away_team": "Team F",
            "commence_time": "2030-01-01T00:00:00Z",
            "bookmakers": [
                _bookmaker_event(mod.SHARP_BOOK, "Team E", "Team F", -108, 102),
            ],
        }
        return [event], None

    monkeypatch.setattr(mod, "fetch_odds", _fake_fetch_odds)

    updated = await mod.run_jit_clv_snatcher(db)

    assert updated == 1
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -108
