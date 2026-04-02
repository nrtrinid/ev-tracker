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
    def __init__(
        self,
        *,
        bets=None,
        scan_opportunities=None,
        scan_opportunity_model_evaluations=None,
        missing_scan_opportunities=False,
    ):
        self.tables = {
            "bets": list(bets or []),
            "scan_opportunities": list(scan_opportunities or []),
            "scan_opportunity_model_evaluations": list(scan_opportunity_model_evaluations or []),
        }
        self.updates = {"bets": [], "scan_opportunities": [], "scan_opportunity_model_evaluations": []}
        self.missing_scan_opportunities = missing_scan_opportunities

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"Unexpected table: {name}")
        if name == "scan_opportunities" and self.missing_scan_opportunities:
            raise RuntimeError("PGRST205 scan_opportunities schema cache stale")
        return _Query(self, name)


def _bookmaker_event(book_key, home, away, home_price=None, away_price=None, *, spread=None, total=None):
    markets = []
    if home_price is not None and away_price is not None:
        markets.append({
            "key": "h2h",
            "outcomes": [
                {"name": home, "price": home_price},
                {"name": away, "price": away_price},
            ],
        })
    if isinstance(spread, dict):
        markets.append({
            "key": "spreads",
            "outcomes": [
                {"name": home, "price": spread["home_price"], "point": spread["home_line"]},
                {"name": away, "price": spread["away_price"], "point": spread["away_line"]},
            ],
        })
    if isinstance(total, dict):
        markets.append({
            "key": "totals",
            "outcomes": [
                {"name": "Over", "price": total["over_price"], "point": total["line"]},
                {"name": "Under", "price": total["under_price"], "point": total["line"]},
            ],
        })
    return {
        "key": book_key,
        "markets": markets,
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
    assert all("beat_close" not in update for update in db.updates["bets"])
    assert all("clv_ev_percent" not in update for update in db.updates["bets"])


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

    assert counts == {"latest_updated": 1, "close_updated": 0}
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

    assert counts == {"latest_updated": 1, "close_updated": 0}
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

    assert counts == {"latest_updated": 1, "close_updated": 1}
    assert db.tables["scan_opportunities"][0]["latest_reference_odds"] == -110
    assert db.tables["scan_opportunities"][0]["reference_odds_at_close"] == -110
    assert db.tables["scan_opportunities"][0]["clv_ev_percent"] is not None
    assert db.tables["scan_opportunities"][0]["beat_close"] is not None


def test_update_scan_opportunity_reference_snapshots_prefers_paired_prop_close_when_opposing_side_exists():
    mod = _reload_clv_tracking()
    now = datetime(2026, 3, 23, 14, 50, tzinfo=timezone.utc)
    commence_time = "2026-03-23T15:00:00Z"
    db = _DB(
        scan_opportunities=[
            {
                "id": "opp-prop-paired",
                "opportunity_key": "player_props|basketball_nba|id:evt-prop-paired|player_points|nikola jokic|over|24.5|fanduel",
                "surface": "player_props",
                "sport": "basketball_nba",
                "team": "Denver Nuggets",
                "commence_time": commence_time,
                "event_id": "evt-prop-paired",
                "player_name": "Nikola Jokic",
                "source_market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "first_book_odds": 105,
                "reference_odds_at_close": None,
            }
        ],
        scan_opportunity_model_evaluations=[
            {
                "id": "eval-prop-paired",
                "opportunity_key": "player_props|basketball_nba|id:evt-prop-paired|player_points|nikola jokic|over|24.5|fanduel",
                "model_key": "props_v1_live",
                "first_true_prob": 0.52,
                "last_true_prob": 0.52,
                "first_book_odds": 105,
                "last_book_odds": 105,
            }
        ],
    )

    counts = mod.update_scan_opportunity_reference_snapshots(
        db,
        sides=[
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-paired",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "reference_odds": -112,
            },
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-paired",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "under",
                "line_value": 24.5,
                "reference_odds": -108,
            },
        ],
        allow_close=True,
        now=now,
    )

    assert counts == {"latest_updated": 1, "close_updated": 1}
    parent = db.tables["scan_opportunities"][0]
    assert parent["reference_odds_at_close"] == -112
    assert parent["close_opposing_reference_odds"] == -108
    assert parent["close_quality"] == "paired"
    assert parent["close_true_prob"] is not None
    evaluation = db.tables["scan_opportunity_model_evaluations"][0]
    assert evaluation["close_reference_odds"] == -112
    assert evaluation["close_opposing_reference_odds"] == -108
    assert evaluation["close_quality"] == "paired"
    assert evaluation["first_brier_score"] is not None
    assert evaluation["first_log_loss"] is not None


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


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_updates_player_prop_bets_without_research_rows(monkeypatch):
    mod = _reload_odds_api()
    import services.player_props as player_props

    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 40,
                "result": "pending",
                "surface": "player_props",
                "clv_sport_key": "basketball_nba",
                "source_event_id": "evt-prop-jit",
                "source_market_key": "player_points",
                "participant_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "odds_american": 105,
                "commence_time": commence_time,
                "pinnacle_odds_at_close": None,
            }
        ],
    )

    async def _fake_fetch_prop_market_for_event(*, sport, event_id, markets, source):
        assert sport == "basketball_nba"
        assert event_id == "evt-prop-jit"
        assert markets == ["player_points"]
        assert source == "jit_clv_props"
        return {"id": event_id, "commence_time": commence_time}, None

    def _fake_parse_prop_sides(**kwargs):
        return [
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-jit",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "reference_odds": -112,
            }
        ]

    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=True)
    monkeypatch.setattr(player_props, "_parse_prop_sides", _fake_parse_prop_sides, raising=True)

    updated = await mod.run_jit_clv_snatcher(db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -112
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -112
    assert db.tables["bets"][0]["clv_updated_at"] is not None


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_uses_looser_prop_clv_gate_than_surface_scan(monkeypatch):
    mod = _reload_odds_api()
    import services.player_props as player_props

    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 41,
                "result": "pending",
                "surface": "player_props",
                "clv_sport_key": "basketball_nba",
                "source_event_id": "evt-prop-gate",
                "source_market_key": "player_points",
                "participant_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "odds_american": 105,
                "commence_time": commence_time,
                "pinnacle_odds_at_close": None,
            }
        ],
    )

    async def _fake_fetch_prop_market_for_event(*, sport, event_id, markets, source):
        return {"id": event_id, "commence_time": commence_time}, None

    def _fake_parse_prop_sides(**kwargs):
        assert kwargs["min_reference_bookmakers"] == 1
        return [
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-gate",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "reference_odds": -111,
            }
        ]

    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=True)
    monkeypatch.setattr(player_props, "_parse_prop_sides", _fake_parse_prop_sides, raising=True)
    monkeypatch.setattr(player_props, "get_player_prop_min_reference_bookmakers", lambda: 3, raising=True)
    monkeypatch.setattr(player_props, "get_player_prop_clv_min_reference_bookmakers", lambda: 1, raising=True)

    updated = await mod.run_jit_clv_snatcher(db)

    assert updated == 1
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -111


@pytest.mark.asyncio
async def test_fetch_clv_for_pending_bets_updates_player_prop_bets(monkeypatch):
    mod = _reload_odds_api()
    import services.player_props as player_props

    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 42,
                "result": "pending",
                "surface": "player_props",
                "clv_sport_key": "basketball_nba",
                "source_event_id": "evt-prop-daily",
                "source_market_key": "player_points",
                "participant_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "odds_american": 105,
                "commence_time": commence_time,
                "pinnacle_odds_at_close": None,
            }
        ],
    )

    async def _fake_fetch_prop_market_for_event(*, sport, event_id, markets, source):
        assert source == "clv_daily_props"
        return {"id": event_id, "commence_time": commence_time}, None

    def _fake_parse_prop_sides(**kwargs):
        return [
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-daily",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "reference_odds": -114,
            }
        ]

    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=True)
    monkeypatch.setattr(player_props, "_parse_prop_sides", _fake_parse_prop_sides, raising=True)

    updated = await mod.fetch_clv_for_pending_bets(db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -114
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -114


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_updates_straight_total_bets(monkeypatch):
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 60,
                "result": "pending",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_nba",
                "clv_team": "over",
                "source_market_key": "totals",
                "line_value": 219.5,
                "commence_time": commence_time,
                "clv_event_id": "evt-total-jit",
                "pinnacle_odds_at_close": None,
                "odds_american": -102,
            }
        ],
    )

    async def _fake_fetch_odds(_sport_key, source="jit_clv"):
        event = {
            "id": "evt-total-jit",
            "home_team": "Team Total A",
            "away_team": "Team Total B",
            "commence_time": commence_time,
            "bookmakers": [
                _bookmaker_event(
                    mod.SHARP_BOOK,
                    "Team Total A",
                    "Team Total B",
                    spread={"home_line": -4.5, "away_line": 4.5, "home_price": -110, "away_price": -110},
                    total={"line": 219.5, "over_price": -114, "under_price": -106},
                ),
            ],
        }
        return [event], None

    monkeypatch.setattr(mod, "fetch_odds", _fake_fetch_odds)

    updated = await mod.run_jit_clv_snatcher(db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -114
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -114


@pytest.mark.asyncio
async def test_run_jit_clv_snatcher_updates_straight_spread_bets(monkeypatch):
    mod = _reload_odds_api()
    commence_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 61,
                "result": "pending",
                "surface": "straight_bets",
                "clv_sport_key": "basketball_nba",
                "clv_team": "Team Spread A",
                "source_market_key": "spreads",
                "line_value": -4.5,
                "commence_time": commence_time,
                "clv_event_id": "evt-spread-jit",
                "pinnacle_odds_at_close": None,
                "odds_american": -105,
            }
        ],
    )

    async def _fake_fetch_odds(_sport_key, source="jit_clv"):
        event = {
            "id": "evt-spread-jit",
            "home_team": "Team Spread A",
            "away_team": "Team Spread B",
            "commence_time": commence_time,
            "bookmakers": [
                _bookmaker_event(
                    mod.SHARP_BOOK,
                    "Team Spread A",
                    "Team Spread B",
                    spread={"home_line": -4.5, "away_line": 4.5, "home_price": -118, "away_price": 102},
                    total={"line": 221.5, "over_price": -110, "under_price": -110},
                ),
            ],
        }
        return [event], None

    monkeypatch.setattr(mod, "fetch_odds", _fake_fetch_odds)

    updated = await mod.run_jit_clv_snatcher(db)

    assert updated == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -118
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -118


@pytest.mark.asyncio
async def test_replay_recent_clv_closes_repairs_started_prop_bets(monkeypatch):
    mod = _reload_odds_api()
    import services.player_props as player_props

    commence_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    db = _DB(
        bets=[
            {
                "id": 43,
                "result": "pending",
                "surface": "player_props",
                "clv_sport_key": "basketball_nba",
                "source_event_id": "evt-prop-replay",
                "source_market_key": "player_points",
                "participant_name": "Nikola Jokic",
                "selection_side": "over",
                "line_value": 24.5,
                "odds_american": 105,
                "commence_time": commence_time,
                "pinnacle_odds_at_close": None,
                "clv_updated_at": None,
            }
        ],
    )

    async def _fake_fetch_prop_market_for_event(*, sport, event_id, markets, source):
        assert source == "clv_replay_props"
        return {"id": event_id, "commence_time": commence_time}, None

    def _fake_parse_prop_sides(**kwargs):
        return [
            {
                "surface": "player_props",
                "sport": "basketball_nba",
                "event_id": "evt-prop-replay",
                "commence_time": commence_time,
                "player_name": "Nikola Jokic",
                "market_key": "player_points",
                "selection_side": "over",
                "line_value": 24.5,
                "reference_odds": -115,
            }
        ]

    monkeypatch.setattr(player_props, "_fetch_prop_market_for_event", _fake_fetch_prop_market_for_event, raising=True)
    monkeypatch.setattr(player_props, "_parse_prop_sides", _fake_parse_prop_sides, raising=True)

    summary = await mod.replay_recent_clv_closes(db, lookback_hours=4)

    assert summary["candidate_count"] == 1
    assert summary["close_updated"] == 1
    assert db.tables["bets"][0]["latest_pinnacle_odds"] == -115
    assert db.tables["bets"][0]["pinnacle_odds_at_close"] == -115
