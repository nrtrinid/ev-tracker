import type { MarketSide, PromoType, ScannedBetData } from "@/lib/types";
import { calculateStealthStake } from "@/lib/utils";

import type { ScannerLens } from "./scanner-ui-model";

export function toggleScannerBookSelection(current: string[], book: string): string[] {
  if (current.includes(book)) {
    if (current.length === 1) {
      return current;
    }
    return current.filter((value) => value !== book);
  }
  return [...current, book];
}

export function parseScannerCustomBoostInput(input: string): number | null {
  const parsed = parseInt(input, 10);
  if (Number.isNaN(parsed) || parsed <= 0 || parsed > 200) {
    return null;
  }
  return parsed;
}

export function buildScannerLogBetInitialValues(params: {
  side: MarketSide;
  activeLens: ScannerLens;
  boostPercent: number;
  sportDisplayMap: Record<string, string>;
  kellyMultiplier: number;
  bankroll: number;
}): ScannedBetData {
  const { side, activeLens, boostPercent, sportDisplayMap, kellyMultiplier, bankroll } = params;

  const sportDisplay = sportDisplayMap[side.sport] || side.sport;

  let promoType: PromoType = "standard";
  let boostPct: number | undefined;

  if (activeLens === "bonus_bet") {
    promoType = "bonus_bet";
  } else if (activeLens === "profit_boost") {
    promoType = "boost_custom";
    boostPct = boostPercent;
  }

  const rawKellyStake = Math.max(0, side.base_kelly_fraction * kellyMultiplier * bankroll);
  const stealthKellyStake = calculateStealthStake(rawKellyStake);

  return {
    sportsbook: side.sportsbook,
    sport: sportDisplay,
    event: `${side.team} ML`,
    market: "ML",
    odds_american: side.book_odds,
    promo_type: promoType,
    boost_percent: boostPct,
    pinnacle_odds_at_entry: side.pinnacle_odds,
    commence_time: side.commence_time,
    clv_team: side.team,
    clv_sport_key: side.sport,
    clv_event_id: side.event_id ?? undefined,
    true_prob_at_entry: side.true_prob,
    raw_kelly_stake: rawKellyStake,
    stealth_kelly_stake: stealthKellyStake,
    scanner_duplicate_state: side.scanner_duplicate_state,
    best_logged_odds_american: side.best_logged_odds_american,
    current_odds_american: side.current_odds_american ?? side.book_odds,
    matched_pending_bet_id: side.matched_pending_bet_id,
  };
}
