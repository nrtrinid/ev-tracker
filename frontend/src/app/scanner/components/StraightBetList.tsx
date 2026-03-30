import { Button } from "@/components/ui/button";
import type { MarketSide } from "@/lib/types";

import { StraightBetCard } from "./StraightBetCard";

interface StraightBetListProps {
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  tutorialMode?: boolean;
  results: Array<MarketSide & { _retention?: number; _boostedEV?: number }>;
  kellyMultiplier: number;
  bankroll: number;
  boostPercent: number;
  canLoadMore: boolean;
  onLoadMore: () => void;
  onLogBet: (side: MarketSide) => void;
  onAddToCart: (side: MarketSide) => void;
  onStartPlaceFlow: (side: MarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function StraightBetList({
  activeLens,
  tutorialMode = false,
  results,
  kellyMultiplier,
  bankroll,
  boostPercent,
  canLoadMore,
  onLoadMore,
  onLogBet,
  onAddToCart,
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: StraightBetListProps) {
  return (
    <>
      {results.map((side, idx) => (
        <StraightBetCard
          key={`${side.surface}-${side.sportsbook}-${side.selection_key ?? side.team}-${side.market_key ?? ""}-${side.commence_time}-${idx}`}
          side={side}
          activeLens={activeLens}
          tutorialMode={tutorialMode}
          kellyMultiplier={kellyMultiplier}
          bankroll={bankroll}
          boostPercent={boostPercent}
          onLogBet={onLogBet}
          onAddToCart={onAddToCart}
          onStartPlaceFlow={onStartPlaceFlow}
          bookColors={bookColors}
          sportDisplayMap={sportDisplayMap}
        />
      ))}

      {canLoadMore && (
        <Button type="button" variant="secondary" className="w-full" onClick={onLoadMore}>
          Load more
        </Button>
      )}
    </>
  );
}
