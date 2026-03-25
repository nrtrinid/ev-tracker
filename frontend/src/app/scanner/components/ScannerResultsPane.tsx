import { Card, CardContent } from "@/components/ui/card";
import type { ScannerNullState } from "@/lib/scanner-contract";
import type { MarketSide, ScannerSurface } from "@/lib/types";
import { getScannerSurface } from "../scanner-surfaces";
import type { PickEmBoardCard, PickEmSlipPick } from "../pickem-board";
import { PlayerPropList } from "./PlayerPropList";
import { PickEmBoardList } from "./PickEmBoardList";
import { StraightBetList } from "./StraightBetList";

interface ScannerResultsPaneProps {
  surface: ScannerSurface;
  playerPropsView?: "sportsbooks" | "pickem";
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier";
  tutorialMode?: boolean;
  results: Array<MarketSide & { _retention?: number; _boostedEV?: number }>;
  pickemCards?: PickEmBoardCard[];
  sourceCount: number;
  rawSourceCount: number;
  filteredCount: number;
  nullState: ScannerNullState;
  activeResultFilterSummary: string;
  pickemEmptyMessage?: string | null;
  pickemEmptySubMessage?: string | null;
  addedPickEmComparisonKeys?: string[];
  kellyMultiplier: number;
  bankroll: number;
  boostPercent: number;
  canLoadMore: boolean;
  onLoadMore: () => void;
  onAddPickEmToSlip: (pick: PickEmSlipPick) => void;
  onLogBet: (side: MarketSide) => void;
  onAddToCart: (side: MarketSide) => void;
  onStartPlaceFlow: (side: MarketSide) => void;
  bookColors: Record<string, string>;
  sportDisplayMap: Record<string, string>;
}

export function ScannerResultsPane({
  surface,
  playerPropsView = "sportsbooks",
  activeLens,
  tutorialMode = false,
  results,
  pickemCards = [],
  sourceCount,
  rawSourceCount,
  filteredCount,
  nullState,
  activeResultFilterSummary,
  pickemEmptyMessage = null,
  pickemEmptySubMessage = null,
  addedPickEmComparisonKeys = [],
  kellyMultiplier,
  bankroll,
  boostPercent,
  canLoadMore,
  onLoadMore,
  onAddPickEmToSlip,
  onLogBet,
  onAddToCart,
  onStartPlaceFlow,
  bookColors,
  sportDisplayMap,
}: ScannerResultsPaneProps) {
  const surfaceConfig = getScannerSurface(surface);
  const isPropsSurface = surface === "player_props";
  const isPickEmView = isPropsSurface && playerPropsView === "pickem";
  const pregameExcludedCount = Math.max(0, rawSourceCount - sourceCount);
  const scanExpiredOutOfPregame = nullState === "backend_empty" && pregameExcludedCount > 0;

  return (
    <div className="space-y-2">
      {tutorialMode && (
        <p className="px-0.5 text-xs text-muted-foreground">
          Tutorial mode: the lines below are sample straight bets. Practice tickets stay local to this walkthrough and disappear when you finish it.
        </p>
      )}
      {isPickEmView && (
        <p className="px-0.5 text-xs text-muted-foreground">
          Pick&apos;em support uses all scanned books for exact-line consensus. My Books only affects the sportsbook card view.
        </p>
      )}
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
        {isPropsSurface
          ? isPickEmView
            ? `Showing ${pickemCards.length} of ${sourceCount} available pick'em board lines`
            : `Showing ${results.length} of ${sourceCount} available props`
          : tutorialMode
            ? `Showing ${results.length} of ${filteredCount} Tutorial Lines`
            : `Showing ${results.length} of ${filteredCount} ${
              activeLens === "standard"
                ? "+EV Lines"
                : activeLens === "bonus_bet"
                  ? "Bonus Bet Targets"
                  : activeLens === "profit_boost"
                    ? "Boost Opportunities"
                    : "Qualifier Candidates"
            }`}
      </h2>

      {(isPickEmView ? pickemCards.length === 0 : results.length === 0) ? (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center">
            <p className="text-sm text-muted-foreground">
              {scanExpiredOutOfPregame
                ? isPickEmView
                  ? `${rawSourceCount} pick'em board lines were scanned, but none are still pregame.`
                  : isPropsSurface
                    ? `${rawSourceCount} props were scanned, but none are still pregame.`
                    : `${rawSourceCount} plays were scanned, but none are still pregame.`
                : isPickEmView && nullState === "backend_empty"
                ? pickemEmptyMessage ||
                  "No supported pick'em board lines are available for this scan yet."
                : nullState === "backend_empty"
                ? isPropsSurface
                  ? surfaceConfig.emptyLabel
                  : activeLens === "standard"
                    ? "No clear starter plays right now. Check back when lines move."
                    : activeLens === "bonus_bet"
                      ? "No bonus-bet targets are standing out right now."
                      : activeLens === "qualifier"
                        ? "No clean qualifier candidates are in range right now."
                        : "No strong boost opportunities are standing out at this percentage."
                : isPickEmView
                  ? `${sourceCount} pick'em board lines were available, but your current filters hid all of them.`
                  : isPropsSurface
                  ? `${sourceCount} props were scanned, but your current filters hid all of them.`
                  : "Your current filters are hiding all of the available plays."}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {scanExpiredOutOfPregame
                ? "Started games are hidden by default. Refresh to load the current slate."
                : isPickEmView && nullState === "backend_empty"
                ? pickemEmptySubMessage ||
                  "Adjust your market filters or try a new scan later."
                : nullState === "backend_empty"
                ? "Try a refresh later, or switch books if you want a different slate."
                : "Try Reset, loosen Safer Odds, or turn off Hide Logged to see more options."}
            </p>
            {nullState === "filter_empty" && (
              <p className="mt-2 text-xs text-muted-foreground">{activeResultFilterSummary}</p>
            )}
          </CardContent>
        </Card>
      ) : (
        isPickEmView ? (
          <PickEmBoardList
            cards={pickemCards}
            canLoadMore={canLoadMore}
            onLoadMore={onLoadMore}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
            addedComparisonKeys={addedPickEmComparisonKeys}
            onAddToSlip={onAddPickEmToSlip}
          />
        ) : isPropsSurface ? (
          <PlayerPropList
            results={results as Array<Extract<MarketSide, { surface: "player_props" }> & { _retention?: number; _boostedEV?: number }>}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            canLoadMore={canLoadMore}
            onLoadMore={onLoadMore}
            onLogBet={(side) => onLogBet(side)}
            onAddToCart={(side) => onAddToCart(side)}
            onStartPlaceFlow={(side) => onStartPlaceFlow(side)}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
          />
        ) : (
          <StraightBetList
            activeLens={activeLens}
            tutorialMode={tutorialMode}
            results={results}
            kellyMultiplier={kellyMultiplier}
            bankroll={bankroll}
            boostPercent={boostPercent}
            canLoadMore={canLoadMore}
            onLoadMore={onLoadMore}
            onLogBet={onLogBet}
            onAddToCart={onAddToCart}
            onStartPlaceFlow={onStartPlaceFlow}
            bookColors={bookColors}
            sportDisplayMap={sportDisplayMap}
          />
        )
      )}
    </div>
  );
}
