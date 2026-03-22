"""
Pydantic Models
Define the data structures for bets and API requests/responses.
"""

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


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


ScannerSurface = Literal["straight_bets", "player_props"]


class BetCreate(BaseModel):
    """Schema for creating a new bet."""

    sport: str
    event: str
    market: str  # ML, Spread, Total, SGP, Prop
    surface: ScannerSurface = "straight_bets"
    sportsbook: str
    promo_type: PromoType
    odds_american: float
    stake: float = Field(gt=0)
    boost_percent: float | None = None
    winnings_cap: float | None = None
    notes: str | None = None
    event_date: date | None = None
    opposing_odds: float | None = None
    payout_override: float | None = None
    pinnacle_odds_at_entry: float | None = None
    commence_time: str | None = None
    clv_team: str | None = None
    clv_sport_key: str | None = None
    clv_event_id: str | None = None
    true_prob_at_entry: float | None = None
    source_event_id: str | None = None
    source_market_key: str | None = None
    source_selection_key: str | None = None
    participant_name: str | None = None
    participant_id: str | None = None
    selection_side: str | None = None
    line_value: float | None = None
    selection_meta: dict[str, Any] | None = None


class BetUpdate(BaseModel):
    """Schema for updating an existing bet."""

    sport: str | None = None
    event: str | None = None
    market: str | None = None
    surface: ScannerSurface | None = None
    sportsbook: str | None = None
    promo_type: PromoType | None = None
    odds_american: float | None = None
    stake: float | None = Field(default=None, gt=0)
    boost_percent: float | None = None
    winnings_cap: float | None = None
    notes: str | None = None
    result: BetResult | None = None
    payout_override: float | None = None
    opposing_odds: float | None = None
    event_date: date | None = None


class BetResponse(BaseModel):
    """Schema for bet data returned from API."""

    id: str
    created_at: datetime
    event_date: date
    settled_at: datetime | None
    sport: str
    event: str
    market: str
    surface: ScannerSurface = "straight_bets"
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
    win_payout: float
    ev_per_dollar: float
    ev_total: float
    real_profit: float | None
    pinnacle_odds_at_entry: float | None = None
    pinnacle_odds_at_close: float | None = None
    clv_updated_at: datetime | None = None
    commence_time: str | None = None
    clv_team: str | None = None
    clv_sport_key: str | None = None
    clv_event_id: str | None = None
    true_prob_at_entry: float | None = None
    clv_ev_percent: float | None = None
    beat_close: bool | None = None
    ev_per_dollar_locked: float | None = None
    ev_total_locked: float | None = None
    win_payout_locked: float | None = None
    ev_lock_version: int = 1
    is_paper: bool = False
    strategy_cohort: str | None = None
    auto_logged: bool = False
    auto_log_run_at: datetime | None = None
    auto_log_run_key: str | None = None
    scan_ev_percent_at_log: float | None = None
    book_odds_at_log: float | None = None
    reference_odds_at_log: float | None = None
    source_event_id: str | None = None
    source_market_key: str | None = None
    source_selection_key: str | None = None
    participant_name: str | None = None
    participant_id: str | None = None
    selection_side: str | None = None
    line_value: float | None = None
    selection_meta: dict[str, Any] | None = None


class SettingsUpdate(BaseModel):
    """User settings."""

    k_factor: float | None = Field(default=None, ge=0, le=1)
    default_stake: float | None = None
    preferred_sportsbooks: list[str] | None = None
    k_factor_mode: str | None = None
    k_factor_min_stake: float | None = None
    k_factor_smoothing: float | None = None
    k_factor_clamp_min: float | None = None
    k_factor_clamp_max: float | None = None
    onboarding_state: dict[str, Any] | None = None


class SettingsResponse(BaseModel):
    """Settings returned from API."""

    k_factor: float
    default_stake: float | None
    preferred_sportsbooks: list[str]
    k_factor_mode: str
    k_factor_min_stake: float
    k_factor_smoothing: float
    k_factor_clamp_min: float
    k_factor_clamp_max: float
    k_factor_observed: float | None
    k_factor_weight: float
    k_factor_effective: float
    k_factor_bonus_stake_settled: float
    onboarding_state: dict[str, Any] | None = None


class SummaryResponse(BaseModel):
    """Dashboard summary statistics."""

    total_bets: int
    pending_bets: int
    total_ev: float
    total_real_profit: float
    variance: float
    win_count: int
    loss_count: int
    win_rate: float | None
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
    net_deposits: float
    profit: float
    pending: float
    balance: float


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
    events_fetched: int
    events_with_both_books: int
    api_requests_remaining: str | None = None


class StraightBetSide(BaseModel):
    """A single side with odds from a target book and true probability."""

    surface: Literal["straight_bets"] = "straight_bets"
    event_id: str | None = None
    market_key: str = "h2h"
    selection_key: str | None = None
    sportsbook: str
    sportsbook_deeplink_url: str | None = None
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


class PlayerPropSide(BaseModel):
    """A player prop selection with surface-aware identity fields."""

    surface: Literal["player_props"] = "player_props"
    event_id: str | None = None
    market_key: str
    selection_key: str
    sportsbook: str
    sportsbook_deeplink_url: str | None = None
    sport: str
    event: str
    commence_time: str
    market: str
    player_name: str
    participant_id: str | None = None
    team: str | None = None
    opponent: str | None = None
    selection_side: str
    line_value: float | None = None
    display_name: str
    reference_odds: float
    reference_source: str
    reference_bookmakers: list[str]
    reference_bookmaker_count: int | None = None
    confidence_label: str | None = None
    book_odds: float
    true_prob: float
    base_kelly_fraction: float
    book_decimal: float
    ev_percentage: float
    scanner_duplicate_state: Literal["new", "already_logged", "better_now"] | None = None
    best_logged_odds_american: float | None = None
    current_odds_american: float | None = None
    matched_pending_bet_id: str | None = None


class PlayerPropDiagnosticGame(BaseModel):
    """A shortlisted scoreboard game and its mapping status."""

    event_id: str | None = None
    away_team: str
    home_team: str
    selection_reason: str
    broadcasts: list[str]
    odds_event_id: str | None = None
    commence_time: str | None = None
    matched: bool = False


class PlayerPropScanDiagnostics(BaseModel):
    """High-level diagnostics for the manual player-prop sniper flow."""

    scan_mode: str
    scoreboard_event_count: int
    odds_event_count: int
    curated_games: list[PlayerPropDiagnosticGame]
    matched_event_count: int
    unmatched_game_count: int
    events_fetched: int
    events_skipped_pregame: int
    events_with_results: int
    candidate_sides_count: int = 0
    quality_gate_filtered_count: int = 0
    quality_gate_min_reference_bookmakers: int = 0
    sides_count: int
    markets_requested: list[str]


ScannerSide = Annotated[StraightBetSide | PlayerPropSide, Field(discriminator="surface")]
MarketSide = StraightBetSide


class FullScanResponse(BaseModel):
    """Response from the full market scanner, by surface."""

    surface: ScannerSurface
    sport: str
    sides: list[ScannerSide]
    events_fetched: int
    events_with_both_books: int
    api_requests_remaining: str | None = None
    scanned_at: str | None = None
    diagnostics: PlayerPropScanDiagnostics | None = None
