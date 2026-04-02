// Types matching the FastAPI backend models

export type PromoType =
  | "standard"
  | "bonus_bet"
  | "no_sweat"
  | "promo_qualifier"
  | "boost_30"
  | "boost_50"
  | "boost_100"
  | "boost_custom";

export type BetResult = "pending" | "win" | "loss" | "push" | "void";
export type ScannerSurface = "straight_bets" | "player_props";
export type BetSurface = ScannerSurface | "parlay";

export interface Bet {
  id: string;
  created_at: string;
  event_date: string;
  settled_at: string | null;
  sport: string;
  event: string;
  market: string;
  surface: BetSurface;
  sportsbook: string;
  promo_type: PromoType;
  odds_american: number;
  odds_decimal: number;
  stake: number;
  boost_percent: number | null;
  winnings_cap: number | null;
  payout_override?: number | null;
  notes: string | null;
  opposing_odds: number | null;
  result: BetResult;
  win_payout: number;
  ev_per_dollar: number;
  ev_total: number;
  real_profit: number | null;
  // CLV tracking
  pinnacle_odds_at_entry: number | null;
  latest_pinnacle_odds: number | null;
  latest_pinnacle_updated_at: string | null;
  pinnacle_odds_at_close: number | null;
  clv_updated_at: string | null;
  commence_time: string | null;
  clv_team: string | null;
  clv_sport_key: string | null;
  clv_event_id: string | null;
  clv_ev_percent: number | null;  // computed: edge vs. Pinnacle close
  beat_close: boolean | null;
  // V1 paper experiment metadata
  is_paper: boolean;
  strategy_cohort: string | null;
  auto_logged: boolean;
  auto_log_run_at: string | null;
  auto_log_run_key: string | null;
  scan_ev_percent_at_log: number | null;
  book_odds_at_log: number | null;
  reference_odds_at_log: number | null;
  source_event_id: string | null;
  source_market_key: string | null;
  source_selection_key: string | null;
  participant_name: string | null;
  participant_id: string | null;
  selection_side: string | null;
  line_value: number | null;
  selection_meta: LoggedParlaySelectionMeta | Record<string, unknown> | null;
}

export interface BetCreate {
  sport: string;
  event: string;
  market: string;
  surface?: BetSurface;
  sportsbook: string;
  promo_type: PromoType;
  odds_american: number;
  stake: number;
  boost_percent?: number;
  winnings_cap?: number;
  notes?: string;
  payout_override?: number;
  opposing_odds?: number;
  event_date?: string;
  // CLV — auto-populated when logging from scanner
  pinnacle_odds_at_entry?: number;
  commence_time?: string;
  clv_team?: string;
  clv_sport_key?: string;
  clv_event_id?: string;
  true_prob_at_entry?: number;
  source_event_id?: string;
  source_market_key?: string;
  source_selection_key?: string;
  participant_name?: string;
  participant_id?: string;
  selection_side?: string;
  line_value?: number;
  selection_meta?: LoggedParlaySelectionMeta | Record<string, unknown>;
}

export interface BetUpdate {
  sport?: string;
  event?: string;
  market?: string;
  surface?: BetSurface;
  sportsbook?: string;
  promo_type?: PromoType;
  odds_american?: number;
  stake?: number;
  boost_percent?: number | null;
  winnings_cap?: number | null;
  notes?: string | null;
  result?: BetResult;
  payout_override?: number | null;
  opposing_odds?: number | null;
  event_date?: string | null;
}

export interface Settings {
  k_factor: number;
  default_stake: number | null;
  preferred_sportsbooks: string[];
  kelly_multiplier: number;
  bankroll_override: number;
  use_computed_bankroll: boolean;
  // Personalized k-factor auto mode
  k_factor_mode: string;             // 'baseline' | 'auto'
  k_factor_min_stake: number;
  k_factor_smoothing: number;
  k_factor_clamp_min: number;
  k_factor_clamp_max: number;
  // Derived fields (computed server-side from settled bonus bets)
  k_factor_observed: number | null;
  k_factor_weight: number;
  k_factor_effective: number;
  k_factor_bonus_stake_settled: number;
  onboarding_state: {
    version?: number;
    completed?: string[];
    dismissed?: string[];
    last_seen_at?: string | null;
  } | null;
}

export interface Summary {
  total_bets: number;
  pending_bets: number;
  total_ev: number;
  total_real_profit: number;
  variance: number;
  win_count: number;
  loss_count: number;
  win_rate: number | null;
  ev_by_sportsbook: Record<string, number>;
  profit_by_sportsbook: Record<string, number>;
  ev_by_sport: Record<string, number>;
}

export interface EVCalculation {
  odds_american: number;
  odds_decimal: number;
  stake: number;
  promo_type: string;
  ev_per_dollar: number;
  ev_total: number;
  win_payout: number;
}

// Transaction types
export type TransactionType = "deposit" | "withdrawal";

export interface Transaction {
  id: string;
  created_at: string;
  sportsbook: string;
  type: TransactionType;
  amount: number;
  notes: string | null;
}

export interface TransactionCreate {
  sportsbook: string;
  type: TransactionType;
  amount: number;
  notes?: string;
  created_at?: string; // For undo functionality to preserve original timestamp
}

export interface Balance {
  sportsbook: string;
  deposits: number;
  withdrawals: number;
  net_deposits: number;
  profit: number;
  pending: number;
  balance: number;
}

// Scanner types
export type SportsbookDeeplinkLevel = "selection" | "market" | "event" | "homepage";

export interface StraightBetMarketSide {
  surface: "straight_bets";
  event_id?: string | null;
  market_key?: string;
  selection_key?: string | null;
  selection_side?: string | null;
  line_value?: number | null;
  sportsbook: string;
  sportsbook_deeplink_url?: string | null;
  sportsbook_deeplink_level?: SportsbookDeeplinkLevel | null;
  sport: string;
  event: string;
  event_short?: string | null;
  commence_time: string;
  team: string;
  team_short?: string | null;
  opponent_short?: string | null;
  pinnacle_odds: number;
  book_odds: number;
  true_prob: number;
  base_kelly_fraction: number;
  book_decimal: number;
  ev_percentage: number;
  scanner_duplicate_state?: "new" | "logged_elsewhere" | "already_logged" | "better_now";
  best_logged_odds_american?: number | null;
  current_odds_american?: number | null;
  matched_pending_bet_id?: string | null;
}

export interface PlayerPropMarketSide {
  surface: "player_props";
  event_id?: string | null;
  market_key: string;
  selection_key: string;
  sportsbook: string;
  sportsbook_deeplink_url?: string | null;
  sportsbook_deeplink_level?: SportsbookDeeplinkLevel | null;
  sport: string;
  event: string;
  event_short?: string | null;
  commence_time: string;
  market: string;
  player_name: string;
  participant_id?: string | null;
  team?: string | null;
  team_short?: string | null;
  opponent?: string | null;
  opponent_short?: string | null;
  selection_side: string;
  line_value?: number | null;
  display_name: string;
  reference_odds: number;
  reference_source: string;
  reference_bookmakers?: string[];
  reference_bookmaker_count?: number | null;
  confidence_label?: string | null;
  confidence_score?: number | null;
  prob_std?: number | null;
  book_odds: number;
  true_prob: number;
  base_kelly_fraction: number;
  book_decimal: number;
  ev_percentage: number;
  scanner_duplicate_state?: "new" | "logged_elsewhere" | "already_logged" | "better_now";
  best_logged_odds_american?: number | null;
  current_odds_american?: number | null;
  matched_pending_bet_id?: string | null;
}

export interface PrizePicksComparisonCard {
  comparison_key: string;
  event_id?: string | null;
  sport: string;
  event: string;
  event_short?: string | null;
  commence_time: string;
  player_name: string;
  participant_id?: string | null;
  team?: string | null;
  team_short?: string | null;
  opponent?: string | null;
  opponent_short?: string | null;
  market_key: string;
  market: string;
  prizepicks_line: number;
  exact_line_bookmakers: string[];
  exact_line_bookmaker_count: number;
  consensus_over_prob: number;
  consensus_under_prob: number;
  consensus_side: "over" | "under";
  confidence_label: string;
  best_over_sportsbook?: string | null;
  best_over_odds?: number | null;
  best_over_deeplink_url?: string | null;
  best_under_sportsbook?: string | null;
  best_under_odds?: number | null;
  best_under_deeplink_url?: string | null;
}

export type MarketSide = StraightBetMarketSide | PlayerPropMarketSide;

export interface PlayerPropBoardItem {
  surface: "player_props";
  event_id?: string | null;
  market_key: string;
  selection_key: string;
  sportsbook: string;
  sportsbook_deeplink_url?: string | null;
  sportsbook_deeplink_level?: SportsbookDeeplinkLevel | null;
  sport: string;
  event: string;
  event_short?: string | null;
  commence_time: string;
  market: string;
  player_name: string;
  participant_id?: string | null;
  team?: string | null;
  team_short?: string | null;
  opponent?: string | null;
  opponent_short?: string | null;
  selection_side: string;
  line_value?: number | null;
  display_name: string;
  reference_odds: number;
  reference_source: string;
  reference_bookmaker_count?: number | null;
  confidence_label?: string | null;
  book_odds: number;
  true_prob: number;
  base_kelly_fraction: number;
  book_decimal: number;
  ev_percentage: number;
  scanner_duplicate_state?: "new" | "logged_elsewhere" | "already_logged" | "better_now";
  best_logged_odds_american?: number | null;
  current_odds_american?: number | null;
  matched_pending_bet_id?: string | null;
}

export interface PlayerPropBoardDetail {
  selection_key: string;
  sportsbook: string;
  reference_bookmakers: string[];
  reference_bookmaker_count?: number | null;
}

export interface PlayerPropBoardPickEmCard {
  comparison_key: string;
  event_id?: string | null;
  sport: string;
  event: string;
  event_short?: string | null;
  commence_time: string;
  player_name: string;
  participant_id?: string | null;
  team?: string | null;
  team_short?: string | null;
  opponent?: string | null;
  opponent_short?: string | null;
  market_key: string;
  market: string;
  line_value: number;
  exact_line_bookmakers: string[];
  exact_line_bookmaker_count: number;
  consensus_over_prob: number;
  consensus_under_prob: number;
  consensus_side: "over" | "under";
  confidence_label: string;
  best_over_sportsbook?: string | null;
  best_over_odds?: number | null;
  best_over_deeplink_url?: string | null;
  best_under_sportsbook?: string | null;
  best_under_odds?: number | null;
  best_under_deeplink_url?: string | null;
}

export interface PlayerPropBoardPageResponse<TItem> {
  items: TItem[];
  page: number;
  page_size: number;
  total: number;
  source_total: number;
  has_more: boolean;
  scanned_at?: string | null;
  available_books: string[];
  available_markets: string[];
}

export interface BoardPromosResponse {
  meta: BoardSnapshotMeta;
  game_context?: Record<string, unknown> | null;
  limit: number;
  sides: MarketSide[];
}

export interface PlayerPropDiagnosticGame {
  event_id?: string | null;
  away_team: string;
  home_team: string;
  selection_reason: string;
  broadcasts: string[];
  odds_event_id?: string | null;
  commence_time?: string | null;
  matched: boolean;
}

export interface PlayerPropScanDiagnostics {
  scan_mode: string;
  scan_scope?: string | null;
  scoreboard_event_count: number;
  odds_event_count: number;
  curated_games: PlayerPropDiagnosticGame[];
  matched_event_count: number;
  unmatched_game_count: number;
  fallback_reason?: string | null;
  fallback_event_count?: number;
  events_fetched: number;
  events_skipped_pregame: number;
  events_with_results: number;
  candidate_sides_count: number;
  quality_gate_filtered_count: number;
  quality_gate_min_reference_bookmakers: number;
  sides_count: number;
  markets_requested: string[];
  prizepicks_status?: string | null;
  prizepicks_message?: string | null;
  prizepicks_board_items_count?: number;
  prizepicks_exact_line_matches_count?: number;
  prizepicks_unmatched_count?: number;
  prizepicks_filtered_count?: number;
}

export interface ScanResult {
  surface: BetSurface;
  sport: string;
  sides: MarketSide[];
  prizepicks_cards?: PrizePicksComparisonCard[] | null;
  events_fetched: number;
  events_with_both_books: number;
  api_requests_remaining: string | null;
  scanned_at?: string | null;
  diagnostics?: PlayerPropScanDiagnostics | null;
}

// ── Board snapshot models ────────────────────────────────────────────────────

export interface BoardSnapshotMeta {
  snapshot_id: string;
  snapshot_type: "scheduled" | "manual";
  scanned_at: string;
  surfaces_included: ScannerSurface[];
  sports_included: string[];
  next_scheduled_drop: string | null;
  events_scanned: number;
  total_sides: number;
}

export interface BoardResponse {
  meta: BoardSnapshotMeta;
  game_context?: Record<string, unknown> | null;
  straight_bets: ScanResult | null;
  player_props: ScanResult | null;
}

export interface ScopedRefreshResponse {
  surface: ScannerSurface;
  refreshed_at: string;
  data: ScanResult;
}

export interface BackendReadiness {
  status: "ready" | "not_ready" | "unreachable";
  timestamp: string | null;
  checks: {
    supabase_env: boolean;
    db_connectivity: boolean;
    scheduler_state: boolean;
    scheduler_freshness: boolean;
  };
  scheduler_freshness?: {
    enabled: boolean;
    fresh: boolean;
    source?: string;
    reason?: string;
    jobs?: Record<
      string,
      {
        fresh: boolean;
        freshness_reason: string;
        last_success_at: string | null;
        last_failure_at: string | null;
        last_run_id: string | null;
        last_error: string | null;
        stale_after_seconds: number;
        age_seconds: number | null;
      }
    >;
  };
  detail?: string;
}

export interface OddsApiActivitySummary {
  calls_last_hour?: number;
  errors_last_hour?: number;
  last_success_at?: string | null;
  last_error_at?: string | null;
}

export interface OddsApiActivityCall {
  activity_kind?: "raw_call";
  timestamp?: string | null;
  source?: string | null;
  endpoint?: string | null;
  sport?: string | null;
  cache_hit?: boolean;
  outbound_call_made?: boolean;
  status_code?: number | null;
  duration_ms?: number | null;
  api_requests_remaining?: string | number | null;
  credits_used_last?: number | null;
  error_type?: string | null;
  error_message?: string | null;
}

export interface OddsApiActivityScanDetail {
  activity_kind?: "scan_detail";
  timestamp?: string | null;
  source?: string | null;
  surface?: ScannerSurface | null;
  scan_scope?: "all" | "single_sport" | string | null;
  requested_sport?: string | null;
  sport?: string | null;
  actor_label?: string | null;
  run_id?: string | null;
  cache_hit?: boolean;
  outbound_call_made?: boolean;
  duration_ms?: number | null;
  events_fetched?: number | null;
  events_with_both_books?: number | null;
  sides_count?: number | null;
  api_requests_remaining?: string | number | null;
  credits_used_last?: number | null;
  status_code?: number | null;
  error_type?: string | null;
  error_message?: string | null;
}

export interface OddsApiActivityScanSession {
  activity_kind?: "scan_session";
  scan_session_id?: string | null;
  timestamp?: string | null;
  source?: string | null;
  surface?: ScannerSurface | null;
  scan_scope?: "all" | "single_sport" | string | null;
  requested_sport?: string | null;
  actor_label?: string | null;
  run_id?: string | null;
  detail_count?: number;
  live_call_count?: number;
  cache_hit_count?: number;
  other_count?: number;
  total_events_fetched?: number;
  total_events_with_both_books?: number;
  total_sides?: number;
  min_api_requests_remaining?: string | number | null;
  error_count?: number;
  has_errors?: boolean;
  details?: OddsApiActivityScanDetail[];
}

export interface OperatorStatusResponse {
  timestamp: string;
  runtime: {
    environment?: string;
    app_role?: string;
    scheduler_expected?: boolean;
    scheduler_running?: boolean;
    scheduler_runs_in_process?: boolean;
    scheduler_responsibility?: "in_process" | "external" | "disabled" | string;
    redis_configured?: boolean;
    redis_recommended_for_coordination?: boolean;
    cron_token_configured?: boolean;
    odds_api_key_configured?: boolean;
    supabase_url_configured?: boolean;
    supabase_service_role_configured?: boolean;
  };
  checks: {
    db_connectivity: boolean;
    scheduler_freshness: boolean;
  };
  db_error?: string | null;
  scheduler_freshness?: BackendReadiness["scheduler_freshness"];
  ops?: {
    last_scheduler_scan?: {
      run_id?: string;
      scan_window?: {
        label?: string;
        anchor_timezone?: string;
        anchor_time_mst?: string;
      } | null;
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
      total_sides?: number;
      props_events_scanned?: number;
      featured_games_count?: number;
      alerts_scheduled?: number;
      hard_errors?: number;
      captured_at?: string;
      board_drop?: boolean;
      result?: {
        selected_event_ids?: string[];
        props_scan_event_ids?: string[];
        selected_games?: Array<Record<string, unknown>>;
        props_sides?: number;
        props_events_scanned?: number;
        featured_games_count?: number;
        duration_ms?: number;
      } | null;
    } | null;
    last_jit_clv?: {
      source?: string;
      run_id?: string;
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
      updated?: number;
      captured_at?: string;
      status?: string;
    } | null;
    last_ops_trigger_scan?: {
      run_id?: string;
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
      total_sides?: number;
      alerts_scheduled?: number;
      error_count?: number;
      errors?: unknown[];
      captured_at?: string;
    } | null;
    last_manual_scan?: {
      captured_at?: string;
      sport?: string;
      events_fetched?: number;
      events_with_both_books?: number;
      total_sides?: number;
      api_requests_remaining?: string | number | null;
    } | null;
    last_auto_settle?: {
      source?: string;
      run_id?: string;
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
      settled?: number;
      captured_at?: string;
    } | null;
    last_auto_settle_summary?: {
      captured_at?: string;
      total_settled?: number;
      skipped_totals?: Record<string, number>;
      sports?: Array<Record<string, unknown>>;
    } | null;
    last_readiness_failure?: {
      captured_at?: string;
      checks?: Record<string, boolean>;
      db_error?: string | null;
    } | null;
    odds_api_activity?: {
      summary?: OddsApiActivitySummary;
      recent_scans?: OddsApiActivityScanSession[];
      recent_calls?: OddsApiActivityCall[];
      board_drop?: {
        last_run_at?: string | null;
        calls_count?: number;
        min_api_requests_remaining?: string | number | null;
        errors?: number;
      } | null;
    } | null;
  };
}

export interface ResearchOpportunityBreakdownItem {
  key: string;
  captured_count: number;
  pending_close_count: number;
  clv_ready_count: number;
  valid_close_count: number;
  invalid_close_count: number;
  aggregate_status:
    | "not_captured"
    | "pending_close"
    | "invalid_only"
    | "pending_and_invalid"
    | "sample_too_small"
    | "aggregate_available";
  suppressed_by_sample_size: boolean;
  beat_close_pct: number | null;
  avg_clv_percent: number | null;
}

export interface ResearchOpportunityRecentRow {
  opportunity_key: string;
  surface: ScannerSurface;
  first_seen_at: string;
  last_seen_at: string;
  commence_time: string;
  sport: string;
  event: string;
  team: string;
  sportsbook: string;
  market: string;
  event_id?: string | null;
  player_name?: string | null;
  source_market_key?: string | null;
  selection_side?: string | null;
  line_value?: number | null;
  first_source: string;
  seen_count: number;
  first_ev_percentage: number;
  first_book_odds: number;
  best_book_odds: number;
  latest_reference_odds: number | null;
  reference_odds_at_close: number | null;
  clv_ev_percent: number | null;
  beat_close: boolean | null;
  close_status: "pending" | "valid" | "invalid";
}

export interface AdminMarketRefreshSurfaceSummary {
  surface: ScannerSurface;
  sport: string;
  events_fetched: number;
  events_with_both_books: number;
  total_sides: number;
  scanned_at: string | null;
  api_requests_remaining: string | null;
}

export interface AdminMarketRefreshResponse {
  results: AdminMarketRefreshSurfaceSummary[];
}

/** Response from POST /api/ops/trigger/scan (proxied via admin manual scan button). */
export interface OpsTriggerScanResponse {
  ok: boolean;
  run_id: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  total_sides: number | null;
  alerts_scheduled: number;
  board_drop: boolean;
  errors: Array<Record<string, unknown>>;
  result?: {
    props_sides?: number;
    selected_event_ids?: string[];
    selected_games?: Array<Record<string, unknown>>;
    duration_ms?: number;
  } | null;
}

/** Response from POST /api/ops/trigger/auto-settle (proxied via admin). */
export interface OpsTriggerAutoSettleResponse {
  ok: boolean;
  run_id: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  settled: number;
}

export interface ResearchOpportunitySummary {
  captured_count: number;
  open_count: number;
  close_captured_count: number;
  pending_close_count: number;
  valid_close_count: number;
  invalid_close_count: number;
  valid_close_coverage_pct: number | null;
  invalid_close_rate_pct: number | null;
  selected_cohort_key: string | null;
  cohort_trend: ResearchOpportunityCohortTrendRow[];
  clv_ready_count: number;
  aggregate_status:
    | "not_captured"
    | "pending_close"
    | "invalid_only"
    | "pending_and_invalid"
    | "sample_too_small"
    | "aggregate_available";
  suppressed_by_sample_size: boolean;
  min_valid_close_threshold: number;
  beat_close_pct: number | null;
  avg_clv_percent: number | null;
  by_surface: ResearchOpportunityBreakdownItem[];
  by_source: ResearchOpportunityBreakdownItem[];
  by_sportsbook: ResearchOpportunityBreakdownItem[];
  by_edge_bucket: ResearchOpportunityBreakdownItem[];
  by_odds_bucket: ResearchOpportunityBreakdownItem[];
  status_buckets: ResearchOpportunityStatusBucket[];
  recent_opportunities: ResearchOpportunityRecentRow[];
}

export interface ResearchOpportunityStatusBucket {
  status: "pending" | "valid" | "invalid";
  count: number;
  sample: ResearchOpportunityRecentRow[];
}

export interface ResearchOpportunityCohortTrendRow {
  cohort_key: string;
  captured_count: number;
  valid_close_count: number;
  beat_close_pct: number | null;
  avg_clv_percent: number | null;
}

export interface ModelCalibrationBreakdownItem {
  key: string;
  captured_count: number;
  valid_close_count: number;
  paired_close_count: number;
  avg_brier_score: number | null;
  avg_log_loss: number | null;
  avg_clv_percent: number | null;
  beat_close_pct: number | null;
}

export interface ModelCalibrationCohortTrendRow {
  cohort_key: string;
  captured_count: number;
  valid_close_count: number;
  avg_brier_score: number | null;
  avg_log_loss: number | null;
  avg_clv_percent: number | null;
  beat_close_pct: number | null;
}

export interface ModelCalibrationRecentComparisonRow {
  opportunity_key: string;
  surface: ScannerSurface;
  first_seen_at: string;
  sport: string;
  event: string;
  sportsbook: string;
  market: string;
  player_name: string | null;
  selection_side: string | null;
  line_value: number | null;
  close_quality: string | null;
  close_true_prob: number | null;
  baseline_model_key: string | null;
  baseline_true_prob: number | null;
  baseline_ev_percentage: number | null;
  baseline_clv_ev_percent: number | null;
  candidate_model_key: string | null;
  candidate_true_prob: number | null;
  candidate_ev_percentage: number | null;
  candidate_clv_ev_percent: number | null;
}

export interface ModelCalibrationReleaseGate {
  candidate_model_key: string;
  baseline_model_key: string;
  candidate_valid_close_count: number;
  baseline_valid_close_count: number;
  candidate_avg_brier_score: number | null;
  baseline_avg_brier_score: number | null;
  candidate_avg_log_loss: number | null;
  baseline_avg_log_loss: number | null;
  candidate_avg_clv_percent: number | null;
  baseline_avg_clv_percent: number | null;
  candidate_beat_close_pct: number | null;
  baseline_beat_close_pct: number | null;
  eligible: boolean;
  passes: boolean;
  reasons: string[];
}

export interface ModelCalibrationSummary {
  captured_count: number;
  valid_close_count: number;
  paired_close_count: number;
  fallback_close_count: number;
  paired_close_pct: number | null;
  by_model: ModelCalibrationBreakdownItem[];
  by_market: ModelCalibrationBreakdownItem[];
  by_sportsbook: ModelCalibrationBreakdownItem[];
  by_interpolation_mode: ModelCalibrationBreakdownItem[];
  cohort_trend: ModelCalibrationCohortTrendRow[];
  recent_comparisons: ModelCalibrationRecentComparisonRow[];
  release_gate: ModelCalibrationReleaseGate;
}

export interface PickEmResearchBreakdownItem {
  key: string;
  captured_count: number;
  close_ready_count: number;
  settled_count: number;
  decisive_count: number;
  push_count: number;
  expected_hit_rate_pct: number | null;
  actual_hit_rate_pct: number | null;
  hit_rate_delta_pct_points: number | null;
  avg_close_drift_pct_points: number | null;
  avg_close_edge_pct: number | null;
  avg_brier_score: number | null;
  avg_log_loss: number | null;
}

export interface PickEmResearchRecentRow {
  observation_key: string;
  comparison_key: string;
  first_seen_at: string;
  last_seen_at: string;
  sport: string;
  event: string;
  commence_time: string;
  market: string;
  player_name: string;
  selection_side: string;
  line_value: number;
  displayed_probability: number;
  fair_odds_american: number | null;
  books_matched_count: number;
  confidence_label: string | null;
  ev_basis: string;
  selected_sportsbook: string | null;
  selected_market_odds: number | null;
  projected_edge_pct: number | null;
  close_true_prob: number | null;
  close_quality: string | null;
  close_edge_pct: number | null;
  close_drift_pct_points: number | null;
  actual_result: "win" | "loss" | "push" | null;
  settled_at: string | null;
  calibration_bucket: string;
  first_source: string;
  surfaced_count: number;
}

export interface PickEmResearchSummary {
  captured_count: number;
  close_ready_count: number;
  settled_count: number;
  decisive_count: number;
  push_count: number;
  pending_result_count: number;
  avg_display_probability_pct: number | null;
  expected_hit_rate_pct: number | null;
  actual_hit_rate_pct: number | null;
  hit_rate_delta_pct_points: number | null;
  avg_close_probability_pct: number | null;
  avg_close_drift_pct_points: number | null;
  avg_close_edge_pct: number | null;
  avg_brier_score: number | null;
  avg_log_loss: number | null;
  by_probability_bucket: PickEmResearchBreakdownItem[];
  by_market: PickEmResearchBreakdownItem[];
  by_books_matched: PickEmResearchBreakdownItem[];
  by_ev_basis: PickEmResearchBreakdownItem[];
  recent_observations: PickEmResearchRecentRow[];
}

export interface ParlayWarning {
  code: string;
  severity: "warning" | "blocking";
  title: string;
  detail: string;
  relatedLegIds: string[];
}

export type ParlaySlipMode = "standard" | "pickem_notes";

export interface ParlayPricingPreview {
  slipMode: ParlaySlipMode;
  legCount: number;
  sportsbook: string | null;
  /** Combined book odds; null when slipMode is pickem_notes (not a priced parlay). */
  combinedDecimalOdds: number | null;
  combinedAmericanOdds: number | null;
  stake: number | null;
  totalPayout: number | null;
  profit: number | null;
  estimatedFairDecimalOdds: number | null;
  estimatedFairAmericanOdds: number | null;
  estimatedTrueProbability: number | null;
  estimatedEvPercent: number | null;
  baseKellyFraction: number | null;
  rawKellyStake: number | null;
  stealthKellyStake: number | null;
  bankrollUsed: number | null;
  kellyMultiplierUsed: number | null;
  estimateAvailable: boolean;
  estimateUnavailableReason: string | null;
  hasBlockingCorrelation: boolean;
  warnings: ParlayWarning[];
}

export interface ParlaySlip {
  id: string;
  created_at: string;
  updated_at: string;
  sportsbook: string;
  stake: number | null;
  legs: ParlayCartLeg[];
  warnings: ParlayWarning[];
  pricingPreview: ParlayPricingPreview | null;
  logged_bet_id: string | null;
}

export interface ParlaySlipCreate {
  sportsbook: string;
  stake: number | null;
  legs: ParlayCartLeg[];
  warnings: ParlayWarning[];
  pricingPreview: ParlayPricingPreview | null;
}

export interface ParlaySlipUpdate {
  sportsbook?: string;
  stake?: number | null;
  legs?: ParlayCartLeg[];
  warnings?: ParlayWarning[];
  pricingPreview?: ParlayPricingPreview | null;
}

export interface ParlaySlipLogRequest {
  sport?: string;
  event?: string;
  promo_type: PromoType;
  odds_american: number;
  stake: number;
  boost_percent?: number;
  winnings_cap?: number;
  notes?: string;
  event_date?: string;
  opposing_odds?: number;
  payout_override?: number;
}

export interface ScannedBetData {
  surface?: BetSurface;
  sportsbook: string;
  sport: string;
  event: string;
  market: string;
  odds_american: number;
  opposing_odds?: number;
  promo_type: PromoType;
  boost_percent?: number;
  // CLV passthrough from scanner
  pinnacle_odds_at_entry?: number;
  commence_time?: string;
  clv_team?: string;
  clv_sport_key?: string;
  clv_event_id?: string;
  true_prob_at_entry?: number;  // de-vigged Pinnacle probability — enables accurate EV display
  source_event_id?: string;
  source_market_key?: string;
  source_selection_key?: string;
  participant_name?: string;
  participant_id?: string;
  selection_side?: string;
  line_value?: number;
  selection_meta?: Record<string, unknown>;
  kelly_suggestion?: number;    // deprecated: use raw_kelly_stake / stealth_kelly_stake
  raw_kelly_stake?: number;     // raw Kelly $ (base_kelly * multiplier * bankroll)
  stealth_kelly_stake?: number; // stealth-rounded stake for display and auto-fill
  // Backend duplicate/exposure awareness for scanner UX
  scanner_duplicate_state?: "new" | "logged_elsewhere" | "already_logged" | "better_now";
  best_logged_odds_american?: number | null;
  current_odds_american?: number | null;
  matched_pending_bet_id?: string | null;
}

export interface TutorialPracticeBet {
  id: string;
  created_at: string;
  event_date: string;
  sport: string;
  event: string;
  market: string;
  sportsbook: string;
  surface: BetSurface;
  promo_type: PromoType;
  odds_american: number;
  stake: number;
  win_payout: number;
  ev_total: number;
  ev_per_dollar: number;
}

export type TutorialSessionStep = "scanner_empty" | "scanner_ready" | "home_review";

export interface TutorialSession {
  surface: BetSurface;
  step: TutorialSessionStep;
  has_seeded_scan: boolean;
  practice_bet: TutorialPracticeBet | null;
  started_at: string;
  updated_at: string;
}

export interface ParlayCartLeg {
  id: string;
  surface: ScannerSurface;
  eventId?: string | null;
  marketKey: string;
  selectionKey: string;
  sportsbook: string;
  oddsAmerican: number;
  referenceOddsAmerican: number | null;
  referenceTrueProbability?: number | null;
  referenceSource: string | null;
  display: string;
  event: string;
  sport: string;
  commenceTime: string;
  correlationTags: string[];
  team?: string | null;
  participantName?: string | null;
  participantId?: string | null;
  selectionSide?: string | null;
  lineValue?: number | null;
  marketDisplay?: string | null;
  sourceEventId?: string | null;
  sourceMarketKey?: string | null;
  sourceSelectionKey?: string | null;
  selectionMeta?: Record<string, unknown> | null;
}

/** Optional per-leg CLV fields merged by the backend into `selection_meta.legs[]`. */
export interface LoggedParlayLegClv {
  latest_reference_odds?: number | null;
  latest_reference_updated_at?: string | null;
  pinnacle_odds_at_close?: number | null;
  reference_updated_at?: string | null;
  clv_ev_percent?: number | null;
  beat_close?: boolean | null;
}

export interface LoggedParlayLeg extends ParlayCartLeg, LoggedParlayLegClv {}

export interface LoggedParlaySelectionMeta {
  type: "parlay";
  slip_id?: string;
  sportsbook?: string;
  logged_at?: string;
  legs: LoggedParlayLeg[];
  warnings?: unknown[];
  pricingPreview?: unknown;
}

// Constants
export const SPORTSBOOKS = [
  "DraftKings",
  "FanDuel",
  "BetMGM",
  "Caesars",
  "ESPN Bet",
  "Fanatics",
  "Hard Rock",
  "bet365",
] as const;

export const SPORTS = [
  "NFL",
  "NBA",
  "MLB",
  "NHL",
  "NCAAF",
  "NCAAB",
  "UFC",
  "Soccer",
  "Tennis",
  "Other",
] as const;

export const MARKETS = [
  "ML",
  "Spread",
  "Total",
  "Parlay",
  "SGP",
  "Prop",
  "Futures",
] as const;

// Ordered by frequency of use (most common first) with logical grouping
export const PROMO_TYPES: { value: PromoType; label: string }[] = [
  { value: "bonus_bet", label: "Bonus Bet" },
  { value: "boost_30", label: "30% Boost" },
  { value: "boost_50", label: "50% Boost" },
  { value: "promo_qualifier", label: "Promo Qualifier" },
  { value: "boost_100", label: "100% Boost" },
  { value: "boost_custom", label: "Custom Boost" },
  { value: "no_sweat", label: "No-Sweat" },
  { value: "standard", label: "Standard" },
];

// Promo type display config - colors for tags and selection buttons
export const PROMO_TYPE_CONFIG: Record<PromoType, { 
  short: string; 
  bg: string; 
  text: string;
  selectedBg: string;
  selectedText: string;
  ring?: string;
}> = {
  bonus_bet: { 
    short: "BB", 
    bg: "bg-[#0EA5A4]/15", 
    text: "text-[#0EA5A4]",
    selectedBg: "bg-[#0EA5A4]/25",
    selectedText: "text-foreground"
  },
  boost_30: { 
    short: "30%", 
    bg: "bg-pending/20", 
    text: "text-pending",
    selectedBg: "bg-pending/30",
    selectedText: "text-foreground"
  },
  boost_50: { 
    short: "50%", 
    bg: "bg-pending/20", 
    text: "text-pending",
    selectedBg: "bg-pending/30",
    selectedText: "text-foreground"
  },
  promo_qualifier: { 
    short: "PQ", 
    bg: "bg-loss/15", 
    text: "text-loss",
    selectedBg: "bg-loss/20",
    selectedText: "text-foreground"
  },
  boost_100: { 
    short: "100%", 
    bg: "bg-pending/20", 
    text: "text-pending",
    selectedBg: "bg-pending/30",
    selectedText: "text-foreground"
  },
  boost_custom: { 
    short: "Boost", 
    bg: "bg-pending/20", 
    text: "text-pending",
    selectedBg: "bg-pending/30",
    selectedText: "text-foreground"
  },
  no_sweat: { 
    short: "NS", 
    bg: "bg-profit/15", 
    text: "text-profit",
    selectedBg: "bg-profit/25",
    selectedText: "text-foreground"
  },
  standard: { 
    short: "Std", 
    bg: "bg-muted", 
    text: "text-muted-foreground",
    selectedBg: "bg-foreground",
    selectedText: "text-background",
  },
};
