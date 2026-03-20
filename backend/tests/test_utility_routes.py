from types import SimpleNamespace

from routes.utility_routes import calculate_ev_preview_impl


class _FakeDB:
    pass


def test_calculate_ev_preview_impl_builds_expected_response_and_calls_dependencies():
    db = _FakeDB()
    calls = {}

    def _get_user_settings(_db, user_id):
        calls["user_id"] = user_id
        return {"k_factor": 0.62}

    def _american_to_decimal(odds_american):
        calls["odds_american"] = odds_american
        return 2.1

    def _calculate_ev(**kwargs):
        calls["ev_kwargs"] = kwargs
        return {"ev_total": 5.5, "ev_per_dollar": 0.55}

    out = calculate_ev_preview_impl(
        odds_american=110,
        stake=10,
        promo_type=SimpleNamespace(value="standard"),
        boost_percent=None,
        winnings_cap=None,
        user={"id": "user-1"},
        get_db=lambda: db,
        get_user_settings=_get_user_settings,
        american_to_decimal=_american_to_decimal,
        calculate_ev=_calculate_ev,
    )

    assert calls["user_id"] == "user-1"
    assert calls["odds_american"] == 110
    assert calls["ev_kwargs"] == {
        "stake": 10,
        "decimal_odds": 2.1,
        "promo_type": "standard",
        "k_factor": 0.62,
        "boost_percent": None,
        "winnings_cap": None,
    }
    assert out == {
        "odds_american": 110,
        "odds_decimal": 2.1,
        "stake": 10,
        "promo_type": "standard",
        "ev_total": 5.5,
        "ev_per_dollar": 0.55,
    }
