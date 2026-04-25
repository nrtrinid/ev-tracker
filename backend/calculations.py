"""
EV Calculation Engine
Ports the Excel spreadsheet formulas to Python.
"""

import math

# Default vig to account for book edge when we only have one side of the market
DEFAULT_VIG = 0.045

def american_to_decimal(american_odds: float) -> float:
    """
    Convert American odds to Decimal odds.
    Examples:
        +150 -> 2.50
        -150 -> 1.667
        +100 -> 2.00
        -100 -> 2.00
    """
    if american_odds >= 100:
        return 1 + (american_odds / 100)
    else:
        return 1 + (100 / abs(american_odds))


def kelly_fraction(p: float, decimal_odds: float) -> float:
    """
    Fractional Kelly base fraction (full Kelly), returned as a fraction of bankroll.

    f* = (b*p - q) / b
      b = decimal_odds - 1
      q = 1 - p

    If f* <= 0, return 0.
    """
    if decimal_odds <= 1:
        return 0.0
    if p <= 0 or p >= 1:
        return 0.0
    b = decimal_odds - 1.0
    q = 1.0 - p
    f = (b * p - q) / b
    return float(f) if f > 0 else 0.0


def decimal_to_american(decimal_odds: float) -> int:
    """
    Convert Decimal odds to American odds.
    Examples:
        2.50 -> +150
        1.667 -> -149
    """
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    else:
        return round(-100 / (decimal_odds - 1))


def calculate_hold_from_odds(odds1: float, odds2: float) -> float | None:
    """
    Calculate hold (vig) from two American odds.
    Returns the hold percentage, or None if invalid.
    """
    if odds1 == 0 or odds2 == 0:
        return None
    if abs(odds1) < 100 or abs(odds2) < 100:
        return None
    
    decimal1 = american_to_decimal(odds1)
    decimal2 = american_to_decimal(odds2)
    
    implied_prob1 = 1 / decimal1
    implied_prob2 = 1 / decimal2
    
    hold = (implied_prob1 + implied_prob2) - 1
    return hold if hold > 0 else None


def devig_two_way_american(
    side_american: float,
    opposing_american: float,
) -> dict[str, float] | None:
    """
    Remove vig from a two-way market represented by American odds.

    Returns:
        {
            "side_prob": <fair probability for side_american>,
            "opposing_prob": <fair probability for opposing_american>,
        }
        or None when the inputs are invalid.
    """
    try:
        side_decimal = american_to_decimal(float(side_american))
        opposing_decimal = american_to_decimal(float(opposing_american))
    except Exception:
        return None

    implied_side = 1 / side_decimal
    implied_opposing = 1 / opposing_decimal
    implied_total = implied_side + implied_opposing
    if implied_total <= 0:
        return None

    return {
        "side_prob": implied_side / implied_total,
        "opposing_prob": implied_opposing / implied_total,
    }


def calculate_close_calibration_metrics(
    predicted_prob: float,
    target_prob: float,
) -> dict[str, float] | None:
    """
    Compare a model's predicted probability to a proxy target probability.

    This uses the de-vigged close probability as the calibration target rather
    than a binary settled result. The metrics are still useful for comparing
    model versions during shadow rollout.
    """
    try:
        pred = float(predicted_prob)
        target = float(target_prob)
    except Exception:
        return None

    if not (0 < pred < 1 and 0 < target < 1):
        return None

    clipped_pred = min(max(pred, 1e-6), 1 - 1e-6)
    clipped_target = min(max(target, 1e-6), 1 - 1e-6)

    brier = (clipped_pred - clipped_target) ** 2
    log_loss = -(
        clipped_target * math.log(clipped_pred)
        + (1 - clipped_target) * math.log(1 - clipped_pred)
    )

    return {
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss, 6),
    }


def calculate_ev(
    stake: float,
    decimal_odds: float,
    promo_type: str,
    k_factor: float = 0.78,  # reserved for future fractional Kelly; currently unused
    boost_percent: float | None = None,
    winnings_cap: float | None = None,
    vig: float | None = None,
    true_prob: float | None = None,
) -> dict:
    """
    Calculate Expected Value based on promo type.
    
    Returns dict with:
        - ev_per_dollar: EV per $1 wagered
        - ev_total: Total EV for the stake
        - win_payout: What you'd receive if you win
    
    Promo types:
        - "standard": No promo, just a regular bet (EV = 0 for fair odds)
        - "bonus_bet": Free bet where you don't get stake back
        - "no_sweat": Refunded as bonus bet if you lose
        - "boost_30", "boost_50", "boost_100": Profit boosts
        - "boost_custom": Custom boost percentage (requires boost_percent)
    """
    
    # Determine effective boost percentage
    if promo_type == "boost_30":
        effective_boost = 0.30
    elif promo_type == "boost_50":
        effective_boost = 0.50
    elif promo_type == "boost_100":
        effective_boost = 1.00
    elif promo_type == "boost_custom" and boost_percent is not None:
        effective_boost = boost_percent / 100
    else:
        effective_boost = 0.0
    
    # Calculate win payout based on promo type
    if promo_type == "bonus_bet":
        # Bonus bet: you don't get the stake back, only winnings
        base_winnings = stake * (decimal_odds - 1)
        win_payout = base_winnings
    elif promo_type in ("boost_30", "boost_50", "boost_100", "boost_custom"):
        # Boosted bet: extra winnings on top of normal payout
        base_winnings = stake * (decimal_odds - 1)
        extra_winnings = base_winnings * effective_boost
        
        # Apply winnings cap if present
        if winnings_cap is not None and extra_winnings > winnings_cap:
            extra_winnings = winnings_cap
        
        win_payout = stake + base_winnings + extra_winnings
    else:
        # Standard or no-sweat: normal payout
        win_payout = stake * decimal_odds
    
    # Use provided vig or default
    effective_vig = vig if vig is not None else DEFAULT_VIG
    
    # Calculate EV per dollar based on promo type
    if promo_type == "bonus_bet":
        # EV = stake × (1 - 1/decimal_odds)
        # You're not risking real money, just potential winnings
        ev_per_dollar = 1 - (1 / decimal_odds)
        
    elif promo_type in ("no_sweat", "promo_qualifier"):
        # No-sweat and promo qualifiers: small negative EV due to vig on the initial leg
        # User logs the resulting bonus bet separately when received
        ev_per_dollar = -effective_vig
        
    elif promo_type in ("boost_30", "boost_50", "boost_100", "boost_custom"):
        # EV = (stake / decimal_odds) × min(boost% × (decimal_odds - 1), cap/stake) - vig
        # The boost provides value, but you still pay vig on the underlying market
        win_probability = 1 / decimal_odds
        potential_extra = effective_boost * (decimal_odds - 1)
        
        if winnings_cap is not None:
            capped_extra = min(potential_extra, winnings_cap / stake)
        else:
            capped_extra = potential_extra
            
        boost_value = win_probability * capped_extra
        ev_per_dollar = boost_value - effective_vig
        
    elif true_prob is not None:
        # Scanner bet: true probability known from Pinnacle de-vig.
        # EV = (true_prob × book_decimal) - 1  — same formula the scanner uses.
        ev_per_dollar = (true_prob * decimal_odds) - 1.0
    else:
        # Standard bet logged manually: no sharp reference, assume vig as cost.
        ev_per_dollar = -effective_vig
    
    ev_total = stake * ev_per_dollar
    
    return {
        "ev_per_dollar": round(ev_per_dollar, 6),
        "ev_total": round(ev_total, 2),
        "win_payout": round(win_payout, 2),
        "decimal_odds": round(decimal_odds, 4),
    }


def calculate_clv(
    book_american: float,
    close_pinnacle_american: float,
    close_opposing_american: float | None = None,
) -> dict:
    """
    Closing Line Value: measures edge of the logged bet against Pinnacle's
    closing line. Positive = you beat the market.

    Formula (same as calculate_edge, but using the closing Pinnacle line):
        true_close_prob  = 1 / decimal(close_pinnacle)
        clv_ev_percent   = (true_close_prob × book_decimal − 1) × 100

    Args:
        book_american:          American odds you got from the target book.
        close_pinnacle_american: Pinnacle's American odds for the same outcome at close.

    Returns:
        clv_ev_percent:  Edge vs. close (positive = beat the close).
        close_true_prob: Pinnacle's closing implied probability.
        book_decimal:    Your book's decimal odds.
        beat_close:      True when clv_ev_percent > 0.
    """
    book_decimal = american_to_decimal(book_american)
    close_quality = "single"
    paired_probs = None
    if close_opposing_american is not None:
        paired_probs = devig_two_way_american(close_pinnacle_american, close_opposing_american)
    if paired_probs:
        close_true_prob = paired_probs["side_prob"]
        close_quality = "paired"
    else:
        close_decimal = american_to_decimal(close_pinnacle_american)
        close_true_prob = 1.0 / close_decimal
    ev_raw = (close_true_prob * book_decimal) - 1.0

    return {
        "clv_ev_percent": round(ev_raw * 100, 2),
        "close_true_prob": round(close_true_prob, 4),
        "book_decimal": round(book_decimal, 4),
        "beat_close": ev_raw > 0,
        "close_quality": close_quality,
        "close_opposing_american": round(float(close_opposing_american), 4) if close_opposing_american is not None else None,
    }


def calculate_real_profit(
    stake: float,
    win_payout: float,
    result: str,
    promo_type: str,
) -> float | None:
    """
    Calculate actual profit/loss after bet settles.
    
    Returns:
        - Profit (positive) or loss (negative)
        - None if bet is not settled
    """
    if result not in ("win", "loss", "push", "void"):
        return None
    
    if result == "win":
        if promo_type == "bonus_bet":
            # Bonus bet win: you just get the payout (stake wasn't real money)
            return win_payout
        else:
            # Normal win: payout minus your stake
            return win_payout - stake
            
    elif result == "loss":
        if promo_type == "bonus_bet":
            # Bonus bet loss: you lose nothing (it was free)
            return 0.0
        else:
            # Normal loss: you lose your stake
            return -stake
            
    else:  # push or void
        return 0.0


# ── Personalized k-factor helpers ──────────────────────────────────────────────

def compute_blend_weight(
    bonus_stake_settled: float,
    min_stake: float = 300.0,
    smoothing_stake: float = 700.0,
) -> float:
    """
    Return blending weight w ∈ [0, 1) that grows as more bonus-bet stake settles.
    w = 0 until min_stake is reached, then asymptotes smoothly toward 1.
    """
    if bonus_stake_settled < min_stake:
        return 0.0
    excess = bonus_stake_settled - min_stake
    return excess / (excess + smoothing_stake)
