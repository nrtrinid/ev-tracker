import type { PlayerPropMarketSide } from "@/lib/types";
import { americanToDecimal } from "@/lib/utils";

export interface PickEmBoardCard {
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

function canonicalize(value: string | null | undefined): string {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[middle - 1] + sorted[middle]) / 2;
  }
  return sorted[middle];
}

function confidenceLabel(bookCount: number): string {
  if (bookCount >= 4) return "elite";
  if (bookCount >= 3) return "high";
  if (bookCount >= 2) return "solid";
  return "thin";
}

function oddsQuality(americanOdds: number | null | undefined): number {
  if (americanOdds == null) return Number.NEGATIVE_INFINITY;
  return americanToDecimal(americanOdds);
}

export function buildPickEmBoardCards(
  sides: Array<PlayerPropMarketSide & { _retention?: number; _boostedEV?: number }>
): PickEmBoardCard[] {
  const grouped = new Map<
    string,
    {
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
      byBook: Record<string, { over?: PlayerPropMarketSide; under?: PlayerPropMarketSide }>;
    }
  >();

  for (const side of sides) {
    if (side.line_value == null) continue;
    const normalizedSide = side.selection_side.trim().toLowerCase();
    if (normalizedSide !== "over" && normalizedSide !== "under") continue;

    const key = [
      side.event_id ?? side.event,
      side.market_key,
      canonicalize(side.player_name),
      String(side.line_value),
    ].join("|");

    const existing = grouped.get(key) ?? {
      event_id: side.event_id ?? null,
      sport: side.sport,
      event: side.event,
      event_short: side.event_short ?? null,
      commence_time: side.commence_time,
      player_name: side.player_name,
      participant_id: side.participant_id ?? null,
      team: side.team ?? null,
      team_short: side.team_short ?? null,
      opponent: side.opponent ?? null,
      opponent_short: side.opponent_short ?? null,
      market_key: side.market_key,
      market: side.market,
      line_value: side.line_value,
      byBook: {},
    };

    existing.byBook[side.sportsbook] ??= {};
    existing.byBook[side.sportsbook][normalizedSide] = side;
    grouped.set(key, existing);
  }

  const cards: PickEmBoardCard[] = [];

  grouped.forEach((entry, comparisonKey) => {
    const validBookPairs = Object.keys(entry.byBook).flatMap((sportsbook) => {
      const pair = entry.byBook[sportsbook];
      return pair?.over && pair?.under ? ([[sportsbook, pair]] as const) : [];
    });
    if (validBookPairs.length === 0) return;

    const overSides = validBookPairs.map(([, pair]) => pair.over!).filter(Boolean);
    const underSides = validBookPairs.map(([, pair]) => pair.under!).filter(Boolean);
    const overProbs = overSides.map((side) => side.true_prob).filter((value) => Number.isFinite(value));
    const underProbs = underSides.map((side) => side.true_prob).filter((value) => Number.isFinite(value));
    if (overProbs.length === 0 || underProbs.length === 0) return;

    const bestOver = overSides.reduce<PlayerPropMarketSide | null>((best, current) => {
      if (!best) return current;
      return oddsQuality(current.book_odds) > oddsQuality(best.book_odds) ? current : best;
    }, null);
    const bestUnder = underSides.reduce<PlayerPropMarketSide | null>((best, current) => {
      if (!best) return current;
      return oddsQuality(current.book_odds) > oddsQuality(best.book_odds) ? current : best;
    }, null);

    const consensusOver = Number(median(overProbs).toFixed(4));
    const consensusUnder = Number(median(underProbs).toFixed(4));
    const supportBooks = validBookPairs.map(([sportsbook]) => sportsbook);

    cards.push({
      comparison_key: comparisonKey,
      event_id: entry.event_id,
      sport: entry.sport,
      event: entry.event,
      event_short: entry.event_short ?? null,
      commence_time: entry.commence_time,
      player_name: entry.player_name,
      participant_id: entry.participant_id,
      team: entry.team,
      team_short: entry.team_short ?? null,
      opponent: entry.opponent,
      opponent_short: entry.opponent_short ?? null,
      market_key: entry.market_key,
      market: entry.market,
      line_value: entry.line_value,
      exact_line_bookmakers: supportBooks,
      exact_line_bookmaker_count: supportBooks.length,
      consensus_over_prob: consensusOver,
      consensus_under_prob: consensusUnder,
      consensus_side: consensusOver >= consensusUnder ? "over" : "under",
      confidence_label: confidenceLabel(supportBooks.length),
      best_over_sportsbook: bestOver?.sportsbook ?? null,
      best_over_odds: bestOver?.book_odds ?? null,
      best_over_deeplink_url: bestOver?.sportsbook_deeplink_url ?? null,
      best_under_sportsbook: bestUnder?.sportsbook ?? null,
      best_under_odds: bestUnder?.book_odds ?? null,
      best_under_deeplink_url: bestUnder?.sportsbook_deeplink_url ?? null,
    });
  });

  return cards;
}
