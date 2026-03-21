import type { MarketSide } from "@/lib/types";

import type { ScannerLens } from "./scanner-ui-model";

export type RankedScannerSide = MarketSide & {
  _retention?: number;
  _boostedEV?: number;
};

export function calculateLensRetention(side: MarketSide, kUser?: number, weight?: number): number {
  const theoretical = (side.book_decimal - 1) * side.true_prob;
  if (kUser !== undefined && weight !== undefined && weight > 0) {
    return (1 - weight) * theoretical + weight * kUser;
  }
  return theoretical;
}

export function calculateLensBoostedEV(side: MarketSide, boostPercent: number): number {
  const baseProfit = side.book_decimal - 1;
  const boostedProfit = baseProfit * (1 + boostPercent / 100);
  const boostedDecimal = 1 + boostedProfit;
  return (side.true_prob * boostedDecimal - 1) * 100;
}

export function rankScannerSidesByLens(params: {
  sides: MarketSide[];
  selectedBooks: string[];
  activeLens: ScannerLens;
  boostPercent: number;
  kUser?: number;
  kWeight?: number;
}): RankedScannerSide[] {
  const { sides, selectedBooks, activeLens, boostPercent, kUser, kWeight } = params;
  const scopedSides = sides.filter((side) => selectedBooks.includes(side.sportsbook));

  switch (activeLens) {
    case "standard":
      return scopedSides
        .filter((side) => side.ev_percentage > 0)
        .sort((a, b) => b.ev_percentage - a.ev_percentage);

    case "profit_boost":
      return scopedSides
        .map((side) => ({ ...side, _boostedEV: calculateLensBoostedEV(side, boostPercent) }))
        .filter((side) => (side._boostedEV ?? 0) > 0)
        .sort((a, b) => (b._boostedEV ?? 0) - (a._boostedEV ?? 0));

    case "bonus_bet":
      return scopedSides
        .map((side) => ({ ...side, _retention: calculateLensRetention(side, kUser, kWeight) }))
        .sort((a, b) => (b._retention ?? 0) - (a._retention ?? 0));

    case "qualifier":
      return scopedSides
        .filter((side) => side.book_odds >= -250 && side.book_odds <= 150)
        .sort((a, b) => b.ev_percentage - a.ev_percentage);
  }
}
