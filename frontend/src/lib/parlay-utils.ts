import type { ParlayCartLeg } from "@/lib/types";
import { americanToDecimal, decimalToAmerican } from "@/lib/utils";

export interface ParlayPreview {
  legCount: number;
  combinedDecimalOdds: number;
  combinedAmericanOdds: number;
  stake: number;
  totalPayout: number;
  profit: number;
}

export function buildParlayPreview(cart: ParlayCartLeg[], stake: number): ParlayPreview | null {
  if (cart.length === 0 || !Number.isFinite(stake) || stake <= 0) {
    return null;
  }

  const combinedDecimalOdds = cart.reduce(
    (running, leg) => running * americanToDecimal(leg.oddsAmerican),
    1
  );
  const totalPayout = stake * combinedDecimalOdds;

  return {
    legCount: cart.length,
    combinedDecimalOdds,
    combinedAmericanOdds: decimalToAmerican(combinedDecimalOdds),
    stake,
    totalPayout,
    profit: totalPayout - stake,
  };
}
