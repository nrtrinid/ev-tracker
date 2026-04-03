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
      <div className="space-y-2">
        {results.map((side, idx) => (
          <div
            key={`${side.sportsbook}-${side.team}-${side.event}-${idx}`}
            className="animate-slide-up"
            style={{ animationDelay: `${idx * 40}ms` }}
          >
            <StraightBetCard
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
          </div>
        ))}
      </div>

      {canLoadMore && (
        <Button
          type="button"
          variant="secondary"
          className="w-full active:scale-[0.98] transition-transform"
          onClick={onLoadMore}
          disabled={isLoadingMore}
        >
          {isLoadingMore ? "Loading more..." : "Load more"}
        </Button>
      )}
    </>
  );
}
