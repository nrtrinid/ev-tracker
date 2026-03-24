from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from .test_utils import ensure_supabase_stub

ensure_supabase_stub()

from routes.parlay_routes import (
    create_parlay_slip_impl,
    delete_parlay_slip_impl,
    list_parlay_slips_impl,
    log_parlay_slip_impl,
    update_parlay_slip_impl,
)


class _Result(SimpleNamespace):
    data: list[dict] | None = None
    status_code: int | None = None


class _FakeTable:
    def __init__(self, db, name: str):
        self.db = db
        self.name = name
        self._filters: list[tuple[str, object]] = []
        self._payload = None
        self._limit: int | None = None
        self._order_field: str | None = None
        self._order_desc = False
        self._operation = "select"

    def select(self, *_args):
        self._operation = "select"
        return self

    def eq(self, field: str, value):
        self._filters.append((field, value))
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def order(self, field: str, desc: bool = False):
        self._order_field = field
        self._order_desc = desc
        return self

    def insert(self, payload):
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._operation = "update"
        self._payload = payload
        return self

    def delete(self):
        self._operation = "delete"
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        matched = [row for row in rows if all(row.get(field) == value for field, value in self._filters)]
        if self._order_field:
            matched = sorted(matched, key=lambda row: row.get(self._order_field), reverse=self._order_desc)
        if self._limit is not None:
            matched = matched[: self._limit]

        if self._operation == "select":
            return _Result(data=[dict(row) for row in matched], status_code=200)

        if self._operation == "insert":
            next_row = {
                "id": f"slip-{len(rows) + 1}",
                "created_at": "2026-03-23T00:00:00Z",
                "updated_at": self._payload.get("updated_at", "2026-03-23T00:00:00Z"),
                **self._payload,
            }
            rows.append(next_row)
            return _Result(data=[dict(next_row)], status_code=201)

        if self._operation == "update":
            updated_rows = []
            for row in matched:
                row.update(self._payload)
                updated_rows.append(dict(row))
            return _Result(data=updated_rows, status_code=200)

        if self._operation == "delete":
            deleted_rows = [dict(row) for row in matched]
            self.db.tables[self.name] = [row for row in rows if row not in matched]
            return _Result(data=deleted_rows, status_code=200)

        raise AssertionError(f"Unsupported operation: {self._operation}")


class _FakeDB:
    def __init__(self, slips: list[dict] | None = None):
        self.tables = {"parlay_slips": list(slips or [])}

    def table(self, name: str):
        return _FakeTable(self, name)


BASE_ROW = {
    "id": "slip-1",
    "created_at": "2026-03-23T00:00:00Z",
    "updated_at": "2026-03-23T00:00:00Z",
    "user_id": "user-1",
    "sportsbook": "DraftKings",
    "stake": 10.0,
    "legs_json": [
        {
            "id": "straight:evt-1:lakers:draftkings",
            "surface": "straight_bets",
            "eventId": "evt-1",
            "marketKey": "h2h",
            "selectionKey": "evt-1:lakers",
            "sportsbook": "DraftKings",
            "oddsAmerican": 130,
            "referenceOddsAmerican": 108,
            "referenceSource": "pinnacle",
            "display": "Lakers ML",
            "event": "Lakers @ Warriors",
            "sport": "basketball_nba",
            "commenceTime": "2026-03-24T01:00:00Z",
            "correlationTags": ["evt-1", "lakers"],
            "team": "Lakers",
            "participantName": None,
            "participantId": None,
            "selectionSide": "Lakers",
            "lineValue": None,
            "marketDisplay": "Moneyline",
            "sourceEventId": "evt-1",
            "sourceMarketKey": "h2h",
            "sourceSelectionKey": "evt-1:lakers",
            "selectionMeta": None,
        }
    ],
    "warnings_json": [],
    "pricing_preview_json": {
        "legCount": 1,
        "sportsbook": "DraftKings",
        "combinedDecimalOdds": 2.3,
        "combinedAmericanOdds": 130,
        "stake": 10.0,
        "totalPayout": 23.0,
        "profit": 13.0,
        "estimatedFairDecimalOdds": 2.08,
        "estimatedFairAmericanOdds": 108,
        "estimatedTrueProbability": 0.48,
        "estimatedEvPercent": 10.4,
        "estimateAvailable": True,
        "estimateUnavailableReason": None,
        "hasBlockingCorrelation": False,
    },
    "logged_bet_id": None,
}


def test_list_parlay_slips_impl_returns_ordered_rows():
    db = _FakeDB(
        slips=[
            {**BASE_ROW, "id": "slip-older", "updated_at": "2026-03-23T00:00:00Z"},
            {**BASE_ROW, "id": "slip-newer", "updated_at": "2026-03-23T01:00:00Z"},
        ]
    )

    out = list_parlay_slips_impl(
        user={"id": "user-1"},
        get_db=lambda: db,
        build_response=lambda payload: payload,
    )

    assert [row["id"] for row in out] == ["slip-newer", "slip-older"]


def test_create_parlay_slip_impl_persists_row():
    db = _FakeDB()
    slip = SimpleNamespace(
        model_dump=lambda exclude_unset=False: {
            "sportsbook": "DraftKings",
            "stake": 10.0,
            "legs": BASE_ROW["legs_json"],
            "warnings": [],
            "pricingPreview": BASE_ROW["pricing_preview_json"],
        }
    )

    out = create_parlay_slip_impl(
        slip=slip,
        user={"id": "user-1"},
        get_db=lambda: db,
        build_insert_payload=lambda **kwargs: {
            "user_id": kwargs["user_id"],
            "sportsbook": "DraftKings",
            "stake": 10.0,
            "legs_json": BASE_ROW["legs_json"],
            "warnings_json": [],
            "pricing_preview_json": BASE_ROW["pricing_preview_json"],
            "updated_at": kwargs["utc_now_iso"](),
        },
        build_response=lambda payload: payload,
        utc_now_iso=lambda: "2026-03-23T02:00:00Z",
    )

    assert out["sportsbook"] == "DraftKings"
    assert out["stake"] == 10.0
    assert db.tables["parlay_slips"][0]["user_id"] == "user-1"


def test_update_parlay_slip_impl_blocks_logged_rows():
    db = _FakeDB(slips=[{**BASE_ROW, "logged_bet_id": "bet-1"}])

    with pytest.raises(HTTPException) as excinfo:
        update_parlay_slip_impl(
            slip_id="slip-1",
            slip_update=SimpleNamespace(model_dump=lambda exclude_unset=True: {"stake": 25.0}),
            user={"id": "user-1"},
            get_db=lambda: db,
            build_update_payload=lambda **kwargs: {"stake": 25.0, "updated_at": kwargs["utc_now_iso"]()},
            build_response=lambda payload: payload,
            utc_now_iso=lambda: "2026-03-23T03:00:00Z",
        )
    assert excinfo.value.detail == "Logged parlay slips cannot be edited"


def test_delete_parlay_slip_impl_deletes_unlogged_row():
    db = _FakeDB(slips=[dict(BASE_ROW)])

    out = delete_parlay_slip_impl(
        slip_id="slip-1",
        user={"id": "user-1"},
        get_db=lambda: db,
    )

    assert out == {"deleted": True, "id": "slip-1"}
    assert db.tables["parlay_slips"] == []


def test_log_parlay_slip_impl_links_created_bet():
    db = _FakeDB(slips=[dict(BASE_ROW)])
    captured = {}

    out = log_parlay_slip_impl(
        slip_id="slip-1",
        log_request=SimpleNamespace(
            sport="NBA",
            event="1-leg Lakers @ Warriors parlay",
            promo_type=SimpleNamespace(value="standard"),
            odds_american=130,
            stake=10.0,
            boost_percent=None,
            winnings_cap=None,
            notes="live slip",
            event_date=None,
            opposing_odds=None,
            payout_override=None,
        ),
        user={"id": "user-1"},
        get_db=lambda: db,
        build_logged_bet_payload_fn=lambda **kwargs: captured.setdefault("payload", {
            "sport": "NBA",
            "event": "1-leg Lakers @ Warriors parlay",
            "market": "Parlay",
            "surface": "parlay",
            "sportsbook": "DraftKings",
            "promo_type": "standard",
            "odds_american": 130,
            "stake": 10.0,
            "selection_meta": {"slip_id": "slip-1"},
        }),
        create_bet_fn=lambda bet, user: SimpleNamespace(id="bet-123", surface=bet.surface, event=bet.event),
        utc_now_iso=lambda: "2026-03-23T04:00:00Z",
    )

    assert captured["payload"]["surface"] == "parlay"
    assert out.id == "bet-123"
    assert db.tables["parlay_slips"][0]["logged_bet_id"] == "bet-123"
