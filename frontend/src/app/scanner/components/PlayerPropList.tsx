import { Button } from "@/components/ui/button";
import type { PlayerPropMarketSide } from "@/lib/types";

import { PlayerPropCard } from "./PlayerPropCard";

interface PlayerPropListProps {
  results: Array<PlayerPropMarketSide & { _retention?: number; _boostedEV?: number; _qualifierHold?: number }>;
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  boostPercent: number;
  kellyMultiplier: number;
  bankroll: number;
  canLoadMore: boolean;
  isLoadingMore?: boolean;
  onLoadMore: () => void;
  onLogBet: (side: PlayerPropMarketSide) => void;
  onAddToCart: (side: PlayerPropMarketSide) => void;
  onStartPlaceFlow: (side: PlayerPropMarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function PlayerPropList({
  results,
  activeLens,
  boostPercent,
  kellyMultiplier,
  bankroll,
  canLoadMore,
  isLoadingMore = false,
  onLoadMore,
  onLogBet,
  onAddToCart,
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: PlayerPropListProps) {
  return (
    <>
      <div className="space-y-2">
        {results.map((side, idx) => (
          <div
            key={`${side.selection_key}-${side.sportsbook}`}
            className="animate-slide-up"
            style={{ animationDelay: `${idx * 40}ms` }}
          >
            <PlayerPropCard
              side={side}
              activeLens={activeLens}
              boostPercent={boostPercent}
              kellyMultiplier={kellyMultiplier}
              bankroll={bankroll}
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
