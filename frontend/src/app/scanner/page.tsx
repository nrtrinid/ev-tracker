"use client";

import { useState, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { cn, formatCurrency, formatOdds, calculateStealthStake } from "@/lib/utils";
import {
  Radar,
  TrendingUp,
  Gift,
  Zap,
  Loader2,
  Clock,
  ChevronRight,
  Info,
} from "lucide-react";
import { scanMarkets } from "@/lib/api";
import type { MarketSide, ScanResult, ScannedBetData, PromoType } from "@/lib/types";
import { useKellySettings } from "@/lib/kelly-context";
import { useBalances } from "@/lib/hooks";
import { useQuery } from "@tanstack/react-query";

// ============ Constants ============

const SPORT_KEY_TO_DISPLAY: Record<string, string> = {
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
  football_nfl: "NFL",
  football_ncaaf: "NCAAF",
  baseball_mlb: "MLB",
  icehockey_nhl: "NHL",
  mma_mixed_martial_arts: "UFC",
  soccer_usa_mls: "Soccer",
  tennis_atp_us_open: "Tennis",
};

const AVAILABLE_BOOKS = [
  "DraftKings",
  "FanDuel",
  "BetMGM",
  "Caesars",
  "ESPN Bet",
];

const DEFAULT_SELECTED_BOOKS = ["DraftKings", "FanDuel"];
const LONGSHOT_MAX_AMERICAN = 500;

type Lens = "standard" | "profit_boost" | "bonus_bet" | "qualifier";

const BOOST_PRESETS = [25, 30, 50];

const bookColors: Record<string, string> = {
  DraftKings: "bg-draftkings",
  FanDuel: "bg-fanduel",
  BetMGM: "bg-betmgm",
  Caesars: "bg-caesars",
  "ESPN Bet": "bg-espnbet",
};

// ============ Helpers ============

function formatGameTime(isoString: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function calculateRetention(side: MarketSide): number {
  return (side.book_decimal - 1) * side.true_prob;
}

function calculateBoostedEV(side: MarketSide, boostPercent: number): number {
  const baseProfit = side.book_decimal - 1;
  const boostedProfit = baseProfit * (1 + boostPercent / 100);
  const boostedDecimal = 1 + boostedProfit;
  return (side.true_prob * boostedDecimal - 1) * 100;
}

function boostedDecimalOdds(side: MarketSide, boostPercent: number): number {
  const baseProfit = side.book_decimal - 1;
  return 1 + baseProfit * (1 + boostPercent / 100);
}

function decimalToAmerican(decimal: number): number {
  if (decimal >= 2.0) return Math.round((decimal - 1) * 100);
  return Math.round(-100 / (decimal - 1));
}

function minutesAgo(isoString: string): number {
  if (!isoString) return 0;
  const then = new Date(isoString).getTime();
  return Math.max(0, Math.floor((Date.now() - then) / 60_000));
}

function bookAbbrev(name: string): string {
  const map: Record<string, string> = {
    DraftKings: "DK",
    FanDuel: "FD",
    BetMGM: "MGM",
    Caesars: "CZR",
    "ESPN Bet": "ESPN",
  };
  return map[name] || name;
}

// ============ Page ============

export default function ScannerPage() {
  const queryClient = useQueryClient();
  const { data: balances } = useBalances();
  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const computedBankroll = useMemo(() => {
    if (!balances || balances.length === 0) return 0;
    return balances.reduce((sum, b) => sum + (b.balance || 0), 0);
  }, [balances]);
  const bankroll = useComputedBankroll ? computedBankroll : bankrollOverride;
  const {
    data: scanData,
    isFetching: isScanning,
    error: scanErrorRaw,
    refetch: refetchScan,
  } = useQuery({
    queryKey: ["scan-markets"],
    queryFn: scanMarkets,
    enabled: false, // only run when user clicks
    staleTime: 5 * 60 * 1000, // keep results fresh-ish across page switches
    gcTime: 30 * 60 * 1000, // keep in cache for 30 minutes
    retry: 1,
  });
  const scanError = scanErrorRaw instanceof Error ? scanErrorRaw.message : null;
  const [cooldown, setCooldown] = useState(0);
  const [activeLens, setActiveLens] = useState<Lens>("standard");
  const [boostPercent, setBoostPercent] = useState(30);
  const [customBoostInput, setCustomBoostInput] = useState("");
  const [selectedBooks, setSelectedBooks] = useState<string[]>(DEFAULT_SELECTED_BOOKS);
  const [visibleCount, setVisibleCount] = useState(10);
  const [hideLongshots, setHideLongshots] = useState(true);

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const [drawerInitialValues, setDrawerInitialValues] = useState<
    ScannedBetData | undefined
  >();

  // Cooldown timer
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((prev) => {
        if (prev <= 1) return 0;
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const handleScan = async () => {
    if (cooldown > 0 || isScanning) return;
    await refetchScan();
    setCooldown(60);
    // Piggyback just updated CLV snapshots in the DB — invalidate bets so
    // the dashboard/bet list shows fresh CLV badges without a manual refresh.
    queryClient.invalidateQueries({ queryKey: ["bets"] });
  };

  const toggleBook = (book: string) => {
    setSelectedBooks((prev) => {
      if (prev.includes(book)) {
        if (prev.length === 1) return prev; // keep at least one
        return prev.filter((b) => b !== book);
      }
      return [...prev, book];
    });
  };

  // Filter by selected books then apply lens
  const fullResults = useMemo(() => {
    if (!scanData) return [];
    const sides = scanData.sides
      .filter((s) => selectedBooks.includes(s.sportsbook))
      .filter((s) => !hideLongshots || s.book_odds <= LONGSHOT_MAX_AMERICAN);

    switch (activeLens) {
      case "standard":
        return sides
          .filter((s) => s.ev_percentage > 0)
          .sort((a, b) => b.ev_percentage - a.ev_percentage);

      case "profit_boost":
        return sides
          .map((s) => ({ ...s, _boostedEV: calculateBoostedEV(s, boostPercent) }))
          .filter((s) => s._boostedEV > 0)
          .sort((a, b) => b._boostedEV - a._boostedEV);

      case "bonus_bet":
        return sides
          .map((s) => ({ ...s, _retention: calculateRetention(s) }))
          .sort((a, b) => b._retention - a._retention);

      case "qualifier":
        return sides
          .filter((s) => s.book_odds >= -250 && s.book_odds <= 150)
          .sort((a, b) => b.ev_percentage - a.ev_percentage);
    }
  }, [scanData, activeLens, boostPercent, selectedBooks]);

  useEffect(() => {
    setVisibleCount(10);
  }, [scanData, activeLens, boostPercent, selectedBooks, hideLongshots]);

  const results = useMemo(() => {
    return fullResults.slice(0, visibleCount);
  }, [fullResults, visibleCount]);

  const handleLogBet = (side: MarketSide) => {
    const sportDisplay = SPORT_KEY_TO_DISPLAY[side.sport] || side.sport;

    let promoType: PromoType = "standard";
    let boostPct: number | undefined;

    if (activeLens === "bonus_bet") {
      promoType = "bonus_bet";
    } else if (activeLens === "profit_boost") {
      promoType = "boost_custom";
      boostPct = boostPercent;
    }

    const rawKellyStake = Math.max(0, side.base_kelly_fraction * kellyMultiplier * bankroll);
    const stealthKellyStake = calculateStealthStake(rawKellyStake);

    setDrawerInitialValues({
      sportsbook: side.sportsbook,
      sport: sportDisplay,
      event: `${side.team} ML`,
      market: "ML",
      odds_american: side.book_odds,
      opposing_odds: side.pinnacle_odds,
      promo_type: promoType,
      boost_percent: boostPct,
      // CLV tracking metadata — stored silently at bet creation
      pinnacle_odds_at_entry: side.pinnacle_odds,
      commence_time: side.commence_time,
      clv_team: side.team,
      clv_sport_key: side.sport,
      true_prob_at_entry: side.true_prob,  // de-vigged Pinnacle prob — used for accurate EV
      raw_kelly_stake: rawKellyStake,
      stealth_kelly_stake: stealthKellyStake,
    });
    setDrawerKey(Date.now());
    setDrawerOpen(true);
  };

  const getMetric = (
    side: MarketSide & { _retention?: number; _boostedEV?: number }
  ) => {
    switch (activeLens) {
      case "standard":
      case "qualifier":
        return {
          label: "EV",
          value: `${side.ev_percentage >= 0 ? "+" : ""}${side.ev_percentage.toFixed(
            1
          )}%`,
          positive: side.ev_percentage > 0,
        };
      case "bonus_bet": {
        const ret = side._retention ?? calculateRetention(side);
        return {
          label: "Retention",
          value: `${(ret * 100).toFixed(1)}%`,
          positive: ret >= 0.7,
        };
      }
      case "profit_boost": {
        const bev = side._boostedEV ?? calculateBoostedEV(side, boostPercent);
        return {
          label: "Boosted EV",
          value: `${bev >= 0 ? "+" : ""}${bev.toFixed(1)}%`,
          positive: bev > 0,
        };
      }
    }
  };

  const lensCards: {
    id: Lens;
    label: string;
    desc: string;
    icon: typeof TrendingUp;
    activeBg: string;
    activeText: string;
  }[] = [
    {
      id: "standard",
      label: "Standard EV",
      desc: "Best +EV lines",
      icon: TrendingUp,
      activeBg: "bg-[#4A7C59]/15 border-[#4A7C59]/40",
      activeText: "text-[#4A7C59]",
    },
    {
      id: "profit_boost",
      label: "Profit Boost",
      desc: "Boosted EV lines",
      icon: Zap,
      activeBg: "bg-[#C4A35A]/15 border-[#C4A35A]/40",
      activeText: "text-[#C4A35A]",
    },
    {
      id: "bonus_bet",
      label: "Bonus Bet",
      desc: "Best bonus conversion",
      icon: Gift,
      activeBg: "bg-[#0EA5A4]/15 border-[#0EA5A4]/40",
      activeText: "text-[#0EA5A4]",
    },
    {
      id: "qualifier",
      label: "Qualifier",
      desc: "Low-loss promo legs",
      icon: TrendingUp,
      activeBg: "bg-[#B85C38]/10 border-[#B85C38]/30",
      activeText: "text-[#B85C38]",
    },
  ];

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-6 space-y-5 max-w-2xl pb-24">
        {/* Header */}
        <div>
          <h1 className="text-xl font-semibold">Scanner</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Best +EV lines across all sports and your selected books
          </p>
        </div>

        {/* Books selector */}
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-2 block pl-0.5">
            My Books
          </label>
          <div className="flex gap-1.5 overflow-x-auto no-scrollbar pb-1">
            {AVAILABLE_BOOKS.map((book) => {
              const isSelected = selectedBooks.includes(book);
              return (
                <button
                  key={book}
                  type="button"
                  onClick={() => toggleBook(book)}
                  className={cn(
                    "flex-shrink-0 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap",
                    isSelected
                      ? `${bookColors[book] || "bg-foreground"} text-white shadow-md`
                      : "bg-muted text-muted-foreground hover:bg-secondary"
                  )}
                >
                  {book}
                </button>
              );
            })}
          </div>
        </div>

        {/* Full Scan Button */}
        <Button
          className="w-full h-12 text-base font-semibold"
          onClick={handleScan}
          disabled={isScanning || cooldown > 0}
        >
          {isScanning ? (
            <>
              <Loader2 className="h-5 w-5 mr-2 animate-spin" />
              Scanning all sports…
            </>
          ) : cooldown > 0 ? (
            <>
              <Clock className="h-5 w-5 mr-2" />
              Rescan in {cooldown}s
            </>
          ) : (
            <>
              <Radar className="h-5 w-5 mr-2" />
              {scanData ? "Rescan" : "Full Scan"}
            </>
          )}
        </Button>

        {scanError && (
          <p className="text-sm text-[#B85C38] text-center">{scanError}</p>
        )}

        {/* Scan metadata */}
        {scanData && (
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {scanData.scanned_at && (
              <span>Data as of {minutesAgo(scanData.scanned_at)} min ago</span>
            )}
            <span>{scanData.events_fetched} events</span>
            <span className="w-px h-3 bg-border" />
            <span>{scanData.events_with_both_books} with sharp + target</span>
            {scanData.api_requests_remaining && (
              <>
                <span className="w-px h-3 bg-border" />
                <span>{scanData.api_requests_remaining} API calls left</span>
              </>
            )}
          </div>
        )}

        {/* Promo Lens Cards */}
        {scanData && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {lensCards.map((lens) => {
              const Icon = lens.icon;
              const isActive = activeLens === lens.id;
              return (
                <button
                  key={lens.id}
                  type="button"
                  onClick={() => setActiveLens(lens.id)}
                  className={cn(
                    "rounded-xl border p-3 text-left transition-all",
                    isActive
                      ? lens.activeBg
                      : "border-border bg-card hover:border-border/80"
                  )}
                >
                  <Icon
                    className={cn(
                      "h-5 w-5 mb-1.5",
                      isActive ? lens.activeText : "text-muted-foreground"
                    )}
                  />
                  <p
                    className={cn(
                      "text-sm font-semibold leading-tight",
                      isActive ? lens.activeText : "text-foreground"
                    )}
                  >
                    {lens.label}
                  </p>
                  <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight">
                    {lens.desc}
                  </p>
                </button>
              );
            })}
          </div>
        )}

        {/* Controls row: boost pills (profit_boost lens) + longshot toggle */}
        {scanData && (
          <div className="flex items-center justify-between gap-2 flex-wrap">
            {/* Left: boost pills (only when on profit_boost lens) */}
            {activeLens === "profit_boost" ? (
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-medium text-muted-foreground mr-0.5">Boost:</span>
                {BOOST_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => {
                      setBoostPercent(preset);
                      setCustomBoostInput("");
                    }}
                    className={cn(
                      "px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                      boostPercent === preset && customBoostInput === ""
                        ? "bg-[#C4A35A]/25 text-[#5C4D2E] border border-[#C4A35A]/40"
                        : "bg-muted text-muted-foreground hover:bg-secondary"
                    )}
                  >
                    {preset}%
                  </button>
                ))}
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min={1}
                    max={200}
                    placeholder="Custom"
                    value={customBoostInput}
                    onChange={(e) => {
                      const val = e.target.value;
                      setCustomBoostInput(val);
                      const n = parseInt(val, 10);
                      if (!isNaN(n) && n > 0 && n <= 200) setBoostPercent(n);
                    }}
                    className={cn(
                      "w-16 px-2 py-1 rounded-md text-xs font-medium border transition-colors bg-muted text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-[#C4A35A]/50",
                      customBoostInput !== "" ? "border-[#C4A35A]/40" : "border-transparent"
                    )}
                  />
                  {customBoostInput !== "" && (
                    <span className="text-xs text-muted-foreground">%</span>
                  )}
                </div>
              </div>
            ) : (
              <div />
            )}

            {/* Right: longshot toggle chip */}
            <button
              type="button"
              onClick={() => setHideLongshots((v) => !v)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors",
                hideLongshots
                  ? "bg-muted text-muted-foreground border-transparent hover:bg-secondary"
                  : "bg-[#B85C38]/10 text-[#B85C38] border-[#B85C38]/30"
              )}
            >
              <span>{hideLongshots ? `Hiding > +${LONGSHOT_MAX_AMERICAN}` : `Showing all odds`}</span>
            </button>
          </div>
        )}

        {/* Results List */}
        {scanData && (
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Showing {results.length} of {fullResults.length}{" "}
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
                    {activeLens === "standard"
                      ? "No +EV lines right now. Check back when lines move."
                      : activeLens === "bonus_bet"
                      ? "No bonus bet targets above 60% retention."
                      : "No profitable boost opportunities at this percentage."}
                  </p>
                </CardContent>
              </Card>
            ) : (
              <>
                {results.map((side, i) => {
                const metric = getMetric(side);
                const rawKellyStake = Math.max(
                  0,
                  side.base_kelly_fraction * kellyMultiplier * bankroll
                );
                const stealthKellyStake = calculateStealthStake(rawKellyStake);
                return (
                  <Card key={`${side.sportsbook}-${side.team}-${side.event}-${i}`} className="card-hover">
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        {/* Left: bet info */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={cn(
                              "text-[10px] font-bold uppercase tracking-wider text-white px-1.5 py-0.5 rounded",
                              bookColors[side.sportsbook] || "bg-foreground"
                            )}>
                              {bookAbbrev(side.sportsbook)}
                            </span>
                            <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                              {SPORT_KEY_TO_DISPLAY[side.sport] || side.sport}
                            </span>
                            <p className="font-semibold text-sm truncate">
                              {side.team}
                            </p>
                            <span className="text-xs text-muted-foreground">
                              ML
                            </span>
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5 truncate">
                            {side.event}
                          </p>
                          <div className="flex flex-col gap-1 mt-2 text-xs">
                            <div className="flex items-center gap-3">
                              <span className="font-mono font-medium">
                                {bookAbbrev(side.sportsbook)}:{" "}
                                <span className="text-foreground">
                                  {formatOdds(side.book_odds)}
                                </span>
                              </span>
                              <span className="font-mono text-muted-foreground">
                                Pin: {formatOdds(side.pinnacle_odds)}
                              </span>
                              {activeLens === "profit_boost" && (
                                <span className="font-mono text-[#C4A35A]">
                                  Boosted:{" "}
                                  {formatOdds(
                                    decimalToAmerican(
                                      boostedDecimalOdds(side, boostPercent)
                                    )
                                  )}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                              <span className="font-mono">
                                Fair:{" "}
                                {formatOdds(
                                  decimalToAmerican(1 / side.true_prob)
                                )}{" "}
                                ({(side.true_prob * 100).toFixed(1)}%)
                              </span>
                              <span>{formatGameTime(side.commence_time)}</span>
                            </div>
                          </div>
                        </div>

                        {/* Right: metric + action */}
                        <div className="flex flex-col items-end gap-2 shrink-0">
                          <div className="text-right">
                            <p
                              className={cn(
                                "font-mono font-bold text-lg leading-tight",
                                metric.positive
                                  ? "text-[#4A7C59]"
                                  : "text-foreground"
                              )}
                            >
                              {metric.value}
                            </p>
                            <p className="text-[10px] text-muted-foreground">
                              {metric.label}
                            </p>
                            {activeLens === "standard" && (
                              <p className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-1">
                                Rec Bet:{" "}
                                <span className="font-mono font-semibold text-foreground">
                                  {formatCurrency(stealthKellyStake)}
                                </span>
                                <span
                                  title={`Raw Kelly: ${formatCurrency(rawKellyStake)}`}
                                  className="inline-flex"
                                >
                                  <Info
                                    className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70"
                                    aria-label="Raw Kelly amount"
                                  />
                                </span>
                              </p>
                            )}
                          </div>
                          <button
                            type="button"
                            onClick={() => handleLogBet(side)}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-foreground text-background hover:opacity-90 transition-opacity"
                          >
                            Log Bet
                            <ChevronRight className="h-3 w-3" />
                          </button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
                })}
                {fullResults.length > results.length && (
                  <Button
                    type="button"
                    variant="secondary"
                    className="w-full"
                    onClick={() => setVisibleCount((c) => c + 10)}
                  >
                    Load more
                  </Button>
                )}
              </>
            )}
          </div>
        )}

        {/* Pre-scan empty state */}
        {!scanData && !isScanning && !scanError && (
          <div className="text-center py-12">
            <Radar className="h-12 w-12 mx-auto mb-3 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">
              Select your books and tap Full Scan
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Results are cached 5 minutes — only stale sports hit the API
            </p>
          </div>
        )}
      </div>

      <LogBetDrawer
        key={drawerKey}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        initialValues={drawerInitialValues}
      />
    </main>
  );
}
