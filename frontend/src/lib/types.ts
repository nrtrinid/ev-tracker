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

export interface Bet {
  id: string;
  created_at: string;
  event_date: string;
  settled_at: string | null;
  sport: string;
  event: string;
  market: string;
  surface: ScannerSurface;
  sportsbook: string;
  promo_type: PromoType;
  odds_american: number;
  odds_decimal: number;
  stake: number;
  boost_percent: number | null;
  winnings_cap: number | null;
  notes: string | null;
  opposing_odds: number | null;
  result: BetResult;
  win_payout: number;
  ev_per_dollar: number;
  ev_total: number;
  real_profit: number | null;
  // CLV tracking
  pinnacle_odds_at_entry: number | null;
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
  selection_meta: Record<string, unknown> | null;
}

export interface BetCreate {
  sport: string;
  event: string;
  market: string;
  surface?: ScannerSurface;
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
  selection_meta?: Record<string, unknown>;
}

export interface BetUpdate {
  sport?: string;
  event?: string;
  market?: string;
  surface?: ScannerSurface;
  sportsbook?: string;
  promo_type?: PromoType;
  odds_american?: number;
  stake?: number;
  boost_percent?: number;
  winnings_cap?: number;
  notes?: string;
  result?: BetResult;
  payout_override?: number;
  opposing_odds?: number;
  event_date?: string;
}

export interface Settings {
  k_factor: number;
  default_stake: number | null;
  preferred_sportsbooks: string[];
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
export interface StraightBetMarketSide {
  surface: "straight_bets";
  event_id?: string | null;
  market_key?: string;
  selection_key?: string | null;
  sportsbook: string;
  sportsbook_deeplink_url?: string | null;
  sport: string;
  event: string;
  commence_time: string;
  team: string;
  pinnacle_odds: number;
  book_odds: number;
  true_prob: number;
  base_kelly_fraction: number;
  book_decimal: number;
  ev_percentage: number;
  scanner_duplicate_state?: "new" | "already_logged" | "better_now";
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
  sport: string;
  event: string;
  commence_time: string;
  market: string;
  player_name: string;
  participant_id?: string | null;
  team?: string | null;
  opponent?: string | null;
  selection_side: string;
  line_value?: number | null;
  display_name: string;
  pinnacle_odds: number;
  book_odds: number;
  true_prob: number;
  base_kelly_fraction: number;
  book_decimal: number;
  ev_percentage: number;
  scanner_duplicate_state?: "new" | "already_logged" | "better_now";
  best_logged_odds_american?: number | null;
  current_odds_american?: number | null;
  matched_pending_bet_id?: string | null;
}

export type MarketSide = StraightBetMarketSide | PlayerPropMarketSide;

export interface ScanResult {
  surface: ScannerSurface;
  sport: string;
  sides: MarketSide[];
  events_fetched: number;
  events_with_both_books: number;
  api_requests_remaining: string | null;
  scanned_at?: string | null;
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

export interface OperatorStatusResponse {
  timestamp: string;
  runtime: {
    environment?: string;
    scheduler_expected?: boolean;
    scheduler_running?: boolean;
    redis_configured?: boolean;
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
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
      total_sides?: number;
      alerts_scheduled?: number;
      hard_errors?: number;
      captured_at?: string;
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
      summary?: {
        calls_last_hour?: number;
        errors_last_hour?: number;
        last_success_at?: string | null;
        last_error_at?: string | null;
      };
      recent_calls?: Array<{
        timestamp?: string | null;
        source?: string | null;
        endpoint?: string | null;
        sport?: string | null;
        cache_hit?: boolean;
        outbound_call_made?: boolean;
        status_code?: number | null;
        duration_ms?: number | null;
        api_requests_remaining?: string | number | null;
        error_type?: string | null;
        error_message?: string | null;
      }>;
    } | null;
  };
}

export interface ScannedBetData {
  surface?: ScannerSurface;
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
  scanner_duplicate_state?: "new" | "already_logged" | "better_now";
  best_logged_odds_american?: number | null;
  current_odds_american?: number | null;
  matched_pending_bet_id?: string | null;
}

export interface ParlayCartLeg {
  id: string;
  surface: ScannerSurface;
  eventId?: string | null;
  marketKey: string;
  selectionKey: string;
  sportsbook: string;
  oddsAmerican: number;
  display: string;
  event: string;
  sport: string;
  commenceTime: string;
  correlationTags: string[];
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
    selectedText: "text-[#0B5E5D]"
  },
  boost_30: { 
    short: "30%", 
    bg: "bg-[#C4A35A]/20", 
    text: "text-[#8B7355]",
    selectedBg: "bg-[#C4A35A]/30",
    selectedText: "text-[#5C4D2E]"
  },
  boost_50: { 
    short: "50%", 
    bg: "bg-[#C4A35A]/20", 
    text: "text-[#8B7355]",
    selectedBg: "bg-[#C4A35A]/30",
    selectedText: "text-[#5C4D2E]"
  },
  promo_qualifier: { 
    short: "PQ", 
    bg: "bg-[#B85C38]/15", 
    text: "text-[#B85C38]",
    selectedBg: "bg-[#B85C38]/20",
    selectedText: "text-[#8B3D20]"
  },
  boost_100: { 
    short: "100%", 
    bg: "bg-[#C4A35A]/20", 
    text: "text-[#8B7355]",
    selectedBg: "bg-[#C4A35A]/30",
    selectedText: "text-[#5C4D2E]"
  },
  boost_custom: { 
    short: "Boost", 
    bg: "bg-[#C4A35A]/20", 
    text: "text-[#8B7355]",
    selectedBg: "bg-[#C4A35A]/30",
    selectedText: "text-[#5C4D2E]"
  },
  no_sweat: { 
    short: "NS", 
    bg: "bg-[#4A7C59]/15", 
    text: "text-[#4A7C59]",
    selectedBg: "bg-[#4A7C59]/25",
    selectedText: "text-[#2C5235]"
  },
  standard: { 
    short: "Std", 
    bg: "bg-[#DDD5C7]", 
    text: "text-[#6B5E4F]",
    selectedBg: "bg-foreground",
    selectedText: "text-background",
  },
};
