import { useState } from "react";
import { SlidersHorizontal, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { formatPlayerPropMarketLabel, formatPlayerPropSportLabel } from "@/lib/player-prop-markets";
import { cn } from "@/lib/utils";
import type {
  ScannerResultFilters,
  ScannerRiskPreset,
  ScannerTimePreset,
} from "@/lib/scanner-filters";
import { shouldShowProfitBoostContextControls, type ScannerLens } from "../scanner-ui-model";

const TIME_OPTIONS: Array<{ value: ScannerTimePreset; label: string }> = [
  { value: "all", label: "All" },
  { value: "starting_soon", label: "Starting Soon" },
  { value: "today", label: "Today" },
  { value: "tomorrow", label: "Tomorrow" },
];

const EDGE_OPTIONS = [0, 1, 1.5, 2, 3];

const RISK_OPTIONS: Array<{ value: ScannerRiskPreset; label: string; hint: string }> = [
  { value: "any", label: "Any Odds", hint: "No odds cap" },
  { value: "safer", label: "Safer", hint: "Up to +150" },
  { value: "balanced", label: "Balanced", hint: "Up to +300" },
];

interface ScannerResultFiltersProps {
  filters: ScannerResultFilters;
  surface: "straight_bets" | "player_props";
  showEdgeControl: boolean;
  activeLens: ScannerLens;
  boostPercent: number;
  customBoostInput: string;
  boostPresets: number[];
  activeFilterChips: string[];
  hasActiveFilters: boolean;
  hidePropSideControl?: boolean;
  sharedPropsOnly?: boolean;
  searchPlaceholder?: string;
  availablePropSports?: string[];
  availablePropMarkets?: string[];
  onSearchChange: (value: string) => void;
  onTimePresetChange: (value: ScannerTimePreset) => void;
  onEdgeMinChange: (value: number) => void;
  onHideLongshotsChange: (checked: boolean) => void;
  onHideAlreadyLoggedChange: (checked: boolean) => void;
  onRiskPresetChange: (value: ScannerRiskPreset) => void;
  onPropSportChange: (value: string) => void;
  onPropMarketChange: (value: string) => void;
  onPropSideChange: (value: "all" | "over" | "under") => void;
  onPresetSelect: (value: number) => void;
  onCustomBoostInputChange: (value: string) => void;
  onResetFilters: () => void;
}

// Selected filter button style — semantic, works in light + dark
const FILTER_SELECTED = "border-color-profit/40 bg-color-profit-subtle text-color-profit-fg";
const FILTER_IDLE = "border-border bg-background text-muted-foreground hover:text-foreground";
const FILTER_IDLE_FULL = "border-border bg-background text-foreground";

// Boost selected style — uses primary/gold accent
const BOOST_SELECTED = "border-primary/40 bg-primary/15 text-primary";

export function ScannerResultFilters({
  filters,
  surface,
  showEdgeControl,
  activeLens,
  boostPercent,
  customBoostInput,
  boostPresets,
  activeFilterChips,
  hasActiveFilters,
  hidePropSideControl = false,
  sharedPropsOnly = false,
  searchPlaceholder = "Search team",
  availablePropSports = [],
  availablePropMarkets = [],
  onSearchChange,
  onTimePresetChange,
  onEdgeMinChange,
  onHideLongshotsChange,
  onHideAlreadyLoggedChange,
  onRiskPresetChange,
  onPropSportChange,
  onPropMarketChange,
  onPropSideChange,
  onPresetSelect,
  onCustomBoostInputChange,
  onResetFilters,
}: ScannerResultFiltersProps) {
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const [mobileBoostOpen, setMobileBoostOpen] = useState(false);

  const moreFiltersContent = (
    <>
      <DropdownMenuLabel>Result Filters</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuLabel>Time</DropdownMenuLabel>
      <DropdownMenuRadioGroup
        value={filters.timePreset}
        onValueChange={(value) => onTimePresetChange(value as ScannerTimePreset)}
      >
        {TIME_OPTIONS.map((option) => (
          <DropdownMenuRadioItem key={option.value} value={option.value}>
            {option.label}
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>

      {showEdgeControl && (
        <>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Edge Threshold</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={String(filters.edgeMinStandard)}
            onValueChange={(value) => onEdgeMinChange(Number(value))}
          >
            {EDGE_OPTIONS.map((edge) => (
              <DropdownMenuRadioItem key={edge} value={String(edge)}>
                {edge === 0 ? "All +EV" : `${edge.toFixed(1)}%+`}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </>
      )}

      {!sharedPropsOnly && (
        <>
          <DropdownMenuCheckboxItem
            checked={filters.hideLongshots}
            onCheckedChange={(checked) => onHideLongshotsChange(Boolean(checked))}
          >
            Hide longshots (&gt; +500)
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={filters.hideAlreadyLogged}
            onCheckedChange={(checked) => onHideAlreadyLoggedChange(Boolean(checked))}
          >
            Hide already logged
          </DropdownMenuCheckboxItem>

          <DropdownMenuSeparator />
          <DropdownMenuLabel>Risk Preset</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={filters.riskPreset}
            onValueChange={(value) => onRiskPresetChange(value as ScannerRiskPreset)}
          >
            {RISK_OPTIONS.map((option) => (
              <DropdownMenuRadioItem key={option.value} value={option.value}>
                {option.label}
                <span className="ml-2 text-[10px] text-muted-foreground">{option.hint}</span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </>
      )}

      {surface === "player_props" && !hidePropSideControl && (
        <>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Sport</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={filters.propSport} onValueChange={onPropSportChange}>
            <DropdownMenuRadioItem value="all">All sports</DropdownMenuRadioItem>
            {availablePropSports.map((sport) => (
              <DropdownMenuRadioItem key={sport} value={sport}>
                {formatPlayerPropSportLabel(sport)}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>

          <DropdownMenuSeparator />
          <DropdownMenuLabel>Prop Market</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={filters.propMarket} onValueChange={onPropMarketChange}>
            <DropdownMenuRadioItem value="all">All markets</DropdownMenuRadioItem>
            {availablePropMarkets.map((market) => (
                <DropdownMenuRadioItem key={market} value={market}>
                {formatPlayerPropMarketLabel(market)}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>

          <DropdownMenuSeparator />
          <DropdownMenuLabel>Prop Side</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={filters.propSide}
            onValueChange={(value) => onPropSideChange(value as "all" | "over" | "under")}
          >
            <DropdownMenuRadioItem value="all">All sides</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="over">Over</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="under">Under</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </>
      )}
    </>
  );

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            value={filters.searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
            className="h-10 rounded-md border border-border bg-background pl-9 pr-3 text-sm border-b-border"
          />
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="secondary"
              className="hidden h-10 shrink-0 px-3 text-xs md:inline-flex"
            >
              <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5" />
              More
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            {moreFiltersContent}
          </DropdownMenuContent>
        </DropdownMenu>

        <Sheet open={mobileMoreOpen} onOpenChange={setMobileMoreOpen}>
          <SheetTrigger asChild>
            <Button
              type="button"
              variant="secondary"
              className="h-10 w-10 shrink-0 p-0 md:hidden"
              aria-label="More filters"
            >
              <SlidersHorizontal className="h-5 w-5 mx-auto" />
            </Button>
          </SheetTrigger>
          <SheetContent side="bottom" className="pb-5">
            <SheetHeader>
              <SheetTitle>More Filters</SheetTitle>
              <SheetDescription>
                Fine-tune which scanner results are shown.
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-4 px-6 pt-3">
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Time</p>
                <div className="grid grid-cols-2 gap-2">
                  {TIME_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => onTimePresetChange(option.value)}
                      className={cn(
                        "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                        filters.timePreset === option.value ? FILTER_SELECTED : FILTER_IDLE_FULL
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              {showEdgeControl && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Edge threshold</p>
                  <div className="grid grid-cols-3 gap-2">
                    {EDGE_OPTIONS.map((edge) => (
                      <button
                        key={edge}
                        type="button"
                        onClick={() => onEdgeMinChange(edge)}
                        className={cn(
                          "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                          filters.edgeMinStandard === edge ? FILTER_SELECTED : FILTER_IDLE_FULL
                        )}
                      >
                        {edge === 0 ? "All +EV" : `${edge.toFixed(1)}%+`}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {!sharedPropsOnly && (
                <>
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">Visibility</p>
                    <button
                      type="button"
                      onClick={() => onHideLongshotsChange(!filters.hideLongshots)}
                      className={cn(
                        "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors",
                        filters.hideLongshots ? FILTER_SELECTED : FILTER_IDLE_FULL
                      )}
                    >
                      Hide longshots (&gt; +500)
                    </button>
                    <button
                      type="button"
                      onClick={() => onHideAlreadyLoggedChange(!filters.hideAlreadyLogged)}
                      className={cn(
                        "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors",
                        filters.hideAlreadyLogged ? FILTER_SELECTED : FILTER_IDLE_FULL
                      )}
                    >
                      Hide already logged
                    </button>
                  </div>

                  <div className="space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">Risk preset</p>
                    <div className="grid grid-cols-1 gap-2">
                      {RISK_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => onRiskPresetChange(option.value)}
                          className={cn(
                            "w-full rounded-md border px-3 py-2 text-left transition-colors",
                            filters.riskPreset === option.value ? FILTER_SELECTED : FILTER_IDLE_FULL
                          )}
                        >
                          <span className="block text-sm font-medium">{option.label}</span>
                          <span className="block text-xs text-muted-foreground">{option.hint}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {surface === "player_props" && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Sport</p>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => onPropSportChange("all")}
                      className={cn(
                        "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                        filters.propSport === "all" ? FILTER_SELECTED : FILTER_IDLE_FULL
                      )}
                    >
                      All sports
                    </button>
                    {availablePropSports.map((sport) => (
                      <button
                        key={sport}
                        type="button"
                        onClick={() => onPropSportChange(sport)}
                        className={cn(
                          "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                          filters.propSport === sport ? FILTER_SELECTED : FILTER_IDLE_FULL
                        )}
                      >
                        {formatPlayerPropSportLabel(sport)}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {surface === "player_props" && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Prop market</p>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => onPropMarketChange("all")}
                      className={cn(
                        "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                        filters.propMarket === "all" ? FILTER_SELECTED : FILTER_IDLE_FULL
                      )}
                    >
                      All markets
                    </button>
                    {availablePropMarkets.map((market) => (
                      <button
                        key={market}
                        type="button"
                        onClick={() => onPropMarketChange(market)}
                        className={cn(
                          "rounded-md border px-2 py-1.5 text-xs font-medium capitalize transition-colors",
                          filters.propMarket === market ? FILTER_SELECTED : FILTER_IDLE_FULL
                        )}
                      >
                        {formatPlayerPropMarketLabel(market)}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {surface === "player_props" && !hidePropSideControl && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Prop side</p>
                  <div className="grid grid-cols-3 gap-2">
                    {(["all", "over", "under"] as const).map((side) => (
                      <button
                        key={side}
                        type="button"
                        onClick={() => onPropSideChange(side)}
                        className={cn(
                          "rounded-md border px-2 py-1.5 text-xs font-medium capitalize transition-colors",
                          filters.propSide === side ? FILTER_SELECTED : FILTER_IDLE_FULL
                        )}
                      >
                        {side}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </SheetContent>
        </Sheet>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1">
        <button
          type="button"
          onClick={() => onTimePresetChange(filters.timePreset === "starting_soon" ? "all" : "starting_soon")}
          className={cn(
            "whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
            filters.timePreset === "starting_soon" ? FILTER_SELECTED : FILTER_IDLE
          )}
        >
          Starting Soon
        </button>
        {!sharedPropsOnly && (
          <>
            <button
              type="button"
              onClick={() => onRiskPresetChange(filters.riskPreset === "safer" ? "any" : "safer")}
              className={cn(
                "whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
                filters.riskPreset === "safer" ? FILTER_SELECTED : FILTER_IDLE
              )}
            >
              Safer Odds
            </button>
            <button
              type="button"
              onClick={() => onHideAlreadyLoggedChange(!filters.hideAlreadyLogged)}
              className={cn(
                "whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
                filters.hideAlreadyLogged ? FILTER_SELECTED : FILTER_IDLE
              )}
            >
              Hide Logged
            </button>
          </>
        )}
      </div>

      {shouldShowProfitBoostContextControls(activeLens) && (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            className="hidden h-8 border border-primary/30 bg-primary/10 px-2.5 text-xs text-primary hover:bg-primary/20 md:inline-flex"
            onClick={() => setMobileBoostOpen(true)}
          >
            Boost: {boostPercent}%
          </Button>
          <Button
            type="button"
            variant="secondary"
            className="h-8 border border-primary/30 bg-primary/10 px-2.5 text-xs text-primary hover:bg-primary/20 md:hidden"
            onClick={() => setMobileBoostOpen(true)}
          >
            Boost: {boostPercent}%
          </Button>
          <Sheet open={mobileBoostOpen} onOpenChange={setMobileBoostOpen}>
            <SheetContent side="bottom" className="pb-5">
              <SheetHeader>
                <SheetTitle>Profit Boost</SheetTitle>
                <SheetDescription>Set your boost percentage.</SheetDescription>
              </SheetHeader>
              <div className="space-y-3 px-6 pt-3">
                <div className="grid grid-cols-3 gap-2">
                  {boostPresets.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => {
                        onPresetSelect(preset);
                        setMobileBoostOpen(false);
                      }}
                      className={cn(
                        "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                        boostPercent === preset && customBoostInput === ""
                          ? BOOST_SELECTED
                          : FILTER_IDLE_FULL
                      )}
                    >
                      {preset}%
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Custom</span>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    placeholder="1-200"
                    value={customBoostInput}
                    onChange={(e) => onCustomBoostInputChange(e.target.value)}
                    className={cn(
                      "h-8 w-20 rounded-md border bg-background px-2 text-xs font-medium text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50",
                      customBoostInput !== "" ? "border-primary/40" : "border-border"
                    )}
                  />
                  <span className="text-xs text-muted-foreground">%</span>
                </div>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      )}

      {activeFilterChips.length > 0 && (
        <div className="flex items-center justify-between gap-2 pt-0.5">
          <div className="flex flex-1 flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-medium text-muted-foreground">Filters:</span>
            {activeFilterChips.slice(0, 3).map((chip) => (
              <span
                key={chip}
                className="rounded-full border border-color-profit/25 bg-color-profit-subtle px-2 py-0.5 text-[10px] text-color-profit-fg"
              >
                {chip}
              </span>
            ))}
            {activeFilterChips.length > 3 && (
              <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] text-muted-foreground">
                +{activeFilterChips.length - 3} more
              </span>
            )}
          </div>

          {hasActiveFilters && (
            <Button
              type="button"
              variant="ghost"
              className="h-5 px-1 text-[10px] font-medium text-muted-foreground hover:text-foreground"
              onClick={onResetFilters}
            >
              Reset
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
