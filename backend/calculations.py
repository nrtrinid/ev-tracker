"""
EV Calculation Engine
Ports the Excel spreadsheet formulas to Python.
"""

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


def calculate_ev(
    stake: float,
    decimal_odds: float,
    promo_type: str,
    k_factor: float = 0.78,
    boost_percent: float | None = None,
    winnings_cap: float | None = None,
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
    
    # Calculate EV per dollar based on promo type
    if promo_type == "bonus_bet":
        # EV = stake × (1 - 1/decimal_odds)
        # You're not risking real money, just potential winnings
        ev_per_dollar = 1 - (1 / decimal_odds)
        
    elif promo_type in ("no_sweat", "promo_qualifier"):
        # No-sweat and promo qualifiers: small negative EV due to vig on the initial leg
        # User logs the resulting bonus bet separately when received
        ev_per_dollar = -DEFAULT_VIG
        
    elif promo_type in ("boost_30", "boost_50", "boost_100", "boost_custom"):
        # EV = (stake / decimal_odds) × min(boost% × (decimal_odds - 1), cap/stake)
        # The boost only provides value proportional to win probability
        win_probability = 1 / decimal_odds
        potential_extra = effective_boost * (decimal_odds - 1)
        
        if winnings_cap is not None:
            capped_extra = min(potential_extra, winnings_cap / stake)
        else:
            capped_extra = potential_extra
            
        ev_per_dollar = win_probability * capped_extra
        
    else:
        # Standard bet: EV is 0 for fair odds (we assume user finds +EV spots)
        ev_per_dollar = 0.0
    
    ev_total = stake * ev_per_dollar
    
    return {
        "ev_per_dollar": round(ev_per_dollar, 6),
        "ev_total": round(ev_total, 2),
        "win_payout": round(win_payout, 2),
        "decimal_odds": round(decimal_odds, 4),
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
