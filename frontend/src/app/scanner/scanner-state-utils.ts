import type { MarketSide, ParlayCartLeg, PromoType, ScannedBetData } from "@/lib/types";
import { calculateStealthStake, decimalToAmerican } from "@/lib/utils";

import type { PickEmBoardCard } from "./pickem-board";
import type { ScannerLens } from "./scanner-ui-model";

function formatPickEmLineValue(value: number): string {
  if (Number.isInteger(value)) {
    return `${value}`;
  }
  return `${Number.parseFloat(value.toFixed(2))}`;
}

function buildPlayerPropSelectionKeyParts(
  eventId: string | null | undefined,
  marketKey: string,
  playerName: string,
  side: string,
  lineValue: number | null | undefined,
): string {
  const lineToken = lineValue == null ? "" : `:${lineValue}`;
  return [
    String(eventId ?? "").trim().toLowerCase(),
    marketKey.trim().toLowerCase(),
    playerName.trim().toLowerCase(),
    side.trim().toLowerCase(),
  ].join("|") + lineToken;
}

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

function fairAmericanFromTrueProbability(trueProb: number | null | undefined): number | null {
  if (trueProb == null || !Number.isFinite(trueProb) || trueProb <= 0 || trueProb >= 1) {
    return null;
  }
  return decimalToAmerican(1 / trueProb);
}

function formatScannerLineValue(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "";
  if (Number.isInteger(value)) return `${value}`;
  return `${Number.parseFloat(value.toFixed(2))}`;
}

function formatStraightBetDisplay(side: Extract<MarketSide, { surface: "straight_bets" }>): string {
  const marketKey = String(side.market_key ?? "h2h").toLowerCase();
  if (marketKey === "spreads") {
    const line = side.line_value;
    const lineLabel =
      line == null || !Number.isFinite(line)
        ? ""
        : line > 0
          ? ` +${formatScannerLineValue(line)}`
          : ` ${formatScannerLineValue(line)}`;
    return `${side.team}${lineLabel}`;
  }
  if (marketKey === "totals") {
    const sideLabel = String(side.selection_side ?? side.team ?? "").trim();
    const lineLabel = formatScannerLineValue(side.line_value);
    return `${sideLabel.charAt(0).toUpperCase()}${sideLabel.slice(1)}${lineLabel ? ` ${lineLabel}` : ""}`.trim();
  }
  return `${side.team} ML`;
}

function formatStraightBetMarketDisplay(side: Extract<MarketSide, { surface: "straight_bets" }>): string {
  const marketKey = String(side.market_key ?? "h2h").toLowerCase();
  if (marketKey === "spreads") return "Spread";
  if (marketKey === "totals") return "Total";
  return "Moneyline";
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
        reference_bookmakers: side.reference_bookmakers ?? [],
      },
      raw_kelly_stake: rawKellyStake,
      stealth_kelly_stake: stealthKellyStake,
      scanner_duplicate_state: side.scanner_duplicate_state,
      best_logged_odds_american: side.best_logged_odds_american,
      current_odds_american: side.current_odds_american ?? side.book_odds,
      matched_pending_bet_id: side.matched_pending_bet_id,
    };
  }

  const straightDisplay = formatStraightBetDisplay(side);
  const straightMarket = formatStraightBetMarketDisplay(side);
  const straightSelectionSide = side.market_key === "totals" ? (side.selection_side ?? side.team) : side.team;

  return {
    surface: side.surface,
    sportsbook: side.sportsbook,
    sport: sportDisplay,
    event: straightDisplay,
    market: straightMarket,
    odds_american: side.book_odds,
    promo_type: promoType,
    boost_percent: boostPct,
    pinnacle_odds_at_entry: side.pinnacle_odds,
    commence_time: side.commence_time,
    clv_team: side.market_key === "totals" ? straightSelectionSide : side.team,
    clv_sport_key: side.sport,
    clv_event_id: side.event_id ?? undefined,
    source_event_id: side.event_id ?? undefined,
    source_market_key: side.market_key ?? "h2h",
    source_selection_key: side.selection_key ?? undefined,
    selection_side: straightSelectionSide,
    line_value: side.line_value ?? undefined,
    selection_meta: {
      marketKey: side.market_key ?? "h2h",
      display: straightDisplay,
      sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
      sportsbookDeeplinkLevel: side.sportsbook_deeplink_level,
    },
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
      referenceOddsAmerican: side.reference_odds,
      referenceTrueProbability: side.true_prob,
      referenceSource: side.reference_source,
      display: side.display_name,
      event: side.event,
      sport: side.sport,
      commenceTime: side.commence_time,
      correlationTags: [side.event_id ?? side.event, side.player_name, side.market_key],
      team: side.team ?? undefined,
      participantName: side.player_name,
      participantId: side.participant_id ?? undefined,
      selectionSide: side.selection_side,
      lineValue: side.line_value ?? undefined,
      marketDisplay: side.market,
      sourceEventId: side.event_id ?? undefined,
      sourceMarketKey: side.market_key,
      sourceSelectionKey: side.selection_key,
      selectionMeta: {
        opponent: side.opponent,
        referenceBookmakers: side.reference_bookmakers ?? [],
        referenceBookmakerCount: side.reference_bookmaker_count,
        confidenceLabel: side.confidence_label,
        sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
        sportsbookDeeplinkLevel: side.sportsbook_deeplink_level,
      },
    };
  }

  const selectionKey = side.selection_key ?? `${side.event_id ?? side.commence_time}:${side.team}`;
  const deviggedFairOdds = fairAmericanFromTrueProbability(side.true_prob);
  const straightDisplay = formatStraightBetDisplay(side);
  const straightMarketDisplay = formatStraightBetMarketDisplay(side);
  const straightSelectionSide = side.market_key === "totals" ? (side.selection_side ?? side.team) : side.team;
  return {
    id: `${side.surface}:${selectionKey}:${side.sportsbook}`,
    surface: side.surface,
    eventId: side.event_id ?? undefined,
    marketKey: side.market_key ?? "h2h",
    selectionKey,
    sportsbook: side.sportsbook,
    oddsAmerican: side.book_odds,
    referenceOddsAmerican: deviggedFairOdds ?? side.pinnacle_odds,
    referenceTrueProbability: side.true_prob,
    referenceSource: "pinnacle",
    display: straightDisplay,
    event: side.event,
    sport: side.sport,
    commenceTime: side.commence_time,
    correlationTags: [side.event_id ?? side.event, side.selection_key ?? `${side.market_key ?? "h2h"}:${straightDisplay}`],
    team: side.team,
    selectionSide: straightSelectionSide,
    lineValue: side.line_value ?? undefined,
    marketDisplay: straightMarketDisplay,
    sourceEventId: side.event_id ?? undefined,
    sourceMarketKey: side.market_key ?? "h2h",
    sourceSelectionKey: selectionKey,
    selectionMeta: {
      rawPinnacleOdds: side.pinnacle_odds,
      sportsbookDeeplinkUrl: side.sportsbook_deeplink_url,
      sportsbookDeeplinkLevel: side.sportsbook_deeplink_level,
    },
  };
}

/** Builds a parlay cart leg from a Pick'em consensus card (best book for the consensus side). */
export function buildParlayCartLegFromPickEmCard(card: PickEmBoardCard): ParlayCartLeg | null {
  const side = card.consensus_side;
  const sportsbook = side === "over" ? card.best_over_sportsbook : card.best_under_sportsbook;
  const bookOdds = side === "over" ? card.best_over_odds : card.best_under_odds;
  const deeplink = side === "over" ? card.best_over_deeplink_url : card.best_under_deeplink_url;
  const trueProb = side === "over" ? card.consensus_over_prob : card.consensus_under_prob;

  if (!sportsbook?.trim() || bookOdds == null || !Number.isFinite(bookOdds)) {
    return null;
  }

  const selectionKey = buildPlayerPropSelectionKeyParts(
    card.event_id,
    card.market_key,
    card.player_name,
    side,
    card.line_value,
  );

  const sideLabel = side === "over" ? "Over" : "Under";
  const display = `${card.player_name} ${sideLabel} ${formatPickEmLineValue(card.line_value)}`;
  const referenceOddsAmerican = fairAmericanFromTrueProbability(trueProb);

  return {
    id: `player_props:${selectionKey}:${sportsbook}`,
    surface: "player_props",
    eventId: card.event_id ?? undefined,
    marketKey: card.market_key,
    selectionKey,
    sportsbook,
    oddsAmerican: bookOdds,
    referenceOddsAmerican,
    referenceTrueProbability: trueProb,
    referenceSource: "pickem_consensus",
    display,
    event: card.event,
    sport: card.sport,
    commenceTime: card.commence_time,
    correlationTags: [card.event_id ?? card.event, card.player_name, card.market_key],
    team: card.team ?? undefined,
    participantName: card.player_name,
    participantId: card.participant_id ?? undefined,
    selectionSide: side,
    lineValue: card.line_value,
    marketDisplay: card.market,
    sourceEventId: card.event_id ?? undefined,
    sourceMarketKey: card.market_key,
    sourceSelectionKey: selectionKey,
    selectionMeta: {
      opponent: card.opponent,
      referenceBookmakers: card.exact_line_bookmakers,
      referenceBookmakerCount: card.exact_line_bookmaker_count,
      confidenceLabel: card.confidence_label,
      sportsbookDeeplinkUrl: deeplink,
      pickEmComparisonKey: card.comparison_key,
    },
  };
}
