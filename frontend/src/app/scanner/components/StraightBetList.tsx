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
  isLoadingMore?: boolean;
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
  isLoadingMore = false,
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
          key={`${side.sportsbook}-${side.team}-${side.event}-${idx}`}
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
        <Button type="button" variant="secondary" className="w-full" onClick={onLoadMore} disabled={isLoadingMore}>
          {isLoadingMore ? "Loading more..." : "Load more"}
        </Button>
      )}
    </>
  );
}
