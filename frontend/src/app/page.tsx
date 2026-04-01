"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Clock, Gift, Layers, ShieldCheck, TrendingUp, Zap } from "lucide-react";

import { ScannerResultsPane } from "@/app/scanner/components/ScannerResultsPane";
import { StraightBetList } from "@/app/scanner/components/StraightBetList";
import type { PickEmBoardCard } from "@/app/scanner/pickem-board";
import { rankScannerSidesByLens, type RankedScannerSide } from "@/app/scanner/scanner-lenses";
import { getBoardPlayerPropDetail } from "@/lib/api";
import {
  buildParlayCartLeg,
  buildParlayCartLegFromPickEmCard,
  buildScannerLogBetInitialValues,
  parseScannerCustomBoostInput,
} from "@/app/scanner/scanner-state-utils";
import { canAddScannerLensToParlayCart } from "@/app/scanner/scanner-ui-model";
import { classifyScannerNullState } from "@/lib/scanner-contract";
import { useBoard, useBoardPromos, useBoardSurface, useBalances, useSettings, queryKeys, useInfiniteBoardPlayerPropsView } from "@/lib/hooks";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { useKellySettings } from "@/lib/kelly-context";
import { createClient } from "@/lib/supabase";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type {
  MarketSide,
  PlayerPropBoardItem,
  PlayerPropBoardPageResponse,
  PlayerPropBoardPickEmCard,
  PlayerPropMarketSide,
  ScanResult,
  ScannedBetData,
} from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────────

type MarketsViewMode = "opportunities" | "browse" | "pickem";
type BoardTimeFilter = "today" | "upcoming" | "all_games" | "today_closed";
type PrimaryMode = "player_props" | "straight_bets" | "promos";
type PromosSubmode = "all" | "boosts" | "bonus_bets" | "qualifiers";
type StraightBetMarketFilter = "all" | "h2h" | "spreads" | "totals";

// Pick'em is filtered out when surface === "straight_bets" in the render
const VIEW_MODES: { id: MarketsViewMode; label: string; description: string }[] = [
  { id: "opportunities", label: "Opportunities", description: "+EV lines ranked by edge" },
  { id: "browse", label: "Browse", description: "All loaded lines, ordered by game time" },
  { id: "pickem", label: "Pick'em", description: "PrizePicks consensus board" },
];

const PROMOS_SUBMODES: Array<{
  id: PromosSubmode;
  label: string;
  description: string;
  icon: typeof TrendingUp;
  activeBg: string;
  activeBorder: string;
  activeText: string;
  iconText: string;
}> = [
  {
    id: "all",
    label: "All",
    description: "All promo-ready lines",
    icon: TrendingUp,
    activeBg: "bg-[#F3F7F5] dark:bg-[#1A2A22]",
    activeBorder: "border-[#B7D1C2] dark:border-[#2F5D45]",
    activeText: "text-[#2E5D39] dark:text-[#9FD6B7]",
    iconText: "text-[#2E5D39] dark:text-[#9FD6B7]",
  },
  {
    id: "boosts",
    label: "Boosts",
    description: "Rank by boosted EV",
    icon: Zap,
    activeBg: "bg-[#FCF7EC] dark:bg-[#2B2417]",
    activeBorder: "border-[#E9D7B9] dark:border-[#6D5A2A]",
    activeText: "text-[#8B7A3E] dark:text-[#E5CF94]",
    iconText: "text-[#8B7A3E] dark:text-[#E5CF94]",
  },
  {
    id: "bonus_bets",
    label: "Bonus Bets",
    description: "Rank by retention",
    icon: Gift,
    activeBg: "bg-[#F4F7F5] dark:bg-[#182723]",
    activeBorder: "border-[#B7CFC2] dark:border-[#2E6A55]",
    activeText: "text-[#3B6C4C] dark:text-[#9FD3BE]",
    iconText: "text-[#3B6C4C] dark:text-[#9FD3BE]",
  },
  {
    id: "qualifiers",
    label: "Qualifiers",
    description: "Rank by lowest hold",
    icon: ShieldCheck,
    activeBg: "bg-[#FDF6F3] dark:bg-[#2A1D18]",
    activeBorder: "border-[#E9C7B9] dark:border-[#6E3A2A]",
    activeText: "text-[#8B3D20] dark:text-[#E2A58F]",
    iconText: "text-[#8B3D20] dark:text-[#E2A58F]",
  },
];

const PLAYER_PROP_BOOKS = ["Bovada", "BetOnline.ag", "DraftKings", "FanDuel", "BetMGM", "Caesars"];
const STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN Bet"];
const DEFAULT_PLAYER_PROP_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Bovada", "BetOnline.ag"];
const DEFAULT_STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel"];
const PLAYER_PROP_MARKET_OPTIONS = [
  "player_points",
  "player_rebounds",
  "player_assists",
  "player_points_rebounds_assists",
  "player_threes",
];
const PLAYER_PROP_PAGE_SIZE = 10;

const SPORT_KEY_TO_DISPLAY: Record<string, string> = {
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
  baseball_mlb: "MLB",
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
const MARKETS_BOOST_PERCENT_STORAGE_KEY = "ev-tracker-markets-boost-percent";
const BOOST_PRESETS = [25, 30, 50] as const;

type StoredScannerBooks = {
  player_props?: unknown;
  straight_bets?: unknown;
};

function buildPromoDedupeKey(side: MarketSide): string {
  // Promos merges `player_props` + `straight_bets`; this key attempts to identify the underlying selection.
  const playerName = side.surface === "player_props" ? side.player_name : "";
  const lineValue = side.surface === "player_props" ? side.line_value : null;
  const opponent = side.surface === "player_props" ? side.opponent ?? "" : "";
  const selectionSide = side.surface === "player_props" ? side.selection_side : "";
  return [
    side.surface,
    side.sportsbook,
    side.event_id ?? "",
    side.market_key ?? "",
    side.selection_key ?? "",
    side.team ?? "",
    playerName,
    lineValue == null ? "" : String(lineValue),
    side.commence_time,
    opponent,
    selectionSide,
  ].join("|");
}

function duplicateStatePriority(state: MarketSide["scanner_duplicate_state"]): number {
  if (state === "already_logged") return 3;
  if (state === "better_now") return 2;
  if (state === "logged_elsewhere") return 1;
  return 0;
}

function dedupePromoSidesByDuplicateState(sides: MarketSide[]): MarketSide[] {
  const byKey = new Map<string, MarketSide>();
  for (const side of sides) {
    const key = buildPromoDedupeKey(side);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, side);
      continue;
    }

    const incomingPriority = duplicateStatePriority(side.scanner_duplicate_state ?? "new");
    const existingPriority = duplicateStatePriority(existing.scanner_duplicate_state ?? "new");
    if (incomingPriority > existingPriority) {
      byKey.set(key, side);
    }
  }
  return Array.from(byKey.values());
}

function compareRankedSidesByLens(
  left: RankedScannerSide,
  right: RankedScannerSide,
  activeLens: "standard" | "profit_boost" | "bonus_bet" | "qualifier",
): number {
  if (activeLens === "profit_boost") {
    return (right._boostedEV ?? 0) - (left._boostedEV ?? 0);
  }
  if (activeLens === "bonus_bet") {
    return (right._retention ?? 0) - (left._retention ?? 0);
  }
  if (activeLens === "qualifier") {
    const holdDiff = (left._qualifierHold ?? Number.POSITIVE_INFINITY) - (right._qualifierHold ?? Number.POSITIVE_INFINITY);
    if (holdDiff !== 0) return holdDiff;
  }
  return (right.ev_percentage ?? 0) - (left.ev_percentage ?? 0);
}

function selectDiversePromoGameLineCandidates(
  sides: Array<RankedScannerSide>,
  maxItems: number,
): Array<RankedScannerSide> {
  const picked: RankedScannerSide[] = [];
  const seenBuckets = new Set<string>();

  for (const side of sides) {
    const bucket = `${side.sport}|${String(side.market_key ?? "").toLowerCase()}`;
    if (seenBuckets.has(bucket)) continue;
    seenBuckets.add(bucket);
    picked.push(side);
    if (picked.length >= maxItems) return picked;
  }

  for (const side of sides) {
    if (picked.includes(side)) continue;
    picked.push(side);
    if (picked.length >= maxItems) return picked;
  }

  return picked;
}

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

type H2HOffer = {
  sportsbook: string;
  home_odds: number;
  away_odds: number;
};

type SpreadOffer = {
  sportsbook: string;
  home_spread: number;
  away_spread: number;
  home_odds: number;
  away_odds: number;
};

type FeaturedLineGame = {
  event: string;
  event_short?: string;
  sport: string;
  commence_time: string;
  h2h_offers: H2HOffer[];
  spreads_offers: SpreadOffer[];
  totals_offers: TotalsOffer[];
};

type FeaturedSportBucket = {
  sport: string;
  games: FeaturedLineGame[];
};

function matchesBoardTimeFilter(commenceTime: string, filter: BoardTimeFilter, now: Date = new Date()): boolean {
  const start = new Date(commenceTime);
  if (Number.isNaN(start.getTime())) return false;
  if (filter === "all_games") return true;
  if (filter === "upcoming") return start.getTime() >= now.getTime();
  if (filter === "today") {
    return (
      start.getFullYear() === now.getFullYear() &&
      start.getMonth() === now.getMonth() &&
      start.getDate() === now.getDate() &&
      start.getTime() >= now.getTime()
    );
  }
  return (
    start.getFullYear() === now.getFullYear() &&
    start.getMonth() === now.getMonth() &&
    start.getDate() === now.getDate() &&
    start.getTime() < now.getTime()
  );
}

function sameStringSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const left = [...a].sort();
  const right = [...b].sort();
  return left.every((value, index) => value === right[index]);
}

function formatMarketTypeLabel(market: string): string {
  const normalized = market.startsWith("player_") ? market.slice("player_".length) : market;
  const labels: Record<string, string> = {
    points: "Points",
    rebounds: "Rebounds",
    assists: "Assists",
    points_rebounds_assists: "PRA",
    threes: "Threes",
  };
  return labels[normalized] ?? normalized.replaceAll("_", " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function parseFeaturedLines(gameContext: unknown): FeaturedSportBucket[] {
  if (!gameContext || typeof gameContext !== "object") return [];
  const gc = gameContext as { featured_lines?: unknown };
  if (!gc.featured_lines || typeof gc.featured_lines !== "object") return [];

  const buckets: FeaturedSportBucket[] = [];
  for (const [sport, rawGames] of Object.entries(gc.featured_lines as Record<string, unknown>)) {
    if (!Array.isArray(rawGames)) continue;
    const games: FeaturedLineGame[] = [];
    for (const rawGame of rawGames) {
      if (!rawGame || typeof rawGame !== "object") continue;
      const g = rawGame as Partial<FeaturedLineGame>;
      if (typeof g.event !== "string" || typeof g.commence_time !== "string") continue;
      const h2h = Array.isArray(g.h2h_offers) ? g.h2h_offers.filter((o) => o && typeof o.sportsbook === "string") : [];
      const spreads = Array.isArray(g.spreads_offers) ? g.spreads_offers.filter((o) => o && typeof o.sportsbook === "string") : [];
      const totals = Array.isArray(g.totals_offers) ? g.totals_offers.filter((o) => o && typeof o.sportsbook === "string") : [];
      if (h2h.length === 0 && spreads.length === 0 && totals.length === 0) continue;
      games.push({
        event: g.event,
        event_short: typeof g.event_short === "string" ? g.event_short : undefined,
        sport,
        commence_time: g.commence_time,
        h2h_offers: h2h as FeaturedLineGame["h2h_offers"],
        spreads_offers: spreads as FeaturedLineGame["spreads_offers"],
        totals_offers: totals as FeaturedLineGame["totals_offers"],
      });
    }
    if (games.length > 0) buckets.push({ sport, games });
  }
  return buckets;
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

  const dailyWindows: Array<{ hour: number; minute: number }> = [
    { hour: 10, minute: 30 },
    { hour: 15, minute: 30 },
  ];
  const todaysDropsUtc = dailyWindows.map(({ hour, minute }) =>
    zonedTimeToUtcMs(year, month, day, hour, minute, PHOENIX_TZ),
  );
  const nextToday = todaysDropsUtc.find((dropUtc) => now.getTime() < dropUtc);
  if (typeof nextToday === "number") return nextToday;
  return todaysDropsUtc[0] + 24 * 60 * 60 * 1000; // Phoenix does not observe DST
}

function MarketsPaneSkeleton(props: {
  label: string;
  variant?: "list" | "pickem" | "gamelines";
}) {
  const { label, variant = "list" } = props;
  const rowCount = variant === "gamelines" ? 3 : 4;

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <div className="space-y-2">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-3 w-44" />
        </div>
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>

      <div className="mt-4 space-y-3">
        {Array.from({ length: rowCount }).map((_, index) => (
          <div key={`${label}-${index}`} className="rounded-lg border border-border/70 px-3 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-3 w-28" />
              </div>
              <div className="w-20 space-y-2">
                <Skeleton className="ml-auto h-4 w-10" />
                <Skeleton className="ml-auto h-5 w-14" />
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Skeleton className="h-5 w-16 rounded-full" />
              <Skeleton className="h-5 w-20 rounded-full" />
              <Skeleton className="h-5 w-14 rounded-full" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
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
  const [primaryMode, setPrimaryMode] = useState<PrimaryMode>("player_props");
  const [viewMode, setViewMode] = useState<MarketsViewMode>("opportunities");
  const [promosSubmode, setPromosSubmode] = useState<PromosSubmode>("all");

  // Per-surface book selections — persisted in localStorage (see hydrate / persist effects below)
  const [selectedPropBooks, setSelectedPropBooks] = useState<string[]>(DEFAULT_PLAYER_PROP_BOOKS);
  const [selectedGameLineBooks, setSelectedGameLineBooks] = useState<string[]>(DEFAULT_STRAIGHT_BET_BOOKS);
  const [booksHydrated, setBooksHydrated] = useState(false);
  const [visibleCount, setVisibleCount] = useState(10);
  const [searchQuery, setSearchQuery] = useState("");
  const [showMoreFeaturedLines, setShowMoreFeaturedLines] = useState(false);
  const [timeFilter, setTimeFilter] = useState<BoardTimeFilter>("today");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [propMarketFilter, setPropMarketFilter] = useState<string>("all");
  const [propSideFilter, setPropSideFilter] = useState<"all" | "over" | "under">("all");
  const [straightBetMarketFilter, setStraightBetMarketFilter] =
    useState<StraightBetMarketFilter>("all");
  const [boostPercent, setBoostPercent] = useState(30);
  const [customBoostInput, setCustomBoostInput] = useState("");
  const [boostSheetOpen, setBoostSheetOpen] = useState(false);
  const [boostHydrated, setBoostHydrated] = useState(false);
  const deferredPlayerPropsSearchQuery = useDeferredValue(searchQuery);
  const [playerPropsQueryFilters, setPlayerPropsQueryFilters] = useState<{
    books: string[];
    timeFilter: BoardTimeFilter;
    market: string;
    search: string;
  }>(() => ({
    books: [...DEFAULT_PLAYER_PROP_BOOKS].sort(),
    timeFilter: "today",
    market: "all",
    search: "",
  }));

  const selectedBooks = primaryMode === "straight_bets" ? selectedGameLineBooks : selectedPropBooks;
  const setSelectedBooks = primaryMode === "straight_bets" ? setSelectedGameLineBooks : setSelectedPropBooks;
  const tzOffsetMinutes = useMemo(() => new Date().getTimezoneOffset(), []);
  const appliedPlayerPropsBooks = playerPropsQueryFilters.books;
  const appliedPlayerPropsTimeFilter = playerPropsQueryFilters.timeFilter;
  const appliedPlayerPropsMarketFilter = playerPropsQueryFilters.market;
  const appliedPlayerPropsSearchQuery = playerPropsQueryFilters.search;

  const straightSurface = useBoardSurface(
    "straight_bets",
    primaryMode === "straight_bets",
  );
  const playerPropsOpportunities = useInfiniteBoardPlayerPropsView({
    view: "opportunities",
    pageSize: PLAYER_PROP_PAGE_SIZE,
    books: appliedPlayerPropsBooks,
    timeFilter: appliedPlayerPropsTimeFilter,
    market: appliedPlayerPropsMarketFilter,
    search: appliedPlayerPropsSearchQuery,
    tzOffsetMinutes,
    enabled: primaryMode === "player_props" && viewMode === "opportunities",
  });
  const playerPropsBrowse = useInfiniteBoardPlayerPropsView({
    view: "browse",
    pageSize: PLAYER_PROP_PAGE_SIZE,
    books: appliedPlayerPropsBooks,
    timeFilter: appliedPlayerPropsTimeFilter,
    market: appliedPlayerPropsMarketFilter,
    search: appliedPlayerPropsSearchQuery,
    tzOffsetMinutes,
    enabled: primaryMode === "player_props" && viewMode === "browse",
  });
  const playerPropsPickem = useInfiniteBoardPlayerPropsView({
    view: "pickem",
    pageSize: PLAYER_PROP_PAGE_SIZE,
    books: appliedPlayerPropsBooks,
    timeFilter: appliedPlayerPropsTimeFilter,
    market: appliedPlayerPropsMarketFilter,
    search: appliedPlayerPropsSearchQuery,
    tzOffsetMinutes,
    enabled: primaryMode === "player_props" && viewMode === "pickem",
  });
  const boardPromos = useBoardPromos(visibleCount * 3, primaryMode === "promos");

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

  useEffect(() => {
    try {
      const raw = localStorage.getItem(MARKETS_BOOST_PERCENT_STORAGE_KEY);
      if (raw) {
        const n = Number(raw);
        if (Number.isFinite(n) && n >= 1 && n <= 200) {
          setBoostPercent(Math.round(n));
        }
      }
    } catch {
      // ignore
    }
    setBoostHydrated(true);
  }, []);

  useEffect(() => {
    if (!boostHydrated) return;
    try {
      localStorage.setItem(MARKETS_BOOST_PERCENT_STORAGE_KEY, String(boostPercent));
    } catch {
      // ignore
    }
  }, [boostHydrated, boostPercent]);

  useEffect(() => {
    if (!boostHydrated) return;
    setVisibleCount(10);
  }, [boostPercent, boostHydrated]);

  useEffect(() => {
    const nextFilters = {
      books: [...selectedPropBooks].sort(),
      timeFilter,
      market: propMarketFilter,
      search: deferredPlayerPropsSearchQuery.trim(),
    };
    const handle = window.setTimeout(() => {
      setPlayerPropsQueryFilters((current) => {
        if (
          sameStringSet(current.books, nextFilters.books) &&
          current.timeFilter === nextFilters.timeFilter &&
          current.market === nextFilters.market &&
          current.search === nextFilters.search
        ) {
          return current;
        }
        return nextFilters;
      });
    }, 250);
    return () => window.clearTimeout(handle);
  }, [selectedPropBooks, timeFilter, propMarketFilter, deferredPlayerPropsSearchQuery]);

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
          queryClient.invalidateQueries({ queryKey: queryKeys.boardSurface("straight_bets") });
          queryClient.invalidateQueries({ queryKey: ["board_player_props"] });
          queryClient.invalidateQueries({ queryKey: ["board_promos"] });
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

  const activePlayerPropsListPage = useMemo(() => {
    const data = viewMode === "browse" ? playerPropsBrowse.data : playerPropsOpportunities.data;
    if (viewMode === "pickem" || !data?.pages?.length) return null;
    const pages = data.pages.filter(Boolean) as PlayerPropBoardPageResponse<PlayerPropBoardItem>[];
    const lastPage = pages[pages.length - 1];
    if (!lastPage) return null;
    return {
      items: pages.flatMap((page) => page?.items ?? []) as PlayerPropBoardItem[],
      total: lastPage.total,
      source_total: lastPage.source_total,
      has_more: lastPage.has_more,
      scanned_at: lastPage.scanned_at,
      available_markets: lastPage.available_markets,
    };
  }, [playerPropsBrowse.data, playerPropsOpportunities.data, viewMode]);

  const activePlayerPropsPickemPage = useMemo(() => {
    if (viewMode !== "pickem" || !playerPropsPickem.data?.pages?.length) return null;
    const pages = playerPropsPickem.data.pages.filter(Boolean) as PlayerPropBoardPageResponse<PlayerPropBoardPickEmCard>[];
    const lastPage = pages[pages.length - 1];
    if (!lastPage) return null;
    return {
      items: pages.flatMap((page) => page?.items ?? []) as PlayerPropBoardPickEmCard[],
      total: lastPage.total,
      source_total: lastPage.source_total,
      has_more: lastPage.has_more,
      scanned_at: lastPage.scanned_at,
      available_markets: lastPage.available_markets,
    };
  }, [playerPropsPickem.data, viewMode]);

  const activePlayerPropsIsFetchingNextPage = useMemo(() => {
    if (viewMode === "browse") {
      return playerPropsBrowse.isFetchingNextPage;
    }
    if (viewMode === "pickem") return playerPropsPickem.isFetchingNextPage;
    return playerPropsOpportunities.isFetchingNextPage;
  }, [playerPropsBrowse.isFetchingNextPage, playerPropsOpportunities.isFetchingNextPage, playerPropsPickem.isFetchingNextPage, viewMode]);

  const activePlayerPropsError = useMemo(() => {
    if (viewMode === "browse") return playerPropsBrowse.error;
    if (viewMode === "pickem") return playerPropsPickem.error;
    return playerPropsOpportunities.error;
  }, [playerPropsBrowse.error, playerPropsOpportunities.error, playerPropsPickem.error, viewMode]);

  const activeScanData: ScanResult | null = useMemo(() => {
    if (primaryMode === "player_props") {
      if (viewMode === "pickem") {
        const pickemPage = activePlayerPropsPickemPage;
        if (!pickemPage) return null;
        return {
          surface: "player_props",
          sport: "basketball_nba",
          sides: [],
          events_fetched: 0,
          events_with_both_books: 0,
          api_requests_remaining: null,
          scanned_at: pickemPage.scanned_at ?? boardMeta?.scanned_at ?? null,
        };
      }
      const listPage = activePlayerPropsListPage;
      if (!listPage) return null;
      return {
        surface: "player_props",
        sport: "basketball_nba",
        sides: listPage.items as MarketSide[],
        events_fetched: 0,
        events_with_both_books: 0,
        api_requests_remaining: null,
        scanned_at: listPage.scanned_at ?? boardMeta?.scanned_at ?? null,
      };
    }

    if (primaryMode === "straight_bets") {
      return straightSurface.data ?? null;
    }

    if (!boardPromos.data) return null;
    return {
      surface: "straight_bets",
      sport: "all",
      sides: boardPromos.data.sides,
      events_fetched: 0,
      events_with_both_books: 0,
      api_requests_remaining: null,
      scanned_at: boardPromos.data.meta?.scanned_at ?? boardMeta?.scanned_at ?? null,
    };
  }, [
    activePlayerPropsListPage,
    activePlayerPropsPickemPage,
    boardMeta?.scanned_at,
    boardPromos.data,
    primaryMode,
    straightSurface.data,
    viewMode,
  ]);
  const activeSurfaceError = useMemo(() => {
    if (primaryMode === "player_props") {
      return activePlayerPropsError;
    }
    if (primaryMode === "promos") {
      return boardPromos.error;
    }
    if (primaryMode === "straight_bets") {
      return straightSurface.error;
    }
    return null;
  }, [activePlayerPropsError, boardPromos.error, primaryMode, straightSurface.error]);
  const activeSurfaceIsLoading = useMemo(() => {
    if (primaryMode === "player_props") {
      if (viewMode === "pickem") {
        return playerPropsPickem.isLoading || (playerPropsPickem.isFetching && !activePlayerPropsPickemPage);
      }
      if (viewMode === "browse") {
        return playerPropsBrowse.isLoading || (playerPropsBrowse.isFetching && !activePlayerPropsListPage);
      }
      return playerPropsOpportunities.isLoading || (playerPropsOpportunities.isFetching && !activePlayerPropsListPage);
    }
    if (primaryMode === "promos") {
      return boardPromos.isLoading || (boardPromos.isFetching && !boardPromos.data);
    }
    return straightSurface.isLoading || (straightSurface.isFetching && !straightSurface.data);
  }, [
    activePlayerPropsListPage,
    activePlayerPropsPickemPage,
    boardPromos.data,
    boardPromos.isFetching,
    boardPromos.isLoading,
    playerPropsBrowse.isFetching,
    playerPropsBrowse.isLoading,
    playerPropsOpportunities.isFetching,
    playerPropsOpportunities.isLoading,
    playerPropsPickem.isFetching,
    playerPropsPickem.isLoading,
    primaryMode,
    straightSurface.data,
    straightSurface.isFetching,
    straightSurface.isLoading,
    viewMode,
  ]);
  const activeContentIsLoading = !boardError && activeScanData === null && (isBoardLoading || activeSurfaceIsLoading);
  const featuredLineBuckets = useMemo(() => parseFeaturedLines(board?.game_context), [board?.game_context]);

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
      return `Next scan: ${localTime}`;
    } catch {
      return "Next scan: 10:30 AM / 3:30 PM";
    }
  }, []);

  const scanWindowLabel = useMemo(() => {
    const gc = board?.game_context as Record<string, unknown> | undefined;
    const scanLabel = typeof gc?.scan_label === "string" ? gc.scan_label : null;
    const mstAnchor = typeof gc?.scan_anchor_time_mst === "string" ? gc.scan_anchor_time_mst : null;
    if (!scanLabel || !mstAnchor) return null;
    const [hourRaw, minuteRaw] = mstAnchor.split(":");
    const hour = Number(hourRaw);
    const minute = Number(minuteRaw);
    if (!Number.isFinite(hour) || !Number.isFinite(minute)) return scanLabel;

    const now = new Date();
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: PHOENIX_TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    const parts = fmt.formatToParts(now);
    const get = (type: string) => parts.find((p) => p.type === type)?.value;
    const y = Number(get("year"));
    const m = Number(get("month"));
    const d = Number(get("day"));
    const utcMs = zonedTimeToUtcMs(y, m, d, hour, minute, PHOENIX_TZ);
    const local = new Date(utcMs).toLocaleString(undefined, { hour: "numeric", minute: "2-digit" });
    return `${scanLabel} • ${local} local`;
  }, [board?.game_context]);

  const featuredGames = useMemo(() => {
    const perSportCap = showMoreFeaturedLines ? 4 : 2;
    const globalCap = showMoreFeaturedLines ? 12 : 6;
    const flat: FeaturedLineGame[] = [];
    for (const bucket of featuredLineBuckets) {
      const sorted = bucket.games
        .slice()
        .filter((g) => matchesBoardTimeFilter(g.commence_time, timeFilter))
        .sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime());
      flat.push(...sorted.slice(0, perSportCap));
    }
    return flat
      .sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime())
      .slice(0, globalCap);
  }, [featuredLineBuckets, showMoreFeaturedLines, timeFilter]);

  const allSides = useMemo(() => {
    if (primaryMode === "player_props") {
      return (activePlayerPropsListPage?.items as MarketSide[]) ?? [];
    }
    return activeScanData?.sides ?? [];
  }, [activePlayerPropsListPage?.items, activeScanData, primaryMode]);

  const activeLens = useMemo(() => {
    if (primaryMode !== "promos") return "standard";
    if (promosSubmode === "boosts") return "profit_boost";
    if (promosSubmode === "bonus_bets") return "bonus_bet";
    if (promosSubmode === "qualifiers") return "qualifier";
    return "standard";
  }, [primaryMode, promosSubmode]);

  const rankedSides = useMemo(() => {
    if (primaryMode === "player_props") {
      return ((activePlayerPropsListPage?.items as MarketSide[]) ?? []);
    }
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

    const sidesForRanking = primaryMode === "promos" ? dedupePromoSidesByDuplicateState(allSides) : allSides;
    if (primaryMode === "promos") {
      const promoProps = rankScannerSidesByLens({
        sides: sidesForRanking.filter((side) => side.surface === "player_props"),
        selectedBooks: selectedPropBooks,
        activeLens,
        boostPercent,
      });
      const promoStraight = rankScannerSidesByLens({
        sides: sidesForRanking.filter((side) => side.surface !== "player_props"),
        selectedBooks: selectedGameLineBooks,
        activeLens,
        boostPercent,
      });
      const ranked = [...promoProps, ...promoStraight].sort((left, right) => compareRankedSidesByLens(left, right, activeLens));
      if (activeLens === "standard") {
        return ranked.filter((s) => Number(s.ev_percentage || 0) > 1);
      }
      return ranked;
    }

    const ranked = rankScannerSidesByLens({
      sides: sidesForRanking,
      selectedBooks,
      activeLens,
      boostPercent,
    });
    // Opportunities view guardrail: keep board quality high by hiding very small edges.
    // This is display-only and does not alter backend scan/research capture.
    if (activeLens === "standard") {
      return ranked.filter((s) => Number(s.ev_percentage || 0) > 1);
    }
    return ranked;
  }, [
    activePlayerPropsListPage?.items,
    allSides,
    selectedBooks,
    selectedPropBooks,
    selectedGameLineBooks,
    viewMode,
    activeLens,
    primaryMode,
    boostPercent,
  ]);

  const filteredSides = useMemo(() => {
    if (primaryMode === "player_props") {
      return ((activePlayerPropsListPage?.items as MarketSide[]) ?? []);
    }
    const timeFiltered = rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, timeFilter));
    const marketFiltered =
      primaryMode === "straight_bets" && straightBetMarketFilter !== "all"
        ? timeFiltered.filter((s) => String(s.market_key ?? "").toLowerCase() === straightBetMarketFilter)
        : timeFiltered;
    if (!searchQuery.trim()) return marketFiltered;
    const q = searchQuery.toLowerCase();
    return marketFiltered.filter((s) => {
      const haystack = [
        s.event,
        s.event_short ?? "",
        s.sport,
        s.sportsbook,
        "player_name" in s ? (s as { player_name?: string }).player_name : "",
        String(s.market_key ?? ""),
        "team" in s ? (s as { team?: string }).team : "",
        "team_short" in s ? (s as { team_short?: string }).team_short : "",
        "opponent" in s ? (s as { opponent?: string }).opponent : "",
        "opponent_short" in s ? (s as { opponent_short?: string }).opponent_short : "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [activePlayerPropsListPage?.items, rankedSides, searchQuery, straightBetMarketFilter, timeFilter, primaryMode]);
  const promoGameLineResults = useMemo(() => {
    if (primaryMode !== "promos") return [];
    return selectDiversePromoGameLineCandidates(
      filteredSides.filter((side): side is RankedScannerSide => side.surface === "straight_bets"),
      6,
    );
  }, [filteredSides, primaryMode]);

  const todayOpenCount = useMemo(
    () => (primaryMode === "player_props" ? 0 : rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, "today")).length),
    [primaryMode, rankedSides],
  );
  const todayClosedCount = useMemo(
    () => (primaryMode === "player_props" ? 0 : rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, "today_closed")).length),
    [primaryMode, rankedSides],
  );

  const filteredFeaturedGames = useMemo(() => {
    return featuredGames.filter((game) => {
      if (straightBetMarketFilter === "h2h") return game.h2h_offers.length > 0;
      if (straightBetMarketFilter === "spreads") return game.spreads_offers.length > 0;
      if (straightBetMarketFilter === "totals") return game.totals_offers.length > 0;
      return game.h2h_offers.length > 0 || game.spreads_offers.length > 0 || game.totals_offers.length > 0;
    });
  }, [featuredGames, straightBetMarketFilter]);
  const gameTodayOpenCount = useMemo(
    () => featuredLineBuckets.flatMap((bucket) => bucket.games).filter((g) => matchesBoardTimeFilter(g.commence_time, "today")).length,
    [featuredLineBuckets],
  );
  const gameTodayClosedCount = useMemo(
    () => featuredLineBuckets.flatMap((bucket) => bucket.games).filter((g) => matchesBoardTimeFilter(g.commence_time, "today_closed")).length,
    [featuredLineBuckets],
  );

  const pickEmCards = useMemo(() => {
    if (primaryMode === "player_props") {
      return (activePlayerPropsPickemPage?.items ?? []) as PickEmBoardCard[];
    }
    return [];
  }, [activePlayerPropsPickemPage?.items, primaryMode]);
  const filteredPickEmCards = useMemo(
    () =>
      pickEmCards.filter((card) => {
        if (primaryMode !== "player_props") return false;
        if (propSideFilter !== "all" && card.consensus_side !== propSideFilter) return false;
        return true;
      }),
    [pickEmCards, primaryMode, propSideFilter],
  );
  const availablePropMarkets = useMemo(() => {
    if (primaryMode === "player_props") {
      const markets = activePlayerPropsListPage?.available_markets ?? activePlayerPropsPickemPage?.available_markets;
      if (Array.isArray(markets) && markets.length > 0) {
        return markets;
      }
    }
    const markets = new Set<string>();
    for (const market of PLAYER_PROP_MARKET_OPTIONS) {
      markets.add(market);
    }
    for (const side of allSides) {
      if (side.surface === "player_props") markets.add((side as PlayerPropMarketSide).market_key);
    }
    return Array.from(markets).sort();
  }, [activePlayerPropsListPage?.available_markets, activePlayerPropsPickemPage?.available_markets, allSides, primaryMode]);
  const isPickEmView = primaryMode === "player_props" && viewMode === "pickem";
  const activeFilterChips = useMemo(() => {
    const chips: string[] = [];
    const activeTimeFilter = primaryMode === "player_props" ? appliedPlayerPropsTimeFilter : timeFilter;
    const activeMarketFilter = primaryMode === "player_props" ? appliedPlayerPropsMarketFilter : propMarketFilter;
    const activeSearchValue = primaryMode === "player_props" ? appliedPlayerPropsSearchQuery : searchQuery.trim();
    const activeBooks = primaryMode === "player_props" ? appliedPlayerPropsBooks : selectedBooks;
    if (activeTimeFilter !== "today") {
      const label =
        activeTimeFilter === "upcoming"
          ? "Upcoming"
          : activeTimeFilter === "all_games"
            ? "All Games"
            : "Closed Today";
      chips.push(`Time: ${label}`);
    }
    const defaultBooks = primaryMode === "straight_bets" ? DEFAULT_STRAIGHT_BET_BOOKS : DEFAULT_PLAYER_PROP_BOOKS;
    if (!sameStringSet(activeBooks, defaultBooks)) {
      chips.push(`Books: ${activeBooks.length}`);
    }
    if (primaryMode === "player_props" && activeMarketFilter !== "all") {
      chips.push(`Market: ${activeMarketFilter.replaceAll("_", " ")}`);
    }
    if (primaryMode === "straight_bets" && straightBetMarketFilter !== "all") {
      const label =
        straightBetMarketFilter === "h2h"
          ? "Moneyline"
          : straightBetMarketFilter === "spreads"
            ? "Spreads"
            : "Totals";
      chips.push(`Market: ${label}`);
    }
    if (isPickEmView && propSideFilter !== "all") {
      chips.push(`Side: ${propSideFilter}`);
    }
    if (activeSearchValue) {
      chips.push(`Search: ${activeSearchValue}`);
    }
    return chips;
  }, [
    appliedPlayerPropsBooks,
    appliedPlayerPropsMarketFilter,
    appliedPlayerPropsSearchQuery,
    appliedPlayerPropsTimeFilter,
    isPickEmView,
    primaryMode,
    propMarketFilter,
    propSideFilter,
    searchQuery,
    selectedBooks,
    straightBetMarketFilter,
    timeFilter,
  ]);

  const resetFilters = () => {
    setTimeFilter("today");
    setPropMarketFilter("all");
    setPropSideFilter("all");
    setStraightBetMarketFilter("all");
    setSearchQuery("");
    if (primaryMode === "straight_bets") {
      setSelectedGameLineBooks(DEFAULT_STRAIGHT_BET_BOOKS);
    } else {
      setSelectedPropBooks(DEFAULT_PLAYER_PROP_BOOKS);
    }
  };

  useEffect(() => {
    if (!isPickEmView && propSideFilter !== "all") {
      setPropSideFilter("all");
    }
  }, [isPickEmView, propSideFilter]);
  // rawSourceCount: keep aligned with ranked/source set so empty-state copy does not
  // misclassify "no opportunities" as "not pregame".
  const rawSourceCount = isPickEmView
    ? (activePlayerPropsPickemPage?.source_total ?? filteredPickEmCards.length)
    : primaryMode === "player_props"
      ? (activePlayerPropsListPage?.source_total ?? filteredSides.length)
      : rankedSides.length;
  const sourceCount = rawSourceCount;
  const filteredCount = isPickEmView
    ? (activePlayerPropsPickemPage?.total ?? filteredPickEmCards.length)
    : primaryMode === "player_props"
      ? (activePlayerPropsListPage?.total ?? filteredSides.length)
      : filteredSides.length;

  const nullState = useMemo(
    () => classifyScannerNullState({ sourceCount, filteredCount }),
    [sourceCount, filteredCount],
  );

  const results = useMemo(() => {
    if (primaryMode === "player_props") {
      return filteredSides;
    }
    return filteredSides.slice(0, visibleCount);
  }, [filteredSides, primaryMode, visibleCount]);
  const visiblePickEmCards = useMemo(
    () => (primaryMode === "player_props" ? filteredPickEmCards : filteredPickEmCards.slice(0, visibleCount)),
    [filteredPickEmCards, primaryMode, visibleCount],
  );

  const canLoadMore = isPickEmView
    ? (playerPropsPickem.hasNextPage ?? false)
    : primaryMode === "player_props"
      ? (viewMode === "browse" ? (playerPropsBrowse.hasNextPage ?? false) : (playerPropsOpportunities.hasNextPage ?? false))
      : results.length < filteredSides.length;
  const isLoadingMore = primaryMode === "player_props" ? activePlayerPropsIsFetchingNextPage : false;

  const handleLoadMore = () => {
    if (primaryMode === "player_props") {
      if (viewMode === "pickem") {
        void playerPropsPickem.fetchNextPage();
        return;
      }
      if (viewMode === "browse") {
        void playerPropsBrowse.fetchNextPage();
        return;
      }
      void playerPropsOpportunities.fetchNextPage();
      return;
    }
    setVisibleCount((v) => v + 10);
  };

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleViewModeChange = (mode: MarketsViewMode) => {
    setViewMode(mode);
    setVisibleCount(10);
    setSearchQuery("");
    if (mode === "opportunities" && timeFilter === "all_games") {
      setTimeFilter("today");
    }
    // Pick'em is only meaningful for player props — auto-switch surface
    if (mode === "pickem" && primaryMode === "straight_bets") {
      setPrimaryMode("player_props");
    }
  };

  const handleSurfaceModeChange = (newSurface: Exclude<PrimaryMode, "promos">) => {
    setPrimaryMode(newSurface);
    setVisibleCount(10);
    setSearchQuery("");
    if (newSurface === "straight_bets" && viewMode === "pickem") {
      setViewMode("opportunities");
    }
  };

  const handlePrimaryModeChange = (mode: PrimaryMode) => {
    setPrimaryMode(mode);
    setVisibleCount(10);
    setSearchQuery("");
    if (mode === "promos") {
      setViewMode("opportunities");
      return;
    }
    handleSurfaceModeChange(mode);
  };

  const enrichPlayerPropSideForActions = async (side: MarketSide): Promise<MarketSide> => {
    if (side.surface !== "player_props") {
      return side;
    }
    if ((side.reference_bookmakers?.length ?? 0) > 0) {
      return side;
    }
    const detail = await queryClient.fetchQuery({
      queryKey: queryKeys.boardPlayerPropDetail(side.selection_key, side.sportsbook),
      queryFn: () =>
        getBoardPlayerPropDetail({
          selectionKey: side.selection_key,
          sportsbook: side.sportsbook,
        }),
      staleTime: Infinity,
      gcTime: 60 * 60 * 1000,
    });
    return {
      ...side,
      reference_bookmakers: detail.reference_bookmakers,
      reference_bookmaker_count:
        detail.reference_bookmaker_count ?? side.reference_bookmaker_count ?? detail.reference_bookmakers.length,
    };
  };

  const handleLogBet = (side: MarketSide) => {
    void (async () => {
      let actionSide = side;
      if (side.surface === "player_props") {
        try {
          actionSide = await enrichPlayerPropSideForActions(side);
        } catch {
          toast.error("Could not load prop detail for review.");
          return;
        }
      }
      const betData = buildScannerLogBetInitialValues({
        side: actionSide,
        activeLens,
        boostPercent,
        sportDisplayMap: SPORT_KEY_TO_DISPLAY,
        kellyMultiplier,
        bankroll,
      });
      setDrawerInitialValues(betData);
      setDrawerKey(Date.now());
      setDrawerOpen(true);
    })();
  };

  const handleBetLogged = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.boardSurface("straight_bets") });
    queryClient.invalidateQueries({ queryKey: ["board_player_props"] });
    queryClient.invalidateQueries({ queryKey: ["board_promos"] });
  };

  const handleAddToCart = (side: MarketSide) => {
    void (async () => {
      if (!canAddScannerLensToParlayCart(activeLens)) {
        toast.error("Slip building is available from Opportunities and Browse lines.");
        return;
      }
      let actionSide = side;
      if (side.surface === "player_props") {
        try {
          actionSide = await enrichPlayerPropSideForActions(side);
        } catch {
          toast.error("Could not load prop detail for slip building.");
          return;
        }
      }
      const result = addCartLeg(buildParlayCartLeg(actionSide));
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
    })();
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
              Lines from {formatBoardAge(boardAgeMinutes)}
              {scanWindowLabel ? ` • ${scanWindowLabel}` : ""}
              {!scanWindowLabel ? ` • ${nextDropLabel}` : ""}
            </span>
          </p>
        ) : isEmptyBoard && !isBoardLoading ? (
          <p className="text-[11px] text-muted-foreground">
            No lines yet · scans daily ~10:30 AM / 3:30 PM AZ
          </p>
        ) : null}
      </div>

      {/* ── Row 1: Primary mode ───────────────────────────────────── */}
      <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
        {([
          { id: "player_props", label: "Player Props" },
          { id: "straight_bets", label: "Game Lines" },
          { id: "promos", label: "Promos" },
        ] as const).map((item) => (
          <button
            key={item.id}
            onClick={() => handlePrimaryModeChange(item.id)}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              primaryMode === item.id
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* ── Row 2: Contextual submode ─────────────────────────────── */}
      <div className="flex gap-1.5 overflow-x-auto pb-0.5 no-scrollbar">
        {primaryMode !== "promos" &&
          VIEW_MODES
            .filter((mode) => mode.id !== "pickem" || primaryMode === "player_props")
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
        {primaryMode === "promos" && (
          <div className="w-full space-y-2">
            <p className="pl-0.5 text-xs font-medium text-muted-foreground">Lens</p>
            <div className="grid grid-cols-2 gap-2">
              {PROMOS_SUBMODES.map((mode) => {
                const Icon = mode.icon;
                const isActive = promosSubmode === mode.id;
                return (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => setPromosSubmode(mode.id)}
                    aria-pressed={isActive}
                    className={cn(
                      "rounded-lg border px-3 py-2.5 text-left transition-colors",
                      isActive
                        ? `${mode.activeBg} ${mode.activeBorder} ${mode.activeText}`
                        : "border-border bg-background text-foreground hover:bg-muted dark:bg-card dark:hover:bg-muted/60",
                    )}
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                        {mode.id === "all" ? "Core View" : "Specialty"}
                      </span>
                      {isActive && (
                        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          Active
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "inline-flex h-6 w-6 items-center justify-center rounded-md bg-background/70 dark:bg-background/40",
                          isActive ? mode.iconText : "text-muted-foreground",
                        )}
                      >
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="text-xs font-semibold leading-tight md:text-sm">{mode.label}</span>
                    </div>
                    <p className="mt-1 text-[11px] leading-tight text-muted-foreground">{mode.description}</p>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* ── Search + single Filters control ───────────────────────── */}
      {activeScanData !== null && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <input
              type="search"
              placeholder={
                primaryMode === "player_props"
                  ? "Search players, teams, events…"
                  : "Search teams, events…"
              }
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <button
              type="button"
              onClick={() => setFiltersOpen((prev) => !prev)}
              className={cn(
                "shrink-0 rounded-md border px-3 py-2 text-xs font-medium transition-colors",
                filtersOpen
                  ? "border-primary/40 bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
              )}
            >
              Filters
            </button>
          </div>
          {filtersOpen && (
            <div className="rounded-md border border-border bg-card p-3 space-y-3">
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Books</p>
                <div className="flex flex-wrap gap-1.5">
                  {(primaryMode === "straight_bets" ? STRAIGHT_BET_BOOKS : PLAYER_PROP_BOOKS).map((book) => {
                    const selected = selectedBooks.includes(book);
                    return (
                      <button
                        key={book}
                        type="button"
                        onClick={() =>
                          setSelectedBooks((prev) =>
                            prev.includes(book) ? prev.filter((b) => b !== book) : [...prev, book],
                          )
                        }
                        className={cn(
                          "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                          selected
                            ? `${BOOK_COLORS[book] || "bg-foreground"} text-white`
                            : "bg-muted text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {book}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Time</p>
                <div className="flex flex-wrap gap-1.5">
                  {(
                    viewMode === "browse"
                      ? [
                          { id: "today", label: "Today" },
                          { id: "today_closed", label: "Closed Today" },
                          { id: "upcoming", label: "Upcoming" },
                          { id: "all_games", label: "All Games" },
                        ]
                      : [
                          { id: "today", label: "Today" },
                          { id: "today_closed", label: "Closed Today" },
                          { id: "upcoming", label: "Upcoming" },
                        ]
                  ).map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => setTimeFilter(option.id as BoardTimeFilter)}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                        timeFilter === option.id
                          ? "border-primary/40 bg-primary/10 text-foreground"
                          : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              {primaryMode === "straight_bets" && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Market Type</p>
                  <div className="flex flex-wrap gap-1.5">
                    {([
                      { id: "all", label: "All" },
                      { id: "h2h", label: "Moneyline" },
                      { id: "spreads", label: "Spreads" },
                      { id: "totals", label: "Totals" },
                    ] as const).map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => setStraightBetMarketFilter(option.id)}
                        className={cn(
                          "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                          straightBetMarketFilter === option.id
                            ? "border-primary/40 bg-primary/10 text-foreground"
                            : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                        )}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {primaryMode === "player_props" && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Market Type</p>
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => setPropMarketFilter("all")}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                        propMarketFilter === "all"
                          ? "border-primary/40 bg-primary/10 text-foreground"
                          : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                      )}
                    >
                      All
                    </button>
                    {availablePropMarkets.map((market) => (
                      <button
                        key={market}
                        type="button"
                        onClick={() => setPropMarketFilter(market)}
                        className={cn(
                          "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                          propMarketFilter === market
                            ? "border-primary/40 bg-primary/10 text-foreground"
                            : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                        )}
                      >
                        {formatMarketTypeLabel(market)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {isPickEmView && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Pick&apos;em Side</p>
                  <div className="flex flex-wrap gap-1.5">
                    {(["all", "over", "under"] as const).map((side) => (
                      <button
                        key={side}
                        type="button"
                        onClick={() => setPropSideFilter(side)}
                        className={cn(
                          "rounded-md border px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                          propSideFilter === side
                            ? "border-primary/40 bg-primary/10 text-foreground"
                            : "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                        )}
                      >
                        {side}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="pt-1">
                <button
                  type="button"
                  onClick={resetFilters}
                  className="text-xs font-medium text-muted-foreground hover:text-foreground underline underline-offset-2"
                >
                  Reset filters
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {!filtersOpen && activeFilterChips.length > 0 && (
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {activeLens === "profit_boost" && (
              <button
                type="button"
                onClick={() => setBoostSheetOpen(true)}
                className="rounded-full border border-[#C4A35A]/35 bg-[#C4A35A]/12 px-2 py-0.5 text-[10px] font-medium text-[#5C4D2E] transition-colors hover:bg-[#C4A35A]/20 dark:border-[#6D5A2A]/60 dark:bg-[#2B2417]/80 dark:text-[#E5CF94]"
                aria-label="Set profit boost percentage"
              >
                Boost: {boostPercent}%
              </button>
            )}
            {activeFilterChips.map((chip) => (
              <span
                key={chip}
                className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] text-foreground"
              >
                {chip}
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={resetFilters}
            className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2"
          >
            Reset
          </button>
        </div>
      )}

      <Sheet open={boostSheetOpen} onOpenChange={setBoostSheetOpen}>
        <SheetContent side="bottom" className="pb-5">
          <SheetHeader>
            <SheetTitle>Profit Boost</SheetTitle>
            <SheetDescription>Set your boost percentage.</SheetDescription>
          </SheetHeader>
          <div className="space-y-3 px-6 pt-3">
            <div className="grid grid-cols-3 gap-2">
              {BOOST_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => {
                    setBoostPercent(preset);
                    setCustomBoostInput("");
                    setBoostSheetOpen(false);
                  }}
                  className={cn(
                    "rounded-md border px-2 py-1.5 text-xs font-medium transition-colors",
                    boostPercent === preset && customBoostInput === ""
                      ? "border-[#C4A35A]/40 bg-[#C4A35A]/25 text-[#5C4D2E] dark:text-[#E5CF94]"
                      : "border-border bg-background text-foreground",
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
                onChange={(e) => {
                  setCustomBoostInput(e.target.value);
                  const n = parseScannerCustomBoostInput(e.target.value);
                  if (n !== null) {
                    setBoostPercent(n);
                  }
                }}
                className={cn(
                  "h-8 w-20 rounded-md border bg-background px-2 text-xs font-medium text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-[#C4A35A]/50",
                  customBoostInput !== "" ? "border-[#C4A35A]/40" : "border-border",
                )}
              />
              <span className="text-xs text-muted-foreground">%</span>
            </div>
          </div>
        </SheetContent>
      </Sheet>

      {/* ── Board error ───────────────────────────────────────────── */}
      {boardError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs text-destructive">
          Failed to load board:{" "}
          {boardError instanceof Error ? boardError.message : "Unknown error"}
        </div>
      )}

      {!boardError && activeSurfaceError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs text-destructive">
          Failed to load {primaryMode === "promos" ? "promo lines" : primaryMode === "straight_bets" ? "game lines" : isPickEmView ? "pick'em board" : "player props"}:{" "}
          {activeSurfaceError instanceof Error ? activeSurfaceError.message : "Unknown error"}
        </div>
      )}

      {!activeSurfaceError && activeContentIsLoading && (
        <MarketsPaneSkeleton
          label={
            primaryMode === "promos"
              ? "promos"
              : primaryMode === "straight_bets"
                ? "game-lines"
                : isPickEmView
                  ? "pickem"
                  : "player-props"
          }
          variant={primaryMode === "straight_bets" ? "gamelines" : isPickEmView ? "pickem" : "list"}
        />
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
      {!activeContentIsLoading && !isBoardLoading && isEmptyBoard && !boardError && !activeSurfaceError && activeScanData === null && (
        <div className="rounded-lg border border-border bg-card px-4 py-10 text-center">
          <Layers className="mx-auto mb-3 h-8 w-8 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">No lines loaded yet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Lines are loaded daily around 10:30 AM and 3:30 PM Arizona time.
          </p>
        </div>
      )}

      {/* 2. Board exists but this surface has no data in today's snapshot */}
      {!activeContentIsLoading && !isBoardLoading && !isEmptyBoard && !boardError && !activeSurfaceError && activeScanData === null && (
        <div className="rounded-lg border border-border bg-card px-4 py-8 text-center">
          <p className="text-sm font-medium text-foreground">
            No {primaryMode === "promos" ? "Promos" : primaryMode === "straight_bets" ? "Game Lines" : "Player Props"} in today&apos;s board
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Today&apos;s scan did not include this market. Check back after the next daily drop.
          </p>
        </div>
      )}

      {/* 3. Results pane — any scan data present (scoped overlay or canonical) */}
      {activeScanData !== null && (
        <>
          {(primaryMode !== "straight_bets" || allSides.length > 0) && (
            <ScannerResultsPane
              surface={primaryMode === "player_props" ? "player_props" : "straight_bets"}
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
              boostPercent={boostPercent}
              addedPickEmComparisonKeys={pickEmSlipKeys}
              canLoadMore={canLoadMore}
              isLoadingMore={isLoadingMore}
              onLoadMore={handleLoadMore}
              onLogBet={handleLogBet}
              onAddToCart={handleAddToCart}
              onStartPlaceFlow={handleLogBet}
              onAddPickEmToSlip={handleAddPickEmToSlip}
              bookColors={BOOK_COLORS}
              sportDisplayMap={SPORT_KEY_TO_DISPLAY}
            />
          )}
          {primaryMode === "promos" && promoGameLineResults.length > 0 && (
            <div className="rounded-lg border border-border bg-card px-4 py-3">
              <div className="mb-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Game-Line Promos
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Straight-bet promo candidates pulled from the current board across moneylines, spreads, and totals.
                </p>
              </div>
              <StraightBetList
                activeLens={activeLens}
                results={promoGameLineResults}
                kellyMultiplier={kellyMultiplier}
                bankroll={bankroll}
                boostPercent={boostPercent}
                canLoadMore={false}
                onLoadMore={() => {}}
                onLogBet={handleLogBet}
                onAddToCart={handleAddToCart}
                onStartPlaceFlow={handleLogBet}
                bookColors={BOOK_COLORS}
                sportDisplayMap={SPORT_KEY_TO_DISPLAY}
              />
            </div>
          )}
          {timeFilter === "today" && todayOpenCount === 0 && todayClosedCount > 0 && (
            <div className="rounded-md border border-border bg-card px-3 py-2 text-center">
              <p className="text-xs text-muted-foreground">No still-open markets today.</p>
              <button
                type="button"
                onClick={() => setTimeFilter("today_closed")}
                className="mt-1 text-xs font-medium text-foreground underline underline-offset-2"
              >
                View Closed Today
              </button>
            </div>
          )}
          {false && (
            <div className="rounded-lg border border-border bg-card px-4 py-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Featured Game Lines
                </p>
                <button
                  type="button"
                  onClick={() => setShowMoreFeaturedLines((prev) => !prev)}
                  className="text-[11px] text-muted-foreground hover:text-foreground"
                >
                  {showMoreFeaturedLines ? "Show less" : "Show more"}
                </button>
              </div>
              <div className="space-y-2">
                {featuredGames.map((game) => {
                  const kickoff = new Date(game.commence_time);
                  const kickoffLabel = Number.isNaN(kickoff.getTime())
                    ? ""
                    : kickoff.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
                  return (
                    <div key={`${game.sport}|${game.event}|${game.commence_time}`} className="rounded-md border border-border/70 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{game.event_short || game.event}</p>
                          <p className="text-[11px] text-muted-foreground">
                            {SPORT_KEY_TO_DISPLAY[game.sport] ?? game.sport}
                            {kickoffLabel ? ` • ${kickoffLabel}` : ""}
                          </p>
                        </div>
                        <div className="text-right text-[11px] text-muted-foreground">
                          <p>ML {game.h2h_offers.length}</p>
                          <p>Spr {game.spreads_offers.length} · Tot {game.totals_offers.length}</p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}

      {/* 3b. Featured Game Lines */}
      {primaryMode === "straight_bets" && !activeContentIsLoading && !isBoardLoading && !boardError && (filteredFeaturedGames.length > 0 || allSides.length === 0) && (
        <div className="space-y-2">
          {filteredFeaturedGames.length === 0 ? (
            <div className="rounded-lg border border-border bg-card px-4 py-8 text-center">
              <p className="text-sm font-medium text-foreground">No Game Lines in today&apos;s board</p>
              <p className="mt-1 text-xs text-muted-foreground">
                The daily drop did not include any featured moneylines, spreads, or totals for this filter yet.
              </p>
              {timeFilter === "today" && gameTodayOpenCount === 0 && gameTodayClosedCount > 0 && (
                <button
                  type="button"
                  onClick={() => setTimeFilter("today_closed")}
                  className="mt-2 text-xs font-medium text-foreground underline underline-offset-2"
                >
                  View Closed Today
                </button>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-border bg-card px-4 py-3">
              <div className="mb-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Featured Game Lines
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Board context across NBA, NCAAB, and MLB, including moneylines, spreads, and totals.
                </p>
              </div>
              <div className="space-y-2">
                {filteredFeaturedGames
                  .slice()
                  .sort((a, b) => new Date(a.commence_time).getTime() - new Date(b.commence_time).getTime())
                  .map((game) => {
                const kickoff = game.commence_time ? new Date(game.commence_time) : null;
                const kickoffLabel = kickoff && !Number.isNaN(kickoff.getTime())
                  ? kickoff.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })
                  : "";

                const title = game.event_short || game.event;
                const [homeTeam = "Home", awayTeam = "Away"] = title.split(/\s+vs\s+/i);
                const h2hByBook = new Map(game.h2h_offers.map((o) => [o.sportsbook, o] as const));
                const spreadByBook = new Map(game.spreads_offers.map((o) => [o.sportsbook, o] as const));
                const totalsByBook = new Map(game.totals_offers.map((o) => [o.sportsbook, o] as const));
                const visibleH2HOffers = selectedGameLineBooks
                  .map((book) => h2hByBook.get(book))
                  .filter((o): o is H2HOffer => Boolean(o));
                const visibleSpreadOffers = selectedGameLineBooks
                  .map((book) => spreadByBook.get(book))
                  .filter((o): o is SpreadOffer => Boolean(o));
                const visibleTotalsOffers = selectedGameLineBooks
                  .map((book) => totalsByBook.get(book))
                  .filter((o): o is TotalsOffer => Boolean(o));
                const showMoneyline = straightBetMarketFilter === "all" || straightBetMarketFilter === "h2h";
                const showSpreads = straightBetMarketFilter === "all" || straightBetMarketFilter === "spreads";
                const showTotals = straightBetMarketFilter === "all" || straightBetMarketFilter === "totals";

                return (
                  <div key={`${game.sport}|${game.event}|${game.commence_time}`} className="rounded-lg border border-border bg-card px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">{title}</p>
                        {kickoffLabel ? (
                          <p className="mt-0.5 text-[11px] text-muted-foreground">
                            {SPORT_KEY_TO_DISPLAY[game.sport] ?? game.sport}
                            {kickoffLabel ? ` • ${kickoffLabel}` : ""}
                          </p>
                        ) : null}
                      </div>
                      <div className="shrink-0 text-right text-[11px] text-muted-foreground">
                        {game.h2h_offers.length > 0 && <p>ML {game.h2h_offers.length}</p>}
                        {game.spreads_offers.length > 0 && <p>Spr {game.spreads_offers.length}</p>}
                        {game.totals_offers.length > 0 && <p>Tot {game.totals_offers.length}</p>}
                      </div>
                    </div>

                    <div className="mt-3 space-y-3">
                      {showMoneyline && visibleH2HOffers.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Moneyline</p>
                          {visibleH2HOffers.map((o) => (
                            <div key={`h2h-${o.sportsbook}`} className="flex items-center justify-between text-xs">
                              <span className="text-foreground">{o.sportsbook}</span>
                              <span className="text-muted-foreground">{homeTeam} {o.home_odds} • {awayTeam} {o.away_odds}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {showSpreads && visibleSpreadOffers.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Spreads</p>
                          {visibleSpreadOffers.map((o) => (
                            <div key={`spreads-${o.sportsbook}`} className="flex items-center justify-between text-xs">
                              <span className="text-foreground">{o.sportsbook}</span>
                              <span className="text-muted-foreground">
                                {homeTeam} {o.home_spread > 0 ? `+${o.home_spread}` : o.home_spread} ({o.home_odds}) • {awayTeam} {o.away_spread > 0 ? `+${o.away_spread}` : o.away_spread} ({o.away_odds})
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                      {showTotals && visibleTotalsOffers.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Totals</p>
                          {visibleTotalsOffers.map((o) => (
                            <div key={`totals-${o.sportsbook}`} className="flex items-center justify-between text-xs">
                              <span className="text-foreground">{o.sportsbook}</span>
                              <span className="text-muted-foreground">Total {o.total} • O {o.over_odds} • U {o.under_odds}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
                })}
              </div>
            </div>
          )}
        </div>
      )}
      <LogBetDrawer
        key={drawerKey}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        initialValues={drawerInitialValues}
        onLogged={handleBetLogged}
      />
    </div>
  );
}
