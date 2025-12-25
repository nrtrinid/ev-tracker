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

export interface Bet {
  id: string;
  created_at: string;
  event_date: string;
  settled_at: string | null;
  sport: string;
  event: string;
  market: string;
  sportsbook: string;
  promo_type: PromoType;
  odds_american: number;
  odds_decimal: number;
  stake: number;
  boost_percent: number | null;
  winnings_cap: number | null;
  notes: string | null;
  result: BetResult;
  win_payout: number;
  ev_per_dollar: number;
  ev_total: number;
  real_profit: number | null;
}

export interface BetCreate {
  sport: string;
  event: string;
  market: string;
  sportsbook: string;
  promo_type: PromoType;
  odds_american: number;
  stake: number;
  boost_percent?: number;
  winnings_cap?: number;
  notes?: string;
  payout_override?: number;
  event_date?: string;
}

export interface BetUpdate {
  sport?: string;
  event?: string;
  market?: string;
  sportsbook?: string;
  promo_type?: PromoType;
  odds_american?: number;
  stake?: number;
  boost_percent?: number;
  winnings_cap?: number;
  notes?: string;
  result?: BetResult;
  payout_override?: number;
  event_date?: string;
}

export interface Settings {
  k_factor: number;
  default_stake: number | null;
  preferred_sportsbooks: string[];
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
  "Golf",
  "Other",
] as const;

export const MARKETS = [
  "ML",
  "Spread",
  "Total",
  "SGP",
  "Prop",
  "Futures",
] as const;

export const PROMO_TYPES: { value: PromoType; label: string }[] = [
  { value: "standard", label: "Standard" },
  { value: "bonus_bet", label: "Bonus Bet" },
  { value: "no_sweat", label: "No-Sweat" },
  { value: "promo_qualifier", label: "Promo Qualifier" },
  { value: "boost_30", label: "30% Boost" },
  { value: "boost_50", label: "50% Boost" },
  { value: "boost_100", label: "100% Boost" },
  { value: "boost_custom", label: "Custom Boost" },
];
