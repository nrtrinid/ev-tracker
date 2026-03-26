"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Clock, Layers } from "lucide-react";

import { ScannerResultsPane } from "@/app/scanner/components/ScannerResultsPane";
import { ScannerScopeBar } from "@/app/scanner/components/ScannerScopeBar";
import { buildPickEmBoardCards } from "@/app/scanner/pickem-board";
import type { PickEmBoardCard } from "@/app/scanner/pickem-board";
import { rankScannerSidesByLens } from "@/app/scanner/scanner-lenses";
import {
  buildParlayCartLeg,
  buildParlayCartLegFromPickEmCard,
  buildScannerLogBetInitialValues,
} from "@/app/scanner/scanner-state-utils";
import { canAddScannerLensToParlayCart } from "@/app/scanner/scanner-ui-model";
import { classifyScannerNullState } from "@/lib/scanner-contract";
import { useBoard, useBalances, useSettings, queryKeys } from "@/lib/hooks";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useKellySettings } from "@/lib/kelly-context";
import { createClient } from "@/lib/supabase";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { cn } from "@/lib/utils";
import type { MarketSide, PlayerPropMarketSide, ScannerSurface, ScanResult, ScannedBetData } from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────────

type MarketsViewMode = "opportunities" | "browse" | "pickem";

// Pick'em is filtered out when surface === "straight_bets" in the render
const VIEW_MODES: { id: MarketsViewMode; label: string; description: string }[] = [
  { id: "opportunities", label: "Opportunities", description: "+EV lines ranked by edge" },
  { id: "browse", label: "Browse", description: "All loaded lines, ordered by game time" },
  { id: "pickem", label: "Pick'em", description: "PrizePicks consensus board" },
];

const PLAYER_PROP_BOOKS = ["Bovada", "BetOnline.ag", "DraftKings", "FanDuel", "BetMGM", "Caesars"];
const STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN Bet"];
const DEFAULT_PLAYER_PROP_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Bovada", "BetOnline.ag"];
const DEFAULT_STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel"];

const SPORT_KEY_TO_DISPLAY: Record<string, string> = {
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
};

const BOOK_COLORS: Record<string, string> = {
  Bovada: "bg-[#B85C38]",
  "BetOnline.ag": "bg-[#4A7C59]",
  DraftKings: "bg-draftkings",
  FanDuel: "bg-fanduel",
  BetMGM: "bg-betmgm",
  Caesars: "bg-caesars",
  "ESPN Bet": "bg-espnbet",
};

const SCANNER_BOOKS_STORAGE_KEY = "ev-tracker-scanner-books";

type StoredScannerBooks = {
  player_props?: unknown;
  straight_bets?: unknown;
};

function sanitizeStoredBooks(stored: unknown, allowed: readonly string[], fallback: string[]): string[] {
  if (!Array.isArray(stored)) return fallback;
  const allow = new Set(allowed);
  const next = stored.filter((b): b is string => typeof b === "string" && allow.has(b));
  return next.length > 0 ? next : fallback;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function minutesAgo(iso: string): number {
  const then = new Date(iso).getTime();
  return Math.max(0, Math.floor((Date.now() - then) / 60_000));
}

function formatBoardAge(minutes: number): string {
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h ago` : `${h}h ${m}m ago`;
}

type TotalsOffer = {
  sportsbook: string;
  total: number;
  over_odds: number;
  under_odds: number;
};

type GameContextGame = {
  event: string;
  commence_time: string;
  totals_offers: TotalsOffer[];
};

function parseGameContextGames(gameContext: unknown): GameContextGame[] {
  if (!gameContext || typeof gameContext !== "object") return [];
  const gc = gameContext as { games?: unknown };
  if (!Array.isArray(gc.games)) return [];

  const out: GameContextGame[] = [];
  for (const rawGame of gc.games) {
    if (!rawGame || typeof rawGame !== "object") continue;
    const g = rawGame as Partial<GameContextGame> & { totals_offers?: unknown };
    if (typeof g.event !== "string" || typeof g.commence_time !== "string") continue;
    if (!Array.isArray(g.totals_offers)) continue;
    const offers: TotalsOffer[] = [];
    for (const rawOffer of g.totals_offers) {
      if (!rawOffer || typeof rawOffer !== "object") continue;
      const o = rawOffer as Partial<TotalsOffer>;
      if (typeof o.sportsbook !== "string") continue;
      if (typeof o.total !== "number") continue;
      if (typeof o.over_odds !== "number") continue;
      if (typeof o.under_odds !== "number") continue;
      offers.push({ sportsbook: o.sportsbook, total: o.total, over_odds: o.over_odds, under_odds: o.under_odds });
    }
    if (offers.length === 0) continue;
    out.push({ event: g.event, commence_time: g.commence_time, totals_offers: offers });
  }

  return out;
}

const PHOENIX_TZ = "America/Phoenix";

function getTimeZoneOffsetMs(date: Date, timeZone: string): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const parts = dtf.formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value;
  const year = Number(get("year"));
  const month = Number(get("month"));
  const day = Number(get("day"));
  const hour = Number(get("hour"));
  const minute = Number(get("minute"));
  const second = Number(get("second"));
  const asUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  return asUtc - date.getTime();
}

function zonedTimeToUtcMs(
  year: number,
  month1: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string,
): number {
  // Initial UTC guess for the intended wall time, then correct by zone offset at that instant.
  const utcGuess = Date.UTC(year, month1 - 1, day, hour, minute, 0);
  const guessDate = new Date(utcGuess);
  const offset = getTimeZoneOffsetMs(guessDate, timeZone);
  return utcGuess - offset;
}

function getNextPhoenixDropUtcMs(now: Date): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: PHOENIX_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = dtf.formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value;
  const year = Number(get("year"));
  const month = Number(get("month"));
  const day = Number(get("day"));

  let dropUtc = zonedTimeToUtcMs(year, month, day, 15, 30, PHOENIX_TZ);
  if (now.getTime() >= dropUtc) dropUtc += 24 * 60 * 60 * 1000; // Phoenix does not observe DST
  return dropUtc;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function MarketsPage() {
  const queryClient = useQueryClient();
  const { data: board, isLoading: isBoardLoading, error: boardError } = useBoard();
  const { data: balances } = useBalances();
  useSettings(); // ensure settings are warmed in cache for LogBetDrawer

  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const { cart, addCartLeg } = useBettingPlatformStore();

  // ── UI state ─────────────────────────────────────────────────────────────
  const [surface, setSurface] = useState<ScannerSurface>("player_props");
  const [viewMode, setViewMode] = useState<MarketsViewMode>("opportunities");
  // promoMode: lens modifier within Opportunities — uses bonus_bet ranking instead of standard EV
  const [promoMode, setPromoMode] = useState(false);
  // Per-surface book selections — persisted in localStorage (see hydrate / persist effects below)
  const [selectedPropBooks, setSelectedPropBooks] = useState<string[]>(DEFAULT_PLAYER_PROP_BOOKS);
  const [selectedGameLineBooks, setSelectedGameLineBooks] = useState<string[]>(DEFAULT_STRAIGHT_BET_BOOKS);
  const [booksHydrated, setBooksHydrated] = useState(false);
  const selectedBooks = surface === "player_props" ? selectedPropBooks : selectedGameLineBooks;
  const setSelectedBooks = surface === "player_props" ? setSelectedPropBooks : setSelectedGameLineBooks;

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SCANNER_BOOKS_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as StoredScannerBooks;
        setSelectedPropBooks(
          sanitizeStoredBooks(parsed.player_props, PLAYER_PROP_BOOKS, DEFAULT_PLAYER_PROP_BOOKS),
        );
        setSelectedGameLineBooks(
          sanitizeStoredBooks(parsed.straight_bets, STRAIGHT_BET_BOOKS, DEFAULT_STRAIGHT_BET_BOOKS),
        );
      }
    } catch {
      // ignore malformed storage
    }
    setBooksHydrated(true);
  }, []);

  useEffect(() => {
    if (!booksHydrated) return;
    try {
      localStorage.setItem(
        SCANNER_BOOKS_STORAGE_KEY,
        JSON.stringify({ player_props: selectedPropBooks, straight_bets: selectedGameLineBooks }),
      );
    } catch {
      // ignore quota / private mode
    }
  }, [booksHydrated, selectedPropBooks, selectedGameLineBooks]);
  const [visibleCount, setVisibleCount] = useState(10);
  const [searchQuery, setSearchQuery] = useState("");

  // ── Board freshness: realtime invalidation ───────────────────────────────
  // Subscribe to Supabase realtime for canonical board changes (surface=board)
  useEffect(() => {
    const supabase = createClient();
    const channel = supabase
      .channel("markets-board-latest")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "global_scan_cache", filter: "surface=eq.board" },
        () => {
          queryClient.invalidateQueries({ queryKey: queryKeys.board });
        },
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [queryClient]);

  // Log drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerKey, setDrawerKey] = useState(0);
  const [drawerInitialValues, setDrawerInitialValues] = useState<ScannedBetData | undefined>();

  // Pick'em slip state
  const [pickEmSlipKeys, setPickEmSlipKeys] = useState<string[]>([]);

  // ── Derived values ────────────────────────────────────────────────────────
  const bankroll = useMemo(() => {
    if (useComputedBankroll) {
      if (!balances || balances.length === 0) return 0;
      return balances.reduce((sum, b) => sum + (b.balance || 0), 0);
    }
    return bankrollOverride;
  }, [useComputedBankroll, balances, bankrollOverride]);

  const boardMeta = board?.meta;
  const isEmptyBoard = !boardMeta || boardMeta.snapshot_id === "none";

  // Active scan data: canonical board scan for Player Props; Game Lines reads board.game_context instead.
  const activeScanData: ScanResult | null = (surface === "player_props" ? board?.player_props : board?.straight_bets) ?? null;
  const gameContextGames = useMemo(() => parseGameContextGames(board?.game_context), [board?.game_context]);

  const boardAgeMinutes = useMemo(() => {
    if (boardMeta?.scanned_at) return minutesAgo(boardMeta.scanned_at);
    return null;
  }, [boardMeta?.scanned_at]);

  const nextDropLabel = useMemo(() => {
    try {
      const nextDropUtcMs = getNextPhoenixDropUtcMs(new Date());
      const nextDropLocal = new Date(nextDropUtcMs);
      const localTime = nextDropLocal.toLocaleString(undefined, {
        weekday: "short",
        hour: "numeric",
        minute: "2-digit",
      });
      return `Next daily scan: ${localTime}`;
    } catch {
      return "Next daily scan: 3:30 PM";
    }
  }, []);

  const allSides = useMemo(() => activeScanData?.sides ?? [], [activeScanData]);

  // Lens: Browse bypasses ranking; promoMode applies bonus_bet ranking within Opportunities
  const activeLens = promoMode ? "bonus_bet" : "standard";

  const rankedSides = useMemo(() => {
    if (viewMode === "browse") {
      // Browse: all sides for selected books, ordered by game start
      return allSides
        .filter((s) => selectedBooks.includes(s.sportsbook))
        .sort((a, b) => {
          const ta = a.commence_time ? new Date(a.commence_time).getTime() : 0;
          const tb = b.commence_time ? new Date(b.commence_time).getTime() : 0;
          return ta - tb;
        });
    }
    return rankScannerSidesByLens({
      sides: allSides,
      selectedBooks,
      activeLens,
      boostPercent: 30,
    });
  }, [allSides, selectedBooks, viewMode, activeLens]);

  const filteredSides = useMemo(() => {
    if (!searchQuery.trim()) return rankedSides;
    const q = searchQuery.toLowerCase();
    return rankedSides.filter((s) => {
      const haystack = [
        s.event,
        s.sport,
        s.sportsbook,
        "player_name" in s ? (s as { player_name?: string }).player_name : "",
        "team" in s ? (s as { team?: string }).team : "",
        "opponent" in s ? (s as { opponent?: string }).opponent : "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [rankedSides, searchQuery]);

  // Pick'em cards are derived from PlayerPropMarketSide sides (not prizepicks_cards).
  // buildPickEmBoardCards groups by player/market/line across books to build consensus cards.
  const pickEmCards = useMemo(() => {
    const propSides = allSides.filter(
      (s): s is PlayerPropMarketSide => s.surface === "player_props",
    ) as Array<PlayerPropMarketSide & { _retention?: number; _boostedEV?: number }>;
    return buildPickEmBoardCards(propSides);
  }, [allSides]);

  const isPickEmView = viewMode === "pickem";
  // rawSourceCount: total sides before book/lens filtering (used for pregame-expiry detection)
  const rawSourceCount = isPickEmView ? pickEmCards.length : allSides.length;
  const sourceCount = isPickEmView ? pickEmCards.length : rankedSides.length;
  const filteredCount = isPickEmView ? pickEmCards.length : filteredSides.length;

  const nullState = useMemo(
    () => classifyScannerNullState({ sourceCount, filteredCount }),
    [sourceCount, filteredCount],
  );

  const results = useMemo(
    () => filteredSides.slice(0, visibleCount),
    [filteredSides, visibleCount],
  );
  const visiblePickEmCards = useMemo(
    () => pickEmCards.slice(0, visibleCount),
    [pickEmCards, visibleCount],
  );

  const canLoadMore = isPickEmView
    ? visiblePickEmCards.length < pickEmCards.length
    : results.length < filteredSides.length;

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleViewModeChange = (mode: MarketsViewMode) => {
    setViewMode(mode);
    setVisibleCount(10);
    setSearchQuery("");
    // Reset promo lens when leaving Opportunities
    if (mode !== "opportunities") setPromoMode(false);
    // Pick'em is only meaningful for player props — auto-switch surface
    if (mode === "pickem" && surface === "straight_bets") {
      setSurface("player_props");
    }
  };

  const handleSurfaceChange = (newSurface: ScannerSurface) => {
    setSurface(newSurface);
    setVisibleCount(10);
    setSearchQuery("");
    // Pick'em is props-only — exit it when switching to Game Lines
    if (newSurface === "straight_bets" && viewMode === "pickem") {
      setViewMode("opportunities");
    }
    // Reset promo lens on surface change
    setPromoMode(false);
  };

  const handleLogBet = (side: MarketSide) => {
    const betData = buildScannerLogBetInitialValues({
      side,
      activeLens,
      boostPercent: 30,
      sportDisplayMap: SPORT_KEY_TO_DISPLAY,
      kellyMultiplier,
      bankroll,
    });
    setDrawerInitialValues(betData);
    setDrawerKey(Date.now());
    setDrawerOpen(true);
  };

  const handleAddToCart = (side: MarketSide) => {
    if (!canAddScannerLensToParlayCart(activeLens)) {
      toast.error("Slip building is available from Opportunities and Browse lines.");
      return;
    }
    const result = addCartLeg(buildParlayCartLeg(side));
    if (!result.added) {
      const msg =
        result.reason === "sportsbook_mismatch"
          ? "All legs in a parlay slip must be from the same sportsbook."
          : result.reason === "slip_kind_mismatch"
            ? "Pick'em slips and priced parlay slips can't be mixed. Clear your slip to switch."
            : "That leg is already in your slip.";
      toast.error(msg);
      return;
    }
    toast.success(`Added to slip (${cart.length + 1} ${cart.length + 1 === 1 ? "leg" : "legs"})`);
  };

  const handleAddPickEmToSlip = (card: PickEmBoardCard) => {
    if (!canAddScannerLensToParlayCart(activeLens)) {
      toast.error("Slip building is available from Opportunities and Browse lines.");
      return;
    }
    const leg = buildParlayCartLegFromPickEmCard(card);
    if (!leg) {
      toast.error("Could not add this pick — missing best price for the consensus side.");
      return;
    }
    const result = addCartLeg(leg);
    if (!result.added) {
      const msg =
        result.reason === "sportsbook_mismatch"
          ? "All legs in a parlay slip must be from the same sportsbook."
          : result.reason === "slip_kind_mismatch"
            ? "Pick'em slips and priced parlay slips can't be mixed. Clear your slip to switch."
            : "That leg is already in your slip.";
      toast.error(msg);
      return;
    }
    setPickEmSlipKeys((prev) =>
      prev.includes(card.comparison_key) ? prev : [...prev, card.comparison_key],
    );
    const sideLabel = card.consensus_side === "over" ? "Over" : "Under";
    const pct = Math.round(
      (card.consensus_side === "over" ? card.consensus_over_prob : card.consensus_under_prob) * 100,
    );
    toast.success(`Added to slip (${cart.length + 1} ${cart.length + 1 === 1 ? "leg" : "legs"})`, {
      description: `${card.player_name} ${sideLabel} ${card.line_value} (${pct}%)`,
    });
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="container mx-auto max-w-2xl space-y-3 px-4 py-4">

      {/* ── Board header ─────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-col gap-0.5">
        <h1 className="text-base font-semibold text-foreground">Markets</h1>
        {isBoardLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading board…</p>
        ) : boardAgeMinutes !== null ? (
          <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <Clock className="h-3 w-3 shrink-0" />
            <span>
              Lines from {formatBoardAge(boardAgeMinutes)} • {nextDropLabel}
            </span>
          </p>
        ) : isEmptyBoard && !isBoardLoading ? (
          <p className="text-[11px] text-muted-foreground">
            No lines yet · drops daily ~3:30 PM AZ
          </p>
        ) : null}
      </div>

      {/* ── PRIMARY: Surface toggle (always visible) ─────────────── */}
      <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
        {(["player_props", "straight_bets"] as const).map((s) => (
          <button
            key={s}
            onClick={() => handleSurfaceChange(s)}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              surface === s
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {s === "player_props" ? "Player Props" : "Game Lines"}
          </button>
        ))}
      </div>

      {/* ── SECONDARY: View modes + contextual Promos lens ───────── */}
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 no-scrollbar">
        {VIEW_MODES
          .filter((mode) => mode.id !== "pickem" || surface === "player_props")
          .map((mode) => (
            <button
              key={mode.id}
              onClick={() => handleViewModeChange(mode.id)}
              className={cn(
                "shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                viewMode === mode.id
                  ? "border-primary/40 bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
              )}
            >
              {mode.label}
            </button>
          ))}
        {/* Promos: bonus-bet lens modifier, contextual to Opportunities */}
        {viewMode === "opportunities" && (
          <>
            <span className="self-center select-none px-0.5 text-border text-sm">·</span>
            <button
              onClick={() => setPromoMode((prev) => !prev)}
              className={cn(
                "shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                promoMode
                  ? "border-primary/40 bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
              )}
            >
              Promos
            </button>
          </>
        )}
      </div>

      {/* ── Book selector (hidden in Pick'em) ────────────────────── */}
      {viewMode !== "pickem" && (
        <ScannerScopeBar
          books={surface === "player_props" ? PLAYER_PROP_BOOKS : STRAIGHT_BET_BOOKS}
          selectedBooks={selectedBooks}
          onToggleBook={(book) =>
            setSelectedBooks((prev) =>
              prev.includes(book) ? prev.filter((b) => b !== book) : [...prev, book],
            )
          }
          bookColors={BOOK_COLORS}
        />
      )}

      {/* ── Search bar (only when scan data is available and not in Pick'em) ── */}
      {activeScanData !== null && !isPickEmView && (
        <input
          type="search"
          placeholder={
            surface === "player_props"
              ? "Search players, teams, events…"
              : "Search teams, events…"
          }
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        />
      )}

      {/* ── Board error ───────────────────────────────────────────── */}
      {boardError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs text-destructive">
          Failed to load board:{" "}
          {boardError instanceof Error ? boardError.message : "Unknown error"}
        </div>
      )}

      {/*
       * ── Content area: mutually exclusive three-way guard ────────────────
       *
       *  1. Empty board  — no snapshot at all AND no scoped data to fall back on
       *  2. Surface empty — board exists but this surface (props vs game lines) has no data
       *  3. Results pane  — activated whenever any scan data is present (scoped or canonical)
       *
       * This prevents: (a) empty state + cards showing simultaneously,
       *                (b) blank page when board exists but surface field is null.
       */}

      {/* 1. No board snapshot yet */}
      {!isBoardLoading && isEmptyBoard && !boardError && activeScanData === null && (
        <div className="rounded-lg border border-border bg-card px-4 py-10 text-center">
          <Layers className="mx-auto mb-3 h-8 w-8 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">No lines loaded yet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Lines are loaded once daily, around 3:30 PM Arizona time.
          </p>
        </div>
      )}

      {/* 2. Board exists but this surface has no data in today's snapshot */}
      {!isBoardLoading && !isEmptyBoard && !boardError && surface === "player_props" && activeScanData === null && (
        <div className="rounded-lg border border-border bg-card px-4 py-8 text-center">
          <p className="text-sm font-medium text-foreground">
            No {surface === "player_props" ? "Player Props" : "Game Lines"} in today&apos;s board
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Today&apos;s scan did not include this market. Check back after the next daily drop.
          </p>
        </div>
      )}

      {/* 3. Results pane — any scan data present (scoped overlay or canonical) */}
      {surface === "player_props" && activeScanData !== null && (
        <ScannerResultsPane
          surface={isPickEmView ? "player_props" : surface}
          playerPropsView={isPickEmView ? "pickem" : "sportsbooks"}
          activeLens={activeLens}
          results={results}
          pickemCards={isPickEmView ? visiblePickEmCards : []}
          sourceCount={sourceCount}
          rawSourceCount={rawSourceCount}
          filteredCount={filteredCount}
          nullState={nullState}
          activeResultFilterSummary=""
          kellyMultiplier={kellyMultiplier}
          bankroll={bankroll}
          boostPercent={30}
          addedPickEmComparisonKeys={pickEmSlipKeys}
          canLoadMore={canLoadMore}
          onLoadMore={() => setVisibleCount((v) => v + 10)}
          onLogBet={handleLogBet}
          onAddToCart={handleAddToCart}
          onStartPlaceFlow={handleLogBet}
          onAddPickEmToSlip={handleAddPickEmToSlip}
          bookColors={BOOK_COLORS}
          sportDisplayMap={SPORT_KEY_TO_DISPLAY}
        />
      )}

      {/* 3b. Game Lines — rendered from board.game_context (totals context) */}
      {surface === "straight_bets" && !isBoardLoading && !boardError && (
        <div className="space-y-2">
          {gameContextGames.length === 0 ? (
            <div className="rounded-lg border border-border bg-card px-4 py-8 text-center">
              <p className="text-sm font-medium text-foreground">No Game Lines in today&apos;s board</p>
              <p className="mt-1 text-xs text-muted-foreground">
                The daily drop did not include totals context yet. Check back after the next daily drop.
              </p>
            </div>
          ) : (
            gameContextGames
              .slice()
              .sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime())
              .map((game) => {
                const kickoff = game.commence_time ? new Date(game.commence_time) : null;
                const kickoffLabel = kickoff && !Number.isNaN(kickoff.getTime())
                  ? kickoff.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })
                  : "";

                const offersByBook = new Map(game.totals_offers.map((o) => [o.sportsbook, o] as const));
                const pinnacle = offersByBook.get("Pinnacle") ?? null;
                const visibleOffers = selectedGameLineBooks
                  .map((book) => offersByBook.get(book))
                  .filter((o): o is TotalsOffer => Boolean(o));

                const totalLabel = (o: TotalsOffer | null) =>
                  o ? `${o.total}` : (pinnacle ? `${pinnacle.total}` : "");

                return (
                  <div key={`${game.event}|${game.commence_time}`} className="rounded-lg border border-border bg-card px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">{game.event}</p>
                        {kickoffLabel ? (
                          <p className="mt-0.5 text-[11px] text-muted-foreground">{kickoffLabel}</p>
                        ) : null}
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[11px] text-muted-foreground">Total</p>
                        <p className="text-sm font-semibold text-foreground">{totalLabel(pinnacle)}</p>
                      </div>
                    </div>

                    <div className="mt-3 space-y-2">
                      {pinnacle ? (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">Pinnacle</span>
                          <span className="text-muted-foreground">O {pinnacle.over_odds} · U {pinnacle.under_odds}</span>
                        </div>
                      ) : null}

                      {visibleOffers.map((o) => (
                        <div key={o.sportsbook} className="flex items-center justify-between text-xs">
                          <span className="text-foreground">{o.sportsbook}</span>
                          <span className="text-muted-foreground">O {o.over_odds} · U {o.under_odds}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })
          )}
        </div>
      )}

      <LogBetDrawer
        key={drawerKey}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        initialValues={drawerInitialValues}
      />
    </div>
  );
}
