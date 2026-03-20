from routes.admin_routes import backfill_ev_locks_impl


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

    def is_(self, _field, _value):
        return self

    def in_(self, _field, _values):
        return self

    def execute(self):
        return _Result(self._rows)


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "bets"
        return _Query(self._rows)


def test_backfill_ev_locks_impl_counts_successes_and_logs_failures():
    rows = [
        {"id": "a"},
        {"id": "b"},
        {"id": "c"},
    ]
    db = _DB(rows)
    warnings = []
    locked_ids = []

    def _lock_ev_for_row(_db, bet_id, _user_id, _row, _settings):
        if bet_id == "b":
            raise RuntimeError("boom")
        locked_ids.append(bet_id)

    out = backfill_ev_locks_impl(
        user={"id": "u1"},
        get_db=lambda: db,
        get_user_settings=lambda _db, _user_id: {"k_factor": 0.5},
        retry_supabase=lambda fn: fn(),
        ev_lock_promo_types=["bonus_bet"],
        lock_ev_for_row=_lock_ev_for_row,
        log_warning=lambda *args: warnings.append(args),
    )

    assert out == {"backfilled": 2, "total_eligible": 3}
    assert locked_ids == ["a", "c"]
    assert len(warnings) == 1
    assert warnings[0][0] == "backfill_ev_lock.failed bet_id=%s err=%s"
    assert warnings[0][1] == "b"
