import { Card, CardContent } from "@/components/ui/card";
import type { ScannerNullState } from "@/lib/scanner-contract";
import type { MarketSide } from "@/lib/types";
import { StraightBetList } from "./StraightBetList";

interface ScannerResultsPaneProps {
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  results: Array<MarketSide & { _retention?: number; _boostedEV?: number }>;
  filteredCount: number;
  nullState: ScannerNullState;
  activeResultFilterSummary: string;
  kellyMultiplier: number;
  bankroll: number;
  boostPercent: number;
  canLoadMore: boolean;
  onLoadMore: () => void;
  onLogBet: (side: MarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function ScannerResultsPane({
  activeLens,
  results,
  filteredCount,
  nullState,
  activeResultFilterSummary,
  kellyMultiplier,
  bankroll,
  boostPercent,
  canLoadMore,
  onLoadMore,
  onLogBet,
  bookColors,
  sportDisplayMap,
}: ScannerResultsPaneProps) {
  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
        Showing {results.length} of {filteredCount}{" "}
        {activeLens === "standard"
          ? "+EV Lines"
          : activeLens === "bonus_bet"
            ? "Bonus Bet Targets"
            : activeLens === "profit_boost"
              ? "Boost Opportunities"
              : "Qualifier Candidates"}
      </h2>

      {results.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center">
            <p className="text-sm text-muted-foreground">
              {nullState === "backend_empty"
                ? activeLens === "standard"
                  ? "No +EV lines right now. Check back when lines move."
                  : activeLens === "bonus_bet"
                    ? "No bonus bet targets above 60% retention."
                    : activeLens === "qualifier"
                      ? "No qualifier candidates in the target odds range right now."
                      : "No profitable boost opportunities at this percentage."
                : "No results match your current filters."}
            </p>
            {nullState === "filter_empty" && (
              <p className="mt-2 text-xs text-muted-foreground">{activeResultFilterSummary}</p>
            )}
          </CardContent>
        </Card>
      ) : (
        <StraightBetList
          activeLens={activeLens}
          results={results}
          kellyMultiplier={kellyMultiplier}
          bankroll={bankroll}
          boostPercent={boostPercent}
          canLoadMore={canLoadMore}
          onLoadMore={onLoadMore}
          onLogBet={onLogBet}
          bookColors={bookColors}
          sportDisplayMap={sportDisplayMap}
        />
      )}
    </div>
  );
}
