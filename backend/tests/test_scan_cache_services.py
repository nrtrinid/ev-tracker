import pytest
from fastapi import HTTPException

from services.scan_cache import (
    empty_scan_response,
    is_missing_scan_cache_error,
    load_latest_scan_payload,
    persist_latest_scan_payload,
    persist_latest_full_scan,
    with_enriched_scan_sides,
    load_and_enrich_latest_scan_payload,
    resolve_scan_latest_response,
    scan_cache_exception_to_http_exception,
)


class _FakeQuery:
    def __init__(self, payload_rows):
        self._payload_rows = payload_rows

    def select(self, _fields):
        return self

    def eq(self, _key, _value):
        return self

    def limit(self, _value):
        return self

    def execute(self):
        return type("Resp", (), {"data": self._payload_rows})()


class _FakeDB:
    def __init__(self, payload_rows):
        self._payload_rows = payload_rows

    def table(self, name):
        assert name == "global_scan_cache"
        return _FakeQuery(self._payload_rows)


class _FakeUpsertQuery:
    def __init__(self):
        self.upsert_calls = []

    def upsert(self, payload, on_conflict=None):
        self.upsert_calls.append((payload, on_conflict))
        return self

    def execute(self):
        return {"ok": True}


class _FakePersistDB:
    def __init__(self):
        self.query = _FakeUpsertQuery()

    def table(self, name):
        assert name == "global_scan_cache"
        return self.query


VALID_PROP_DIAGNOSTICS = {
    "scan_mode": "curated_sniper",
    "scoreboard_event_count": 10,
    "odds_event_count": 5,
    "curated_games": [
        {
            "event_id": "espn-1",
            "away_team": "Boston Celtics",
            "home_team": "Los Angeles Lakers",
            "selection_reason": "national_tv",
            "broadcasts": ["ESPN"],
            "odds_event_id": "odds-1",
            "commence_time": "2026-03-19T00:00:00Z",
            "matched": True,
        }
    ],
    "matched_event_count": 1,
    "unmatched_game_count": 0,
    "events_fetched": 1,
    "events_skipped_pregame": 0,
    "events_with_results": 1,
    "candidate_sides_count": 14,
    "quality_gate_filtered_count": 2,
    "quality_gate_min_reference_bookmakers": 2,
    "sides_count": 12,
    "markets_requested": ["player_points"],
}


def test_empty_scan_response_shape():
    payload = empty_scan_response()
    assert payload.sport == "all"
    assert payload.sides == []
    assert payload.events_fetched == 0


def test_is_missing_scan_cache_error_patterns():
    assert is_missing_scan_cache_error(Exception("PGRST205: relation missing")) is True
    assert is_missing_scan_cache_error(Exception("global_scan_cache schema cache stale")) is True
    assert is_missing_scan_cache_error(Exception("other error")) is False


def test_load_latest_scan_payload_returns_none_when_missing_or_empty():
    db = _FakeDB([])
    assert load_latest_scan_payload(db=db, retry_supabase=lambda fn: fn()) is None

    def _raise_missing(_fn):
        raise Exception("PGRST205 missing")

    assert load_latest_scan_payload(db=db, retry_supabase=_raise_missing) is None


def test_load_latest_scan_payload_validates_payload_dict():
    db_good = _FakeDB([{"payload": {"sport": "all", "sides": []}}])
    payload = load_latest_scan_payload(db=db_good, retry_supabase=lambda fn: fn())
    assert payload == {"sport": "all", "sides": []}

    db_bad = _FakeDB([{"payload": "not-a-dict"}])
    with pytest.raises(ValueError, match="Invalid scan cache payload"):
        load_latest_scan_payload(db=db_bad, retry_supabase=lambda fn: fn())


def test_with_enriched_scan_sides_handles_missing_and_existing_sides():
    payload_without_sides = {"sport": "all"}
    out = with_enriched_scan_sides(
        payload=payload_without_sides,
        enrich_sides=lambda sides: sides + [{"id": "x"}],
    )
    assert out["sides"] == [{"id": "x"}]
    assert payload_without_sides.get("sides") is None

    payload_with_sides = {"sport": "all", "sides": [{"id": "a"}]}
    out2 = with_enriched_scan_sides(
        payload=payload_with_sides,
        enrich_sides=lambda sides: sides + [{"id": "b"}],
    )
    assert out2["sides"] == [{"id": "a"}, {"id": "b"}]


def test_persist_latest_scan_payload_success_and_warning_path():
    db = _FakePersistDB()
    events = []

    persist_latest_scan_payload(
        db=db,
        payload={"sport": "all", "sides": []},
        retry_supabase=lambda fn: fn(),
        log_event=lambda event, **fields: events.append((event, fields)),
    )
    assert len(db.query.upsert_calls) == 1
    assert events == []

    def _failing_retry(_fn):
        raise RuntimeError("db unavailable")

    persist_latest_scan_payload(
        db=db,
        payload={"sport": "all", "sides": []},
        retry_supabase=_failing_retry,
        log_event=lambda event, **fields: events.append((event, fields)),
    )
    assert any(e[0] == "scan_latest_cache.persist_failed" for e in events)


def test_persist_latest_full_scan_builds_expected_payload():
    db = _FakePersistDB()
    events = []
    valid_side = {
        "sportsbook": "DraftKings",
        "sport": "basketball_nba",
        "event": "A vs B",
        "commence_time": "2026-03-19T00:00:00Z",
        "team": "A",
        "pinnacle_odds": -110,
        "book_odds": -105,
        "true_prob": 0.52,
        "base_kelly_fraction": 0.01,
        "book_decimal": 1.95,
        "ev_percentage": 1.2,
    }

    persist_latest_full_scan(
        db=db,
        surface="straight_bets",
        sport="all",
        sides=[valid_side],
        events_fetched=3,
        events_with_both_books=2,
        api_requests_remaining="88",
        scanned_at="2026-03-19T00:00:00Z",
        diagnostics=VALID_PROP_DIAGNOSTICS,
        retry_supabase=lambda fn: fn(),
        log_event=lambda event, **fields: events.append((event, fields)),
    )

    assert len(db.query.upsert_calls) == 1
    upsert_payload, on_conflict = db.query.upsert_calls[0]
    assert on_conflict == "key"
    assert upsert_payload["key"] == "straight_bets:latest"
    assert upsert_payload["surface"] == "straight_bets"
    assert upsert_payload["payload"]["sport"] == "all"
    assert upsert_payload["payload"]["events_fetched"] == 3
    assert upsert_payload["payload"]["events_with_both_books"] == 2
    assert upsert_payload["payload"]["api_requests_remaining"] == "88"
    assert upsert_payload["payload"]["scanned_at"] == "2026-03-19T00:00:00Z"
    assert upsert_payload["payload"]["diagnostics"] == VALID_PROP_DIAGNOSTICS
    assert events == []


def test_load_and_enrich_latest_scan_payload_handles_none_and_enrichment():
    db_empty = _FakeDB([])
    out_empty = load_and_enrich_latest_scan_payload(
        db=db_empty,
        retry_supabase=lambda fn: fn(),
        enrich_sides=lambda sides: sides,
    )
    assert out_empty is None

    db_value = _FakeDB([{"payload": {"sport": "all", "sides": [{"id": "a"}]}}])
    out_value = load_and_enrich_latest_scan_payload(
        db=db_value,
        retry_supabase=lambda fn: fn(),
        enrich_sides=lambda sides: sides + [{"id": "b"}],
    )
    assert out_value is not None
    assert out_value["sides"] == [{"id": "a"}, {"id": "b"}]


def test_resolve_scan_latest_response_returns_empty_or_payload():
    db_empty = _FakeDB([])
    out_empty = resolve_scan_latest_response(
        db=db_empty,
        retry_supabase=lambda fn: fn(),
        enrich_sides=lambda sides: sides,
    )
    assert not isinstance(out_empty, dict)
    assert out_empty.sport == "all"

    db_value = _FakeDB([{"payload": {"sport": "all", "sides": [{"id": "a"}]}}])
    out_value = resolve_scan_latest_response(
        db=db_value,
        retry_supabase=lambda fn: fn(),
        enrich_sides=lambda sides: sides + [{"id": "b"}],
    )
    assert isinstance(out_value, dict)
    assert out_value["sides"] == [{"id": "a"}, {"id": "b"}]


def test_scan_cache_exception_to_http_exception_maps_errors():
    v = scan_cache_exception_to_http_exception(ValueError("bad payload"))
    assert isinstance(v, HTTPException)
    assert v.status_code == 500
    assert v.detail == "bad payload"

    g = scan_cache_exception_to_http_exception(RuntimeError("db down"))
    assert isinstance(g, HTTPException)
    assert g.status_code == 502
    assert g.detail == "Failed to load scan cache: db down"

    original = HTTPException(status_code=401, detail="unauthorized")
    same = scan_cache_exception_to_http_exception(original)
    assert same is original
