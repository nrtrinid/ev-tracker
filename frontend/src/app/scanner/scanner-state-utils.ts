import type { MarketSide, ParlayCartLeg, PromoType, ScannedBetData } from "@/lib/types";
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

  if (side.surface === "player_props") {
    return {
      surface: side.surface,
      sportsbook: side.sportsbook,
      sport: sportDisplay,
      event: side.display_name,
      market: "Prop",
      odds_american: side.book_odds,
      promo_type: promoType,
      boost_percent: boostPct,
      pinnacle_odds_at_entry: side.reference_odds,
      commence_time: side.commence_time,
      clv_team: side.team ?? side.player_name,
      clv_sport_key: side.sport,
      clv_event_id: side.event_id ?? undefined,
      true_prob_at_entry: side.true_prob,
      source_event_id: side.event_id ?? undefined,
      source_market_key: side.market_key,
      source_selection_key: side.selection_key,
      participant_name: side.player_name,
      participant_id: side.participant_id ?? undefined,
      selection_side: side.selection_side,
      line_value: side.line_value ?? undefined,
      selection_meta: {
        market: side.market,
        opponent: side.opponent,
        display_name: side.display_name,
        reference_source: side.reference_source,
        reference_bookmakers: side.reference_bookmakers,
      },
      raw_kelly_stake: rawKellyStake,
      stealth_kelly_stake: stealthKellyStake,
      scanner_duplicate_state: side.scanner_duplicate_state,
      best_logged_odds_american: side.best_logged_odds_american,
      current_odds_american: side.current_odds_american ?? side.book_odds,
      matched_pending_bet_id: side.matched_pending_bet_id,
    };
  }

  return {
    surface: side.surface,
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
    source_event_id: side.event_id ?? undefined,
    source_market_key: side.market_key ?? "h2h",
    source_selection_key: side.selection_key ?? undefined,
    selection_side: side.team,
    true_prob_at_entry: side.true_prob,
    raw_kelly_stake: rawKellyStake,
    stealth_kelly_stake: stealthKellyStake,
    scanner_duplicate_state: side.scanner_duplicate_state,
    best_logged_odds_american: side.best_logged_odds_american,
    current_odds_american: side.current_odds_american ?? side.book_odds,
    matched_pending_bet_id: side.matched_pending_bet_id,
  };
}

export function buildParlayCartLeg(side: MarketSide): ParlayCartLeg {
  if (side.surface === "player_props") {
    return {
      id: `${side.surface}:${side.selection_key}:${side.sportsbook}`,
      surface: side.surface,
      eventId: side.event_id ?? undefined,
      marketKey: side.market_key,
      selectionKey: side.selection_key,
      sportsbook: side.sportsbook,
      oddsAmerican: side.book_odds,
      display: side.display_name,
      event: side.event,
      sport: side.sport,
      commenceTime: side.commence_time,
      correlationTags: [side.event_id ?? side.event, side.player_name, side.market_key],
    };
  }

  const selectionKey = side.selection_key ?? `${side.event_id ?? side.commence_time}:${side.team}`;
  return {
    id: `${side.surface}:${selectionKey}:${side.sportsbook}`,
    surface: side.surface,
    eventId: side.event_id ?? undefined,
    marketKey: side.market_key ?? "h2h",
    selectionKey,
    sportsbook: side.sportsbook,
    oddsAmerican: side.book_odds,
    display: `${side.team} ML`,
    event: side.event,
    sport: side.sport,
    commenceTime: side.commence_time,
    correlationTags: [side.event_id ?? side.event, side.team],
  };
}
