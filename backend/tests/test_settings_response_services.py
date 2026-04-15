from services.settings_response import build_settings_response


def test_build_settings_response_applies_defaults_and_k_derivatives():
    settings = {
        "k_factor": 0.6,
        "default_stake": 25,
        "preferred_sportsbooks": None,
        "kelly_multiplier": None,
        "bankroll_override": None,
        "use_computed_bankroll": None,
        "theme_preference": None,
        "k_factor_mode": None,
        "k_factor_min_stake": None,
        "k_factor_smoothing": None,
        "k_factor_clamp_min": None,
        "k_factor_clamp_max": None,
    }

    out = build_settings_response(
        db=object(),
        user_id="u1",
        settings=settings,
        default_sportsbooks=["DraftKings"],
        compute_k_user=lambda _db, _user_id: {"k_obs": 0.55, "bonus_stake_settled": 300.0},
        build_effective_k=lambda _s, _k_obs, _bonus_stake_settled: {
            "k_factor_effective": 0.58,
            "k_factor_obs": 0.55,
            "k_factor_source": "baseline",
            "k_factor_floor_applied": False,
            "k_factor_ceiling_applied": False,
            "k_factor_user_sample_size": 10,
            "k_factor_last_updated": None,
        },
        settings_response_cls=lambda **kwargs: kwargs,
    )

    assert out["k_factor"] == 0.6
    assert out["default_stake"] == 25
    assert out["preferred_sportsbooks"] == ["DraftKings"]
    assert out["kelly_multiplier"] == 0.25
    assert out["bankroll_override"] == 1000.0
    assert out["use_computed_bankroll"] is True
    assert out["theme_preference"] == "light"
    assert out["k_factor_mode"] == "baseline"
    assert out["k_factor_min_stake"] == 300.0
    assert out["k_factor_smoothing"] == 700.0
    assert out["k_factor_clamp_min"] == 0.5
    assert out["k_factor_clamp_max"] == 0.95
    assert out["k_factor_effective"] == 0.58
