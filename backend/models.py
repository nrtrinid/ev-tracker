"""
Pydantic Models
Define the data structures for bets and API requests/responses.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class PromoType(str, Enum):
    """Promo types that determine EV calculation method."""
    STANDARD = "standard"
    BONUS_BET = "bonus_bet"
    NO_SWEAT = "no_sweat"
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
    date: datetime
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
    
    # Optional override for edge cases
    payout_override: float | None = None


class BetUpdate(BaseModel):
    """Schema for updating an existing bet."""
    date: datetime | None = None
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


class BetResponse(BaseModel):
    """Schema for bet data returned from API."""
    id: str
    created_at: datetime
    date: datetime
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
    result: BetResult
    
    # Calculated fields
    win_payout: float
    ev_per_dollar: float
    ev_total: float
    real_profit: float | None


class SettingsUpdate(BaseModel):
    """User settings."""
    k_factor: float = Field(default=0.78, ge=0, le=1)
    default_stake: float | None = None
    preferred_sportsbooks: list[str] | None = None


class SettingsResponse(BaseModel):
    """Settings returned from API."""
    k_factor: float
    default_stake: float | None
    preferred_sportsbooks: list[str]


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
