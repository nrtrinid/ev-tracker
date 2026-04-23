from types import SimpleNamespace

from services.analytics_events import (
    capture_analytics_event,
    capture_backend_event,
    classify_analytics_row,
    normalize_analytics_audience,
)


class _InsertQuery:
    def __init__(self, db, payload):
        self._db = db
        self._payload = payload

    def execute(self):
        if self._db.raise_duplicate:
            raise RuntimeError("duplicate key value violates unique constraint idx_analytics_events_dedupe_key")
        self._db.inserted.append(self._payload)
        return SimpleNamespace(data=[self._payload])


class _Table:
    def __init__(self, db):
        self._db = db

    def insert(self, payload):
        return _InsertQuery(self._db, payload)


class _DB:
    def __init__(self, *, raise_duplicate: bool = False):
        self.raise_duplicate = raise_duplicate
        self.inserted: list[dict] = []

    def table(self, name: str):
        assert name == "analytics_events"
        return _Table(self)


def test_capture_analytics_event_canonicalizes_properties() -> None:
    db = _DB()

    inserted = capture_analytics_event(
        db=db,
        event_name="bet_logged",
        source="frontend",
        user_id="user-1",
        session_id="session-1",
        route="/bets",
        app_area="tracker",
        properties={
            "surface": "straight_bets",
            "sportsbook": "draftkings",
            "source_market_key": "spreads",
            "source_selection_key": "selection-1",
            "ev_percentage": 2.3,
        },
        dedupe_key="bet-logged:1",
    )

    assert inserted is True
    payload = db.inserted[0]
    assert payload["route"] == "/bets"
    assert payload["app_area"] == "tracker"
    assert payload["properties"]["origin_surface"] == "straight_bets"
    assert payload["properties"]["book"] == "draftkings"
    assert payload["properties"]["market"] == "spreads"
    assert payload["properties"]["opportunity_id"] == "selection-1"
    assert payload["properties"]["edge_bucket"] == "2-4%"


def test_capture_analytics_event_returns_false_for_duplicate_dedupe_key() -> None:
    inserted = capture_analytics_event(
        db=_DB(raise_duplicate=True),
        event_name="board_viewed",
        source="frontend",
        user_id="user-1",
        session_id="session-1",
        route="/",
        app_area="markets",
        properties={"snapshot_id": "snap-1"},
        dedupe_key="board-viewed:snap-1",
    )

    assert inserted is False


def test_classify_analytics_row_prefers_internal_and_test_allowlists() -> None:
    internal = frozenset({"ops@example.com"})
    tests = frozenset({"test@example.com"})

    assert (
        classify_analytics_row(
            user_id="user-1",
            session_id="session-1",
            properties={"user_email": "ops@example.com"},
            internal_emails=internal,
            test_emails=tests,
        )
        == "internal"
    )
    assert (
        classify_analytics_row(
            user_id="user-2",
            session_id="session-2",
            properties={"user_email": "test@example.com"},
            internal_emails=internal,
            test_emails=tests,
        )
        == "test"
    )


def test_capture_backend_event_injects_user_email() -> None:
    db = _DB()

    inserted = capture_backend_event(
        db,
        event_name="bet_logged",
        user_id="user-1",
        user_email="Ops@Example.com",
        session_id="session-1",
        properties={
            "route": "/bets",
            "app_area": "tracker",
            "sportsbook": "draftkings",
        },
        dedupe_key="bet-logged:1",
        retry_supabase=lambda op: op(),
        log_event=lambda *args, **kwargs: None,
    )

    assert inserted is True
    payload = db.inserted[0]
    assert payload["route"] == "/bets"
    assert payload["app_area"] == "tracker"
    assert payload["properties"]["user_email"] == "ops@example.com"


def test_normalize_analytics_audience_defaults_to_external() -> None:
    assert normalize_analytics_audience(None) == "external"
    assert normalize_analytics_audience("external") == "external"
    assert normalize_analytics_audience("all") == "all"
    assert normalize_analytics_audience("unexpected") == "external"
