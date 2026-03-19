"""
Pydantic Models
Define the data structures for bets and API requests/responses.
"""

from pydantic import BaseModel, Field
from datetime import datetime, date
from enum import Enum
from typing import Literal


class PromoType(str, Enum):
    """Promo types that determine EV calculation method."""
    STANDARD = "standard"
    BONUS_BET = "bonus_bet"
    NO_SWEAT = "no_sweat"
    PROMO_QUALIFIER = "promo_qualifier"
    BOOST_30 = "boost_30"
    BOOST_50 = "boost_50"
    BOOST_100 = "boost_100"
    BOOST_CUSTOM = "boost_custom"


class BetResult(str, Enum):
    """Possible outcomes for a bet."""
    PENDING = "pending"
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"
    VOID = "void"


class BetCreate(BaseModel):
    """Schema for creating a new bet."""
    sport: str
    event: str
    market: str  # ML, Spread, Total, SGP, Prop
    sportsbook: str
    promo_type: PromoType
    odds_american: float
    stake: float = Field(gt=0)
    boost_percent: float | None = None  # For custom boosts
    winnings_cap: float | None = None
    notes: str | None = None
    event_date: date | None = None  # Defaults to today if not provided
    opposing_odds: float | None = None  # For accurate vig calculation

    # Optional override for edge cases
    payout_override: float | None = None

    # CLV tracking — populated automatically when logging from scanner
    pinnacle_odds_at_entry: float | None = None  # Pinnacle line for this side at bet time
    commence_time: str | None = None             # ISO-8601 game start (for snapshot matching)
    clv_team: str | None = None                  # Team name (e.g. "Los Angeles Lakers")
    clv_sport_key: str | None = None             # Odds API key (e.g. "basketball_nba")
    true_prob_at_entry: float | None = None      # De-vigged Pinnacle probability — enables accurate EV for standard scanner bets


class BetUpdate(BaseModel):
    """Schema for updating an existing bet."""
    sport: str | None = None
    event: str | None = None
    market: str | None = None
    sportsbook: str | None = None
    promo_type: PromoType | None = None
    odds_american: float | None = None
    stake: float | None = Field(default=None, gt=0)
    boost_percent: float | None = None
    winnings_cap: float | None = None
    notes: str | None = None
    result: BetResult | None = None
    payout_override: float | None = None
    opposing_odds: float | None = None  # For accurate vig calculation
    event_date: date | None = None  # Allow correction in Edit modal


class BetResponse(BaseModel):
    """Schema for bet data returned from API."""
    id: str
    created_at: datetime
    event_date: date
    settled_at: datetime | None
    sport: str
    event: str
    market: str
    sportsbook: str
    promo_type: PromoType
    odds_american: float
    odds_decimal: float
    stake: float
    boost_percent: float | None
    winnings_cap: float | None
    notes: str | None
    opposing_odds: float | None
    result: BetResult

    # Calculated fields
    win_payout: float
    ev_per_dollar: float
    ev_total: float
    real_profit: float | None

    # CLV fields
    pinnacle_odds_at_entry: float | None = None
    pinnacle_odds_at_close: float | None = None
    clv_updated_at: datetime | None = None
    commence_time: str | None = None
    clv_team: str | None = None
    clv_sport_key: str | None = None
    true_prob_at_entry: float | None = None
    # Calculated CLV — only set when both entry and close Pinnacle odds are present
    clv_ev_percent: float | None = None
    beat_close: bool | None = None

    # Locked EV — frozen at bet-creation time so history is stable when k updates
    ev_per_dollar_locked: float | None = None
    ev_total_locked: float | None = None
    win_payout_locked: float | None = None
    ev_lock_version: int = 1

    # Paper experiment metadata (server-managed)
    is_paper: bool = False
    strategy_cohort: str | None = None
    auto_logged: bool = False
    auto_log_run_at: datetime | None = None
    auto_log_run_key: str | None = None
    scan_ev_percent_at_log: float | None = None
    book_odds_at_log: float | None = None
    reference_odds_at_log: float | None = None


class SettingsUpdate(BaseModel):
    """User settings."""
    k_factor: float | None = Field(default=None, ge=0, le=1)
    default_stake: float | None = None
    preferred_sportsbooks: list[str] | None = None
    # Personalized k-factor auto mode
    k_factor_mode: str | None = None          # 'baseline' | 'auto'
    k_factor_min_stake: float | None = None   # minimum bonus stake to start blending
    k_factor_smoothing: float | None = None   # smoothing stake denominator
    k_factor_clamp_min: float | None = None
    k_factor_clamp_max: float | None = None


class SettingsResponse(BaseModel):
    """Settings returned from API."""
    k_factor: float
    default_stake: float | None
    preferred_sportsbooks: list[str]
    # Personalized k-factor auto mode
    k_factor_mode: str
    k_factor_min_stake: float
    k_factor_smoothing: float
    k_factor_clamp_min: float
    k_factor_clamp_max: float
    # Derived fields (computed from settled bonus bets)
    k_factor_observed: float | None       # user's actual observed retention
    k_factor_weight: float                # current blend weight w
    k_factor_effective: float             # effective k actually used = (1-w)*k0 + w*k_obs
    k_factor_bonus_stake_settled: float   # total settled bonus stake (sample size indicator)


class SummaryResponse(BaseModel):
    """Dashboard summary statistics."""
    total_bets: int
    pending_bets: int
    total_ev: float
    total_real_profit: float
    variance: float  # Real Profit - EV
    win_count: int
    loss_count: int
    win_rate: float | None  # None if no settled bets
    
    # Breakdowns
    ev_by_sportsbook: dict[str, float]
    profit_by_sportsbook: dict[str, float]
    ev_by_sport: dict[str, float]


class TransactionType(str, Enum):
    """Transaction types for bankroll tracking."""
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"


class TransactionCreate(BaseModel):
    """Schema for creating a transaction."""
    sportsbook: str
    type: TransactionType
    amount: float = Field(gt=0)
    notes: str | None = None
    created_at: datetime | None = None


class TransactionResponse(BaseModel):
    """Schema for transaction data returned from API."""
    id: str
    created_at: datetime
    sportsbook: str
    type: TransactionType
    amount: float
    notes: str | None


class BalanceResponse(BaseModel):
    """Per-sportsbook balance."""
    sportsbook: str
    deposits: float
    withdrawals: float
    net_deposits: float  # deposits - withdrawals
    profit: float        # from betting
    pending: float       # pending exposure
    balance: float       # net_deposits + profit - pending


class EVOpportunity(BaseModel):
    """A single +EV bet opportunity from the odds scanner."""
    sportsbook: str
    sport: str
    event: str
    commence_time: str
    team: str
    pinnacle_odds: float
    book_odds: float
    true_prob: float
    base_kelly_fraction: float
    ev_percentage: float
    book_decimal: float


class ScanResponse(BaseModel):
    """Response from the odds scanner endpoint."""
    sport: str
    opportunities: list[EVOpportunity]
    events_fetched: int  # events returned by the Odds API
    events_with_both_books: int  # events that had Pinnacle + DraftKings
    api_requests_remaining: str | None = None


class MarketSide(BaseModel):
    """A single side (team) with odds from a target book and true probability."""
    sportsbook: str
    sport: str
    event: str
    commence_time: str
    team: str
    pinnacle_odds: float
    book_odds: float
    true_prob: float
    base_kelly_fraction: float
    book_decimal: float
    ev_percentage: float
    scanner_duplicate_state: Literal["new", "already_logged", "better_now"] | None = None
    best_logged_odds_american: float | None = None
    current_odds_american: float | None = None
    matched_pending_bet_id: str | None = None


class FullScanResponse(BaseModel):
    """Response from the full market scanner — all sides, not just +EV."""
    sport: str  # "all" for full scan, or single sport key
    sides: list[MarketSide]
    events_fetched: int
    events_with_both_books: int
    api_requests_remaining: str | None = None
    scanned_at: str | None = None  # ISO datetime of oldest cache used (for "Data as of X min ago")
