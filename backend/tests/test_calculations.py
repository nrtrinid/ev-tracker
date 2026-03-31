"""
Unit tests for backend/calculations.py.
Run from backend directory: pytest tests -v
Or from repo root with PYTHONPATH=backend: pytest backend/tests -v
"""
import pytest

from calculations import (
    DEFAULT_VIG,
    american_to_decimal,
    calculate_clv,
    calculate_close_calibration_metrics,
    calculate_ev,
    calculate_hold_from_odds,
    calculate_real_profit,
    decimal_to_american,
    devig_two_way_american,
    kelly_fraction,
)


# --- Helper: american_to_decimal ---


@pytest.mark.parametrize(
    "american,expected_decimal",
    [
        (150, 2.5),
        (-150, 1 + 100 / 150),
        (100, 2.0),
        (-100, 2.0),
        (200, 3.0),
        (-200, 1.5),
    ],
)
def test_american_to_decimal(american, expected_decimal):
    assert american_to_decimal(american) == expected_decimal


def test_american_to_decimal_negative_150():
    assert american_to_decimal(-150) == pytest.approx(1.6666666666666667)


# --- Helper: decimal_to_american ---


@pytest.mark.parametrize(
    "decimal_odds,expected_american",
    [
        (2.5, 150),
        (2.0, 100),
        (3.0, 200),
        (1.5, -200),
    ],
)
def test_decimal_to_american(decimal_odds, expected_american):
    assert decimal_to_american(decimal_odds) == expected_american


def test_decimal_to_american_boundary_at_two():
    # At 2.0 the formula (decimal - 1) * 100 = 100; implementation uses >= 2.0 -> positive
    assert decimal_to_american(2.0) == 100


def test_decimal_to_american_rounds_negative():
    # 1.667 -> -100/0.667 ~ -149.92 -> round = -150 (implementation rounds to int)
    result = decimal_to_american(1.6666666666666667)
    assert result == -150


# --- Helper: calculate_hold_from_odds ---


def test_calculate_hold_from_odds_standard_juice():
    # -110 / -110: each implied prob = 1/1.90909... -> hold ~ 4.76%
    hold = calculate_hold_from_odds(-110, -110)
    assert hold is not None
    assert hold == pytest.approx(0.0476, abs=0.001)


def test_calculate_hold_from_odds_invalid_zero():
    assert calculate_hold_from_odds(0, -110) is None
    assert calculate_hold_from_odds(-110, 0) is None


def test_calculate_hold_from_odds_invalid_abs_under_100():
    # Odds with abs < 100 are invalid (e.g. 50)
    assert calculate_hold_from_odds(50, -110) is None
    assert calculate_hold_from_odds(-110, 50) is None


# --- Helper: kelly_fraction ---


def test_kelly_fraction_positive_edge():
    # p=0.55, decimal=2.0 -> b=1, q=0.45, f* = (1*0.55 - 0.45)/1 = 0.10
    assert kelly_fraction(0.55, 2.0) == pytest.approx(0.10)


def test_kelly_fraction_negative_edge_returns_zero():
    # p=0.4, decimal=2.0 -> b*0.4 - 0.6 = -0.2 < 0
    assert kelly_fraction(0.4, 2.0) == 0.0


def test_kelly_fraction_invalid_p_zero():
    assert kelly_fraction(0.0, 2.0) == 0.0


def test_kelly_fraction_invalid_p_one():
    assert kelly_fraction(1.0, 2.0) == 0.0


def test_kelly_fraction_invalid_decimal_one():
    assert kelly_fraction(0.55, 1.0) == 0.0


def test_kelly_fraction_decimal_below_one():
    assert kelly_fraction(0.55, 0.99) == 0.0


# --- calculate_ev ---


def test_calculate_ev_standard_with_true_prob():
    # Scanner-style: true_prob from Pinnacle de-vig. EV = (true_prob * decimal) - 1
    # 0.55 * 2.0 - 1 = 0.10 per dollar; stake 100 -> ev_total 10
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="standard",
        true_prob=0.55,
    )
    assert out["ev_per_dollar"] == 0.10
    assert out["ev_total"] == 10.0
    assert out["win_payout"] == 200.0


def test_calculate_ev_standard_without_true_prob():
    # Manual bet: no sharp reference, assume vig as cost
    out = calculate_ev(stake=100, decimal_odds=2.0, promo_type="standard")
    assert out["ev_per_dollar"] == -DEFAULT_VIG
    assert out["ev_total"] == pytest.approx(-100 * DEFAULT_VIG, abs=0.01)
    assert out["win_payout"] == 200.0


def test_calculate_ev_bonus_bet():
    # Free bet: win_payout = winnings only (no stake back); ev_per_dollar = 1 - 1/decimal
    out = calculate_ev(stake=100, decimal_odds=2.0, promo_type="bonus_bet")
    assert out["win_payout"] == 100.0  # stake * (decimal - 1)
    assert out["ev_per_dollar"] == 0.5  # 1 - 1/2
    assert out["ev_total"] == 50.0


def test_calculate_ev_no_sweat():
    # Same as plan: ev_per_dollar = -effective_vig; win_payout normal
    out = calculate_ev(stake=100, decimal_odds=2.0, promo_type="no_sweat")
    assert out["ev_per_dollar"] == -DEFAULT_VIG
    assert out["win_payout"] == 200.0


def test_calculate_ev_promo_qualifier():
    # Intentional: promo_qualifier uses same formula as no_sweat (vig on initial leg only)
    out = calculate_ev(stake=100, decimal_odds=2.0, promo_type="promo_qualifier")
    assert out["ev_per_dollar"] == -DEFAULT_VIG
    assert out["win_payout"] == 200.0


@pytest.mark.parametrize(
    "promo_type,effective_boost",
    [
        ("boost_30", 0.30),
        ("boost_50", 0.50),
        ("boost_100", 1.00),
    ],
)
def test_calculate_ev_fixed_boosts(promo_type, effective_boost):
    # stake=100, decimal=2.0 -> base_winnings=100, extra = 100 * effective_boost
    # win_payout = 100 + 100 + extra = 200 + 100*effective_boost
    # ev: win_prob=0.5, potential_extra=effective_boost*1, boost_value=0.5*effective_boost, ev_per_dollar = boost_value - vig
    out = calculate_ev(stake=100, decimal_odds=2.0, promo_type=promo_type)
    base_winnings = 100.0
    extra_winnings = base_winnings * effective_boost
    assert out["win_payout"] == pytest.approx(100 + base_winnings + extra_winnings, abs=0.01)
    expected_ev_per_dollar = (0.5 * effective_boost) - DEFAULT_VIG
    assert out["ev_per_dollar"] == pytest.approx(expected_ev_per_dollar, abs=0.0001)


def test_calculate_ev_boost_custom_without_cap():
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="boost_custom",
        boost_percent=40.0,
    )
    # 40% boost: extra = 100 * 0.4 = 40, win_payout = 100 + 100 + 40 = 240
    assert out["win_payout"] == 240.0
    expected_ev = (0.5 * 0.40) - DEFAULT_VIG
    assert out["ev_per_dollar"] == pytest.approx(expected_ev, abs=0.0001)


def test_calculate_ev_boost_custom_with_winnings_cap_above_cap():
    # Extra would be 50% of 100 = 50, but cap is 25 -> extra capped at 25
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="boost_custom",
        boost_percent=50.0,
        winnings_cap=25.0,
    )
    # win_payout = stake + base_winnings + min(extra, cap) = 100 + 100 + 25 = 225
    assert out["win_payout"] == 225.0
    # ev uses capped_extra: min(0.5, 25/100) = 0.25 per dollar -> boost_value = 0.5 * 0.25 = 0.125
    assert out["ev_per_dollar"] == pytest.approx(0.125 - DEFAULT_VIG, abs=0.0001)


def test_calculate_ev_boost_custom_with_winnings_cap_below_cap():
    # Extra = 20% of 100 = 20, cap = 50 -> no cap applied
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="boost_custom",
        boost_percent=20.0,
        winnings_cap=50.0,
    )
    assert out["win_payout"] == pytest.approx(100 + 100 + 20, abs=0.01)
    assert out["ev_per_dollar"] == pytest.approx((0.5 * 0.20) - DEFAULT_VIG, abs=0.0001)


def test_calculate_ev_custom_vig():
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="standard",
        vig=0.03,
    )
    assert out["ev_per_dollar"] == -0.03
    assert out["ev_total"] == -3.0


# --- calculate_clv ---


def test_calculate_clv_positive():
    # Book -105 (better than close -110) -> we got better odds than Pinnacle close
    out = calculate_clv(book_american=-105, close_pinnacle_american=-110)
    assert out["clv_ev_percent"] > 0
    assert out["beat_close"] is True


def test_calculate_clv_negative():
    # Book -115 (worse than close -110)
    out = calculate_clv(book_american=-115, close_pinnacle_american=-110)
    assert out["clv_ev_percent"] < 0
    assert out["beat_close"] is False


def test_calculate_clv_neutral():
    # Same odds -> no edge vs close
    out = calculate_clv(book_american=-110, close_pinnacle_american=-110)
    assert out["clv_ev_percent"] == 0.0
    # Implementation: beat_close is ev_raw > 0, so False when exactly 0
    assert out["beat_close"] is False


def test_devig_two_way_american_returns_paired_probabilities():
    result = devig_two_way_american(-110, -110)
    assert result is not None
    assert result["side_prob"] == pytest.approx(0.5, abs=0.0001)
    assert result["opposing_prob"] == pytest.approx(0.5, abs=0.0001)


def test_calculate_clv_uses_paired_close_when_opposing_side_is_available():
    out = calculate_clv(book_american=105, close_pinnacle_american=-112, close_opposing_american=-108)
    assert out["close_quality"] == "paired"
    assert out["close_opposing_american"] == -108
    assert out["close_true_prob"] == pytest.approx(0.5043, abs=0.0002)
    assert out["clv_ev_percent"] == pytest.approx(3.39, abs=0.02)


def test_calculate_close_calibration_metrics_matches_hand_math():
    metrics = calculate_close_calibration_metrics(0.55, 0.52)
    assert metrics is not None
    assert metrics["brier_score"] == pytest.approx(0.0009, abs=0.000001)
    assert metrics["log_loss"] == pytest.approx(0.694159, abs=0.000001)


# --- calculate_real_profit ---


def test_calculate_real_profit_standard_win():
    # stake 100, win_payout 195 (e.g. 1.95 decimal)
    assert calculate_real_profit(stake=100, win_payout=195, result="win", promo_type="standard") == 95.0


def test_calculate_real_profit_standard_loss():
    assert calculate_real_profit(stake=100, win_payout=195, result="loss", promo_type="standard") == -100.0


def test_calculate_real_profit_standard_push():
    assert calculate_real_profit(stake=100, win_payout=195, result="push", promo_type="standard") == 0.0


def test_calculate_real_profit_standard_void():
    assert calculate_real_profit(stake=100, win_payout=195, result="void", promo_type="standard") == 0.0


def test_calculate_real_profit_bonus_bet_win():
    # Bonus bet win: profit = win_payout (stake was not real money)
    assert calculate_real_profit(stake=100, win_payout=95, result="win", promo_type="bonus_bet") == 95.0


def test_calculate_real_profit_bonus_bet_loss():
    assert calculate_real_profit(stake=100, win_payout=95, result="loss", promo_type="bonus_bet") == 0.0


def test_calculate_real_profit_bonus_bet_push():
    assert calculate_real_profit(stake=100, win_payout=95, result="push", promo_type="bonus_bet") == 0.0


def test_calculate_real_profit_invalid_result_returns_none():
    assert calculate_real_profit(stake=100, win_payout=195, result="pending", promo_type="standard") is None
    assert calculate_real_profit(stake=100, win_payout=195, result="", promo_type="standard") is None
    assert calculate_real_profit(stake=100, win_payout=195, result="won", promo_type="standard") is None


# =============================================================================
# Hand-calculated truth tests
# Expected values derived manually in comments; assertions use hand math, not
# mirroring the implementation. Different inputs from branch tests where useful.
# =============================================================================


def test_truth_standard_ev_with_true_prob_hand_calculated():
    # Hand: EV per $1 = (true_prob × decimal_odds) − 1 = 0.48×2.5 − 1 = 0.20
    #       ev_total = 50×0.20 = 10; win_payout = 50×2.5 = 125
    out = calculate_ev(
        stake=50,
        decimal_odds=2.5,
        promo_type="standard",
        true_prob=0.48,
    )
    assert out["ev_per_dollar"] == 0.2
    assert out["ev_total"] == 10.0
    assert out["win_payout"] == 125.0


def test_truth_bonus_bet_ev_hand_calculated():
    # Hand: win_payout = stake×(decimal−1) = 50×1.5 = 75
    #       EV per $1 = 1 − 1/decimal = 1 − 0.4 = 0.6; ev_total = 50×0.6 = 30
    out = calculate_ev(stake=50, decimal_odds=2.5, promo_type="bonus_bet")
    assert out["win_payout"] == 75.0
    assert out["ev_per_dollar"] == 0.6
    assert out["ev_total"] == 30.0


def test_truth_fixed_boost_ev_hand_calculated():
    # Hand: base_winnings = 50×(2.5−1) = 75; extra = 75×0.5 = 37.5
    #       win_payout = 50+75+37.5 = 162.5
    #       win_prob = 1/2.5 = 0.4; potential_extra = 0.5×(2.5−1) = 0.75
    #       boost_value = 0.4×0.75 = 0.3; ev_per_dollar = 0.3 − 0.045 = 0.255
    #       ev_total = 50×0.255 = 12.75
    out = calculate_ev(stake=50, decimal_odds=2.5, promo_type="boost_50")
    assert out["win_payout"] == 162.5
    assert out["ev_per_dollar"] == pytest.approx(0.255, abs=0.0001)
    assert out["ev_total"] == pytest.approx(12.75, abs=0.01)


def test_truth_custom_boost_with_cap_hand_calculated():
    # Hand: base = 75; uncapped extra = 45; capped extra = 20
    #       win_payout = 50+75+20 = 145
    #       capped_extra_per_dollar = min(0.9, 20/50) = 0.4
    #       boost_value = 0.4×0.4 = 0.16; ev_per_dollar = 0.16 − 0.045 = 0.115
    #       ev_total = 50×0.115 = 5.75
    out = calculate_ev(
        stake=50,
        decimal_odds=2.5,
        promo_type="boost_custom",
        boost_percent=60.0,
        winnings_cap=20.0,
    )
    assert out["win_payout"] == 145.0
    assert out["ev_per_dollar"] == pytest.approx(0.115, abs=0.0001)
    assert out["ev_total"] == pytest.approx(5.75, abs=0.01)


def test_truth_positive_clv_hand_calculated():
    # Hand: book_decimal = 3, close_decimal = 2.5
    #       close_true_prob = 1/2.5 = 0.4; ev_raw = 0.4×3 − 1 = 0.2
    #       clv_ev_percent = 20; beat_close = True
    out = calculate_clv(book_american=200, close_pinnacle_american=150)
    assert out["clv_ev_percent"] == 20.0
    assert out["beat_close"] is True


def test_truth_negative_clv_hand_calculated():
    # Hand: book_decimal = 2.5, close_decimal = 3
    #       close_true_prob = 1/3; ev_raw = (1/3)×2.5 − 1 = −1/6 ≈ −16.67%
    out = calculate_clv(book_american=150, close_pinnacle_american=200)
    assert out["clv_ev_percent"] == pytest.approx(-16.67, abs=0.01)
    assert out["beat_close"] is False


def test_truth_standard_real_profit_hand_calculated():
    # Hand: stake=50, win_payout=125 (2.5 decimal). Win profit = 125−50 = 75; loss = −50
    assert calculate_real_profit(stake=50, win_payout=125, result="win", promo_type="standard") == 75.0
    assert calculate_real_profit(stake=50, win_payout=125, result="loss", promo_type="standard") == -50.0


def test_truth_bonus_bet_real_profit_hand_calculated():
    # Hand: stake=50, win_payout=75. Win profit = 75 (no stake back); loss = 0
    assert calculate_real_profit(stake=50, win_payout=75, result="win", promo_type="bonus_bet") == 75.0
    assert calculate_real_profit(stake=50, win_payout=75, result="loss", promo_type="bonus_bet") == 0.0


# =============================================================================
# Invariant / property-style tests
# Business truths that must always hold; not tied to one implementation path.
# =============================================================================


def test_higher_true_prob_does_not_reduce_standard_ev():
    # For fixed stake and odds, higher true_prob must not decrease EV per dollar
    stake, decimal = 100.0, 2.0
    ev_52 = calculate_ev(stake=stake, decimal_odds=decimal, promo_type="standard", true_prob=0.52)["ev_per_dollar"]
    ev_55 = calculate_ev(stake=stake, decimal_odds=decimal, promo_type="standard", true_prob=0.55)["ev_per_dollar"]
    ev_60 = calculate_ev(stake=stake, decimal_odds=decimal, promo_type="standard", true_prob=0.60)["ev_per_dollar"]
    assert ev_52 <= ev_55 <= ev_60


def test_ev_total_scales_with_stake():
    # Same promo and odds: ev_total(2*stake) == 2*ev_total(stake)
    ev_50 = calculate_ev(stake=50, decimal_odds=2.0, promo_type="standard", true_prob=0.55)["ev_total"]
    ev_100 = calculate_ev(stake=100, decimal_odds=2.0, promo_type="standard", true_prob=0.55)["ev_total"]
    assert ev_100 == pytest.approx(2 * ev_50, abs=0.01)


@pytest.mark.parametrize(
    "result,promo_type",
    [
        ("push", "standard"),
        ("void", "standard"),
        ("push", "bonus_bet"),
        ("void", "bonus_bet"),
    ],
)
def test_push_and_void_always_return_zero_real_profit(result, promo_type):
    assert calculate_real_profit(stake=100, win_payout=200, result=result, promo_type=promo_type) == 0.0


def test_negative_edge_kelly_always_zero():
    assert kelly_fraction(0.45, 2.0) == 0.0
    assert kelly_fraction(0.4, 1.8) == 0.0


def test_equal_entry_and_close_odds_never_beat_close():
    out = calculate_clv(book_american=100, close_pinnacle_american=100)
    assert out["beat_close"] is False


def test_boost_cap_never_increases_win_payout_beyond_capped_extra():
    # With winnings_cap=25, win_payout must be stake + base_winnings + min(extra, 25)
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="boost_custom",
        boost_percent=50.0,
        winnings_cap=25.0,
    )
    base_winnings = 100.0
    assert out["win_payout"] <= 100 + base_winnings + 25
    assert out["win_payout"] == 225.0  # strict: exactly capped


def test_bonus_bet_loss_never_negative():
    assert calculate_real_profit(stake=100, win_payout=50, result="loss", promo_type="bonus_bet") >= 0
    assert calculate_real_profit(stake=50, win_payout=30, result="loss", promo_type="bonus_bet") >= 0


@pytest.mark.parametrize("stake", [50, 100])
def test_standard_loss_always_equals_negative_stake(stake):
    assert calculate_real_profit(stake=stake, win_payout=stake * 2, result="loss", promo_type="standard") == -stake


# =============================================================================
# Regression / edge-case tests
# Document current behavior for ambiguous or fragile inputs; do not change behavior.
#
# Suspicious behaviors (tests reveal; no change in this suite):
# - american_to_decimal(0) and decimal_to_american(1.0) raise ZeroDivisionError.
# - true_prob is not clamped to [0,1]; e.g. 1.5 yields nonsensical EV.
# - boost_custom with boost_percent=None gives normal payout but EV = -vig.
# - stake=0 is accepted (returns zeros); unknown promo_type falls through to standard.
# =============================================================================


def test_decimal_to_american_just_below_two():
    # 1.999 -> -100/0.999 ≈ -100.1 -> round = -100
    assert decimal_to_american(1.999) == -100


def test_decimal_to_american_just_above_two():
    assert decimal_to_american(2.001) == 100


def test_decimal_to_american_one_raises():
    # decimal_odds=1.0 -> -100/(decimal_odds−1) causes ZeroDivisionError
    with pytest.raises(ZeroDivisionError):
        decimal_to_american(1.0)


def test_decimal_to_american_near_one_finite():
    # 1.001 -> -100/0.001 = -100000; no crash, large negative American
    result = decimal_to_american(1.001)
    assert result < 0
    assert abs(result) == 100000


def test_american_to_decimal_zero_raises():
    # 0 is not >= 100, so code uses 1+100/abs(0) -> ZeroDivisionError
    with pytest.raises(ZeroDivisionError):
        american_to_decimal(0)


def test_boost_custom_without_boost_percent_documented_behavior():
    # boost_custom without boost_percent: effective_boost=0; full normal payout, EV = −vig
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="boost_custom",
        boost_percent=None,
    )
    assert out["win_payout"] == 200.0  # normal payout
    assert out["ev_per_dollar"] == pytest.approx(-DEFAULT_VIG, abs=0.0001)


def test_stake_zero_accepted():
    out = calculate_ev(stake=0, decimal_odds=2.0, promo_type="standard")
    assert out["win_payout"] == 0
    assert out["ev_total"] == 0
    assert calculate_real_profit(stake=0, win_payout=0, result="loss", promo_type="standard") == -0.0


def test_true_prob_outside_zero_one_allowed():
    # Current code does not clamp true_prob; 1.5 yields nonsensical ev_per_dollar = 2
    out = calculate_ev(
        stake=100,
        decimal_odds=2.0,
        promo_type="standard",
        true_prob=1.5,
    )
    assert out["ev_per_dollar"] == 2.0


def test_unknown_promo_type_treated_as_standard():
    # Unknown promo falls through: full payout, ev_per_dollar = −DEFAULT_VIG
    out = calculate_ev(stake=100, decimal_odds=2.0, promo_type="other")
    assert out["win_payout"] == 200.0
    assert out["ev_per_dollar"] == -DEFAULT_VIG
