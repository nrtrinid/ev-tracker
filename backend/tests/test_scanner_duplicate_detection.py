from services.scanner_duplicate_detection import annotate_sides_with_duplicate_state


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, _fields):
        return self

    def eq(self, _field, _value):
        return self

    def execute(self):
        return _Result(self._rows)


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "bets"
        return _Query(self._rows)


def _side(*, team, commence_time, sportsbook, odds, event_id=None):
    return {
        "sport": "basketball_nba",
        "market": "ML",
        "sportsbook": sportsbook,
        "commence_time": commence_time,
        "team": team,
        "book_odds": odds,
        "event_id": event_id,
    }


def _pending_bet(*, bet_id, team, commence_time, sportsbook, odds, clv_event_id=None):
    return {
        "id": bet_id,
        "clv_sport_key": "basketball_nba",
        "market": "ML",
        "sportsbook": sportsbook,
        "commence_time": commence_time,
        "clv_team": team,
        "clv_event_id": clv_event_id,
        "odds_american": odds,
        "result": "pending",
    }


def _prop_side(*, market_key, selection_key, sportsbook, odds):
    return {
        "surface": "player_props",
        "market_key": market_key,
        "selection_key": selection_key,
        "sportsbook": sportsbook,
        "book_odds": odds,
    }


def _pending_prop(*, bet_id, market_key, selection_key, sportsbook, odds):
    return {
        "id": bet_id,
        "surface": "player_props",
        "source_market_key": market_key,
        "source_selection_key": selection_key,
        "sportsbook": sportsbook,
        "odds_american": odds,
        "result": "pending",
    }


def test_annotate_sides_with_duplicate_state_marks_new_when_no_pending_match():
    db = _DB(rows=[])
    sides = [_side(team="lakers", commence_time="2026-01-01T00:00:00Z", sportsbook="fanduel", odds=110)]

    out = annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert out[0]["scanner_duplicate_state"] == "new"
    assert out[0]["best_logged_odds_american"] is None
    assert out[0]["matched_pending_bet_id"] is None


def test_annotate_sides_with_duplicate_state_marks_better_now_when_price_improves():
    db = _DB(
        rows=[
            _pending_bet(
                bet_id="b1",
                team="lakers",
                commence_time="2026-01-01T00:00:00Z",
                sportsbook="fanduel",
                odds=100,
            )
        ]
    )
    sides = [_side(team="lakers", commence_time="2026-01-01T00:00:00Z", sportsbook="fanduel", odds=150)]

    out = annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert out[0]["scanner_duplicate_state"] == "better_now"
    assert out[0]["best_logged_odds_american"] == 100
    assert out[0]["matched_pending_bet_id"] == "b1"


def test_annotate_sides_with_duplicate_state_marks_already_logged_when_not_improved():
    db = _DB(
        rows=[
            _pending_bet(
                bet_id="b1",
                team="lakers",
                commence_time="2026-01-01T00:00:00Z",
                sportsbook="fanduel",
                odds=150,
            )
        ]
    )
    sides = [_side(team="lakers", commence_time="2026-01-01T00:00:00Z", sportsbook="fanduel", odds=120)]

    out = annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert out[0]["scanner_duplicate_state"] == "already_logged"
    assert out[0]["best_logged_odds_american"] == 150
    assert out[0]["matched_pending_bet_id"] == "b1"


def test_annotate_sides_with_duplicate_state_handles_unparseable_logged_odds():
    db = _DB(
        rows=[
            _pending_bet(
                bet_id="b1",
                team="lakers",
                commence_time="2026-01-01T00:00:00Z",
                sportsbook="fanduel",
                odds=None,
            )
        ]
    )
    sides = [_side(team="lakers", commence_time="2026-01-01T00:00:00Z", sportsbook="fanduel", odds=120)]

    out = annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert out[0]["scanner_duplicate_state"] == "already_logged"
    assert out[0]["best_logged_odds_american"] is None
    assert out[0]["matched_pending_bet_id"] == "b1"


def test_annotate_sides_with_duplicate_state_matches_by_event_id_before_time():
    db = _DB(
        rows=[
            _pending_bet(
                bet_id="b1",
                team="lakers",
                commence_time="2026-01-01T00:00:00Z",
                sportsbook="fanduel",
                odds=100,
                clv_event_id="evt_abc",
            )
        ]
    )
    sides = [
        _side(
            team="lakers",
            commence_time="2026-01-01T00:05:00Z",
            sportsbook="fanduel",
            odds=130,
            event_id="evt_abc",
        )
    ]

    out = annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert out[0]["scanner_duplicate_state"] == "better_now"
    assert out[0]["matched_pending_bet_id"] == "b1"


def test_annotate_sides_with_duplicate_state_marks_logged_elsewhere_for_cross_book_ml_match():
    db = _DB(
        rows=[
            _pending_bet(
                bet_id="b1",
                team="lakers",
                commence_time="2026-01-01T00:00:00Z",
                sportsbook="fanduel",
                odds=100,
            )
        ]
    )
    sides = [_side(team="lakers", commence_time="2026-01-01T00:00:00Z", sportsbook="draftkings", odds=130)]

    out = annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert out[0]["scanner_duplicate_state"] == "logged_elsewhere"
    assert out[0]["best_logged_odds_american"] == 100
    assert out[0]["matched_pending_bet_id"] == "b1"


def test_annotate_sides_with_duplicate_state_marks_logged_elsewhere_for_cross_book_prop_match():
    db = _DB(
        rows=[
            _pending_prop(
                bet_id="p1",
                market_key="player_points",
                selection_key="evt-1|player_points|jokic|over:24.5",
                sportsbook="fanduel",
                odds=110,
            )
        ]
    )
    sides = [
        _prop_side(
            market_key="player_points",
            selection_key="evt-1|player_points|jokic|over:24.5",
            sportsbook="draftkings",
            odds=115,
        )
    ]

    out = annotate_sides_with_duplicate_state(db, "user-1", sides)

    assert out[0]["scanner_duplicate_state"] == "logged_elsewhere"
    assert out[0]["best_logged_odds_american"] == 110
    assert out[0]["matched_pending_bet_id"] == "p1"
