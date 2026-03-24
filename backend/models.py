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
BetSurface = Literal["straight_bets", "player_props", "parlay"]
ScannerDeeplinkLevel = Literal["selection", "market", "event", "homepage"]


class BetCreate(BaseModel):
    """Schema for creating a new bet."""

    sport: str
    event: str
    market: str  # ML, Spread, Total, SGP, Prop
    surface: BetSurface = "straight_bets"
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
    surface: BetSurface | None = None
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
    surface: BetSurface = "straight_bets"
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
    kelly_multiplier: float | None = Field(default=None, gt=0)
    bankroll_override: float | None = Field(default=None, ge=0)
    use_computed_bankroll: bool | None = None
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
    kelly_multiplier: float
    bankroll_override: float
    use_computed_bankroll: bool
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
    sportsbook_deeplink_level: ScannerDeeplinkLevel | None = None
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
    sportsbook_deeplink_level: ScannerDeeplinkLevel | None = None
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


class PrizePicksComparisonCard(BaseModel):
    """A read-only PrizePicks line compared against exact-line sportsbook consensus."""

    comparison_key: str
    event_id: str | None = None
    sport: str
    event: str
    commence_time: str
    player_name: str
    participant_id: str | None = None
    team: str | None = None
    opponent: str | None = None
    market_key: str
    market: str
    prizepicks_line: float
    exact_line_bookmakers: list[str]
    exact_line_bookmaker_count: int
    consensus_over_prob: float
    consensus_under_prob: float
    consensus_side: Literal["over", "under"]
    confidence_label: str
    best_over_sportsbook: str | None = None
    best_over_odds: float | None = None
    best_over_deeplink_url: str | None = None
    best_under_sportsbook: str | None = None
    best_under_odds: float | None = None
    best_under_deeplink_url: str | None = None


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
    scan_scope: str | None = None
    scoreboard_event_count: int
    odds_event_count: int
    curated_games: list[PlayerPropDiagnosticGame]
    matched_event_count: int
    unmatched_game_count: int
    fallback_reason: str | None = None
    fallback_event_count: int = 0
    events_fetched: int
    events_skipped_pregame: int
    events_with_results: int
    candidate_sides_count: int = 0
    quality_gate_filtered_count: int = 0
    quality_gate_min_reference_bookmakers: int = 0
    sides_count: int
    markets_requested: list[str]
    prizepicks_status: str | None = None
    prizepicks_message: str | None = None
    prizepicks_board_items_count: int = 0
    prizepicks_exact_line_matches_count: int = 0
    prizepicks_unmatched_count: int = 0
    prizepicks_filtered_count: int = 0


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
    prizepicks_cards: list[PrizePicksComparisonCard] | None = None


class ResearchOpportunityBreakdownItem(BaseModel):
    """Aggregate summary row for research-opportunity breakdowns."""

    key: str
    captured_count: int
    clv_ready_count: int
    beat_close_pct: float | None = None
    avg_clv_percent: float | None = None


class ResearchOpportunityRecentRow(BaseModel):
    """Recent research-opportunity row for operator spot checks."""

    opportunity_key: str
    first_seen_at: datetime
    last_seen_at: datetime
    commence_time: str
    sport: str
    event: str
    team: str
    sportsbook: str
    market: str
    event_id: str | None = None
    first_source: str
    seen_count: int
    first_ev_percentage: float
    first_book_odds: float
    best_book_odds: float
    latest_reference_odds: float | None = None
    reference_odds_at_close: float | None = None
    clv_ev_percent: float | None = None
    beat_close: bool | None = None


class ResearchOpportunitySummaryResponse(BaseModel):
    """Internal operator summary for the scan-opportunity research ledger."""

    captured_count: int
    open_count: int
    close_captured_count: int
    clv_ready_count: int
    beat_close_pct: float | None = None
    avg_clv_percent: float | None = None
    by_source: list[ResearchOpportunityBreakdownItem]
    by_sportsbook: list[ResearchOpportunityBreakdownItem]
    by_edge_bucket: list[ResearchOpportunityBreakdownItem]
    by_odds_bucket: list[ResearchOpportunityBreakdownItem]
    recent_opportunities: list[ResearchOpportunityRecentRow]


class ParlayWarning(BaseModel):
    """A correlation or pricing warning attached to a parlay slip."""

    code: str
    severity: Literal["warning", "blocking"]
    title: str
    detail: str
    relatedLegIds: list[str] = Field(default_factory=list)


class ParlayPricingPreview(BaseModel):
    """Saved pricing snapshot for an active/saved parlay slip."""

    legCount: int
    sportsbook: str | None = None
    combinedDecimalOdds: float
    combinedAmericanOdds: float
    stake: float | None = None
    totalPayout: float | None = None
    profit: float | None = None
    estimatedFairDecimalOdds: float | None = None
    estimatedFairAmericanOdds: float | None = None
    estimatedTrueProbability: float | None = None
    estimatedEvPercent: float | None = None
    estimateAvailable: bool = False
    estimateUnavailableReason: str | None = None
    hasBlockingCorrelation: bool = False
    warnings: list[ParlayWarning] = Field(default_factory=list)


class ParlaySlipLeg(BaseModel):
    """Saved cart-leg snapshot for a parlay draft."""

    id: str
    surface: ScannerSurface
    eventId: str | None = None
    marketKey: str
    selectionKey: str
    sportsbook: str
    oddsAmerican: float
    referenceOddsAmerican: float | None = None
    referenceSource: str | None = None
    display: str
    event: str
    sport: str
    commenceTime: str
    correlationTags: list[str] = Field(default_factory=list)
    team: str | None = None
    participantName: str | None = None
    participantId: str | None = None
    selectionSide: str | None = None
    lineValue: float | None = None
    marketDisplay: str | None = None
    sourceEventId: str | None = None
    sourceMarketKey: str | None = None
    sourceSelectionKey: str | None = None
    selectionMeta: dict[str, Any] | None = None


class ParlaySlipCreate(BaseModel):
    """Create a saved parlay draft."""

    sportsbook: str
    stake: float | None = Field(default=None, ge=0)
    legs: list[ParlaySlipLeg]
    warnings: list[ParlayWarning] = Field(default_factory=list)
    pricingPreview: ParlayPricingPreview | None = None


class ParlaySlipUpdate(BaseModel):
    """Update a saved parlay draft."""

    sportsbook: str | None = None
    stake: float | None = Field(default=None, ge=0)
    legs: list[ParlaySlipLeg] | None = None
    warnings: list[ParlayWarning] | None = None
    pricingPreview: ParlayPricingPreview | None = None


class ParlaySlipResponse(BaseModel):
    """Saved parlay draft returned by the API."""

    id: str
    created_at: datetime
    updated_at: datetime
    sportsbook: str
    stake: float | None = None
    legs: list[ParlaySlipLeg]
    warnings: list[ParlayWarning]
    pricingPreview: ParlayPricingPreview | None = None
    logged_bet_id: str | None = None


class ParlaySlipLogRequest(BaseModel):
    """User-confirmed logging details for a saved parlay slip."""

    sport: str | None = None
    event: str | None = None
    promo_type: PromoType = PromoType.STANDARD
    odds_american: float
    stake: float = Field(gt=0)
    boost_percent: float | None = None
    winnings_cap: float | None = None
    notes: str | None = None
    event_date: date | None = None
    opposing_odds: float | None = None
    payout_override: float | None = None
