from services.board_snapshot import _payload_sports_included, persist_board_snapshot


class _FakeQuery:
    def __init__(self):
        self.rows = []

    def upsert(self, payload, on_conflict=None):
        self.rows.append({"payload": payload, "on_conflict": on_conflict})
        return self

    def execute(self):
        return type("Resp", (), {"data": self.rows})()


class _FakeDB:
    def __init__(self):
        self.query = _FakeQuery()

    def table(self, name):
        assert name == "global_scan_cache"
        return self.query


def test_payload_sports_included_prefers_diagnostics_sports_scanned():
    payload = {
        "surface": "player_props",
        "sport": "all",
        "sides": [],
        "diagnostics": {
            "sports_scanned": ["baseball_mlb", "basketball_nba", "baseball_mlb"],
        },
    }

    assert _payload_sports_included(payload, fallback="all") == ["baseball_mlb", "basketball_nba"]


def test_persist_board_snapshot_uses_all_fallback_for_empty_player_props_payload():
    db = _FakeDB()

    persist_board_snapshot(
        db=db,
        snapshot_type="manual",
        straight_bets_payload=None,
        player_props_payload={
            "surface": "player_props",
            "sport": "all",
            "sides": [],
            "events_fetched": 0,
            "diagnostics": None,
        },
        retry_supabase=lambda operation: operation(),
        log_event=lambda *args, **kwargs: None,
    )

    stored = db.query.rows[0]["payload"]["payload"]
    assert stored["meta"]["surfaces_included"] == ["player_props"]
    assert stored["meta"]["sports_included"] == ["all"]
