"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Clock, Gift, Layers, ShieldCheck, TrendingUp, Zap } from "lucide-react";

import { ScannerResultsPane } from "@/app/scanner/components/ScannerResultsPane";
import {
  isStraightBetsTutorialActive,
  STRAIGHT_BETS_TUTORIAL_SCAN,
} from "@/app/scanner/scanner-tutorial";
import type { PickEmBoardCard } from "@/app/scanner/pickem-board";
import { rankScannerSidesByLens, type RankedScannerSide } from "@/app/scanner/scanner-lenses";
import { getBoardPlayerPropDetail } from "@/lib/api";
import { sendAnalyticsEvent } from "@/lib/analytics";
import {
  buildParlayCartLeg,
  buildParlayCartLegFromPickEmCard,
  buildScannerLogBetInitialValues,
  parseScannerCustomBoostInput,
} from "@/app/scanner/scanner-state-utils";
import { canAddScannerLensToParlayCart } from "@/app/scanner/scanner-ui-model";
import { classifyScannerNullState } from "@/lib/scanner-contract";
import { useApplyOnboardingEvent, useBoard, useBoardSurface, useBalances, useSettings, queryKeys, useInfiniteBoardPlayerPropsView } from "@/lib/hooks";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { getDailyDropWindowsLocal } from "@/lib/drop-windows";
import { useKellySettings } from "@/lib/kelly-context";
import { useOnboardingHighlight } from "@/lib/onboarding-highlight";
import { ONBOARDING_HIGHLIGHT_TARGETS } from "@/lib/onboarding-guidance";
import { createClient } from "@/lib/supabase";
import { expandTeamAliasSearchQuery, matchesTeamAliasSearch } from "@/lib/team-search-aliases";
import {
  PLAYER_PROP_MARKET_OPTIONS,
  formatPlayerPropMarketLabel,
  isSupportedPlayerPropMarketForSport,
} from "@/lib/player-prop-markets";
import { JourneyCoach } from "@/components/JourneyCoach";
import { LogBetDrawer } from "@/components/LogBetDrawer";
import {
  FilterChipList,
  MultiSelectFilterPills,
  SingleSelectFilterPills,
} from "@/components/shared/FilterControls";
import { FolderTabs } from "@/components/shared/FolderTabs";
import { ONBOARDING_STEPS } from "@/lib/onboarding";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { americanToDecimal, cn } from "@/lib/utils";
import type {
  MarketSide,
  PlayerPropBoardItem,
  PlayerPropBoardPageResponse,
  PlayerPropBoardPickEmCard,
  PlayerPropMarketSide,
  ScanResult,
  ScannedBetData,
  TutorialPracticeBet,
} from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────────

type MarketsViewMode = "opportunities" | "browse" | "pickem";
type BoardTimeFilter = "today" | "upcoming" | "all_games" | "today_closed";
type PrimaryMode = "player_props" | "straight_bets" | "promos";
type PromosSubmode = "boosts" | "bonus_bets" | "qualifiers";
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
    id: "boosts",
    label: "Boosts",
    description: "Rank by boosted EV",
    icon: Zap,
    activeBg: "bg-primary/8",
    activeBorder: "border-primary/30",
    activeText: "text-primary",
    iconText: "text-primary",
  },
  {
    id: "bonus_bets",
    label: "Bonus Bets",
    description: "Rank by retention",
    icon: Gift,
    activeBg: "bg-profit/8",
    activeBorder: "border-profit/20",
    activeText: "text-profit",
    iconText: "text-profit",
  },
  {
    id: "qualifiers",
    label: "Qualifiers",
    description: "Rank by lowest hold",
    icon: ShieldCheck,
    activeBg: "bg-loss/8",
    activeBorder: "border-loss/25",
    activeText: "text-loss",
    iconText: "text-loss",
  },
];

const PLAYER_PROP_BOOKS = ["Bovada", "BetOnline.ag", "DraftKings", "FanDuel", "BetMGM", "Caesars"];
const STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN Bet"];
const PROMO_BOOKS = Array.from(new Set([...PLAYER_PROP_BOOKS, ...STRAIGHT_BET_BOOKS]));
const DEFAULT_PLAYER_PROP_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Bovada", "BetOnline.ag"];
const DEFAULT_STRAIGHT_BET_BOOKS = ["DraftKings", "FanDuel"];
const DEFAULT_PROMO_BOOKS = Array.from(new Set([...DEFAULT_PLAYER_PROP_BOOKS, ...DEFAULT_STRAIGHT_BET_BOOKS]));
const PLAYER_PROP_PAGE_SIZE = 10;
const PROMO_PLAYER_PROP_PAGE_SIZE = 200;

const SPORT_KEY_TO_DISPLAY: Record<string, string> = {
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
  baseball_mlb: "MLB",
};

const BOOK_COLORS: Record<string, string> = {
  Bovada: "bg-color-loss",
  "BetOnline.ag": "bg-color-profit",
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
  promos?: unknown;
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

function sanitizeStoredBooks(stored: unknown, allowed: readonly string[], fallback: string[]): string[] {
  if (!Array.isArray(stored)) return fallback;
  const allow = new Set(allowed);
  const next = stored.filter((b): b is string => typeof b === "string" && allow.has(b));
  return next.length > 0 ? next : fallback;
}

function toggleBookSelection(current: string[], book: string): string[] {
  if (current.includes(book)) {
    // Keep at least one selected book to avoid API fallback behavior that can look like stale filtering.
    if (current.length <= 1) return current;
    return current.filter((candidate) => candidate !== book);
  }
  return [...current, book];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const PHOENIX_WALL_CLOCK_AS_UTC_OFFSET_MS = 7 * 60 * 60 * 1000;

function parseScanTimestampMs(iso: string): number | null {
  const parsed = new Date(iso).getTime();
  if (Number.isNaN(parsed)) return null;

  // Some older payloads stored Phoenix wall-clock time with a trailing Z.
  // If that happens, the timestamp appears ~7h older than reality.
  if (!iso.endsWith("Z")) return parsed;

  const shifted = parsed + PHOENIX_WALL_CLOCK_AS_UTC_OFFSET_MS;
  const now = Date.now();
  const parsedDistance = Math.abs(now - parsed);
  const shiftedDistance = Math.abs(now - shifted);

  if (shifted <= now + 15 * 60 * 1000 && shiftedDistance + 60 * 1000 < parsedDistance) {
    return shifted;
  }
  return parsed;
}

function minutesAgo(iso: string): number {
  const then = parseScanTimestampMs(iso);
  if (then === null) return 0;
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
  event_id?: string | null;
  event: string;
  event_short?: string;
  sport: string;
  commence_time: string;
  away_team?: string;
  away_team_short?: string;
  home_team?: string;
  home_team_short?: string;
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
  return formatPlayerPropMarketLabel(market);
}

function getSearchableMarketTokens(side: MarketSide): string[] {
  const marketKey = String(side.market_key ?? "").trim().toLowerCase();
  const marketLabel = String((side as { market?: string }).market ?? "").trim();

  if (marketKey === "h2h") return ["h2h", "moneyline", "ml", marketLabel].filter(Boolean);
  if (marketKey === "spreads") return ["spreads", "spread", marketLabel].filter(Boolean);
  if (marketKey === "totals") return ["totals", "total", "over under", "ou", marketLabel].filter(Boolean);

  return [marketKey, marketLabel].filter(Boolean);
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
        event_id: typeof (rawGame as { event_id?: unknown }).event_id === "string" ? (rawGame as { event_id: string }).event_id : undefined,
        event: g.event,
        event_short: typeof g.event_short === "string" ? g.event_short : undefined,
        sport,
        commence_time: g.commence_time,
        away_team: typeof (rawGame as { away_team?: unknown }).away_team === "string" ? (rawGame as { away_team: string }).away_team : undefined,
        away_team_short:
          typeof (rawGame as { away_team_short?: unknown }).away_team_short === "string"
            ? (rawGame as { away_team_short: string }).away_team_short
            : undefined,
        home_team: typeof (rawGame as { home_team?: unknown }).home_team === "string" ? (rawGame as { home_team: string }).home_team : undefined,
        home_team_short:
          typeof (rawGame as { home_team_short?: unknown }).home_team_short === "string"
            ? (rawGame as { home_team_short: string }).home_team_short
            : undefined,
        h2h_offers: h2h as FeaturedLineGame["h2h_offers"],
        spreads_offers: spreads as FeaturedLineGame["spreads_offers"],
        totals_offers: totals as FeaturedLineGame["totals_offers"],
      });
    }
    if (games.length > 0) buckets.push({ sport, games });
  }
  return buckets;
}

function devigTwoWayProbabilities(priceA: number, priceB: number): { sideA: number; sideB: number } | null {
  if (!Number.isFinite(priceA) || !Number.isFinite(priceB)) return null;
  const decimalA = americanToDecimal(priceA);
  const decimalB = americanToDecimal(priceB);
  if (decimalA <= 1 || decimalB <= 1) return null;
  const impliedA = 1 / decimalA;
  const impliedB = 1 / decimalB;
  const overround = impliedA + impliedB;
  if (!Number.isFinite(overround) || overround <= 0) return null;
  return {
    sideA: impliedA / overround,
    sideB: impliedB / overround,
  };
}

function calculateKellyFraction(trueProb: number, decimalOdds: number): number {
  if (!Number.isFinite(trueProb) || !Number.isFinite(decimalOdds) || decimalOdds <= 1) return 0;
  const b = decimalOdds - 1;
  const q = 1 - trueProb;
  const kelly = ((b * trueProb) - q) / b;
  return Math.max(0, kelly);
}

function buildSelectionToken(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function buildLineToken(value: number, options?: { includePlus?: boolean }): string {
  const includePlus = options?.includePlus ?? false;
  const normalized = Number.parseFloat(value.toFixed(2));
  const token = `${normalized}`.replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
  if (includePlus && normalized > 0 && !token.startsWith("+")) return `+${token}`;
  return token;
}

function buildFeaturedSelectionKey(
  game: FeaturedLineGame,
  marketKey: "spreads" | "totals",
  selectionToken: string,
  lineValue: number,
): string {
  const eventRef = (game.event_id ?? `${game.sport}|${game.commence_time}|${game.event}`).trim().toLowerCase();
  return [
    eventRef,
    marketKey,
    buildSelectionToken(selectionToken),
    buildLineToken(lineValue, { includePlus: marketKey === "spreads" }),
  ].join("|");
}

function makeStraightCardKey(side: MarketSide): string {
  const lineToken =
    side.line_value == null || !Number.isFinite(side.line_value)
      ? ""
      : `|${Number.parseFloat(side.line_value.toFixed(2))}`;
  return [
    side.surface,
    side.sportsbook,
    side.market_key ?? "h2h",
    side.selection_key ?? "",
    side.selection_side ?? "",
    side.event_id ?? side.commence_time,
    side.team ?? "",
    lineToken,
  ].join("|");
}

function mergeMarketSides(primary: MarketSide[], supplemental: MarketSide[]): MarketSide[] {
  const seen = new Set<string>();
  const merged: MarketSide[] = [];
  for (const side of [...primary, ...supplemental]) {
    const key = makeStraightCardKey(side);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(side);
  }
  return merged;
}

function buildFeaturedDerivedSides(buckets: FeaturedSportBucket[]): MarketSide[] {
  const derived: MarketSide[] = [];

  for (const bucket of buckets) {
    for (const game of bucket.games) {
      const homeTeam = game.home_team?.trim();
      const awayTeam = game.away_team?.trim();
      if (!homeTeam || !awayTeam) continue;

      const pinnacleSpread = game.spreads_offers.find((offer) => offer.sportsbook === "Pinnacle");
      if (pinnacleSpread) {
        const trueProbs = devigTwoWayProbabilities(pinnacleSpread.home_odds, pinnacleSpread.away_odds);
        if (trueProbs) {
          for (const offer of game.spreads_offers) {
            if (offer.sportsbook === "Pinnacle") continue;
            if (
              Math.abs(offer.home_spread - pinnacleSpread.home_spread) > 0.01 ||
              Math.abs(offer.away_spread - pinnacleSpread.away_spread) > 0.01
            ) {
              continue;
            }
            const homeDecimal = americanToDecimal(offer.home_odds);
            const awayDecimal = americanToDecimal(offer.away_odds);
            derived.push({
              surface: "straight_bets",
              event_id: game.event_id,
              market_key: "spreads",
              selection_key: buildFeaturedSelectionKey(game, "spreads", homeTeam, offer.home_spread),
              selection_side: "home",
              line_value: offer.home_spread,
              sportsbook: offer.sportsbook,
              sport: bucket.sport,
              event: game.event,
              event_short: game.event_short,
              commence_time: game.commence_time,
              team: homeTeam,
              team_short: game.home_team_short,
              opponent_short: game.away_team_short,
              pinnacle_odds: pinnacleSpread.home_odds,
              book_odds: offer.home_odds,
              true_prob: trueProbs.sideA,
              base_kelly_fraction: calculateKellyFraction(trueProbs.sideA, homeDecimal),
              book_decimal: homeDecimal,
              ev_percentage: (trueProbs.sideA * homeDecimal - 1) * 100,
            });
            derived.push({
              surface: "straight_bets",
              event_id: game.event_id,
              market_key: "spreads",
              selection_key: buildFeaturedSelectionKey(game, "spreads", awayTeam, offer.away_spread),
              selection_side: "away",
              line_value: offer.away_spread,
              sportsbook: offer.sportsbook,
              sport: bucket.sport,
              event: game.event,
              event_short: game.event_short,
              commence_time: game.commence_time,
              team: awayTeam,
              team_short: game.away_team_short,
              opponent_short: game.home_team_short,
              pinnacle_odds: pinnacleSpread.away_odds,
              book_odds: offer.away_odds,
              true_prob: trueProbs.sideB,
              base_kelly_fraction: calculateKellyFraction(trueProbs.sideB, awayDecimal),
              book_decimal: awayDecimal,
              ev_percentage: (trueProbs.sideB * awayDecimal - 1) * 100,
            });
          }
        }
      }

      const pinnacleTotal = game.totals_offers.find((offer) => offer.sportsbook === "Pinnacle");
      if (pinnacleTotal) {
        const trueProbs = devigTwoWayProbabilities(pinnacleTotal.over_odds, pinnacleTotal.under_odds);
        if (trueProbs) {
          for (const offer of game.totals_offers) {
            if (offer.sportsbook === "Pinnacle") continue;
            if (Math.abs(offer.total - pinnacleTotal.total) > 0.01) continue;
            const overDecimal = americanToDecimal(offer.over_odds);
            const underDecimal = americanToDecimal(offer.under_odds);
            derived.push({
              surface: "straight_bets",
              event_id: game.event_id,
              market_key: "totals",
              selection_key: buildFeaturedSelectionKey(game, "totals", "over", offer.total),
              selection_side: "over",
              line_value: offer.total,
              sportsbook: offer.sportsbook,
              sport: bucket.sport,
              event: game.event,
              event_short: game.event_short,
              commence_time: game.commence_time,
              team: "Over",
              team_short: null,
              opponent_short: null,
              pinnacle_odds: pinnacleTotal.over_odds,
              book_odds: offer.over_odds,
              true_prob: trueProbs.sideA,
              base_kelly_fraction: calculateKellyFraction(trueProbs.sideA, overDecimal),
              book_decimal: overDecimal,
              ev_percentage: (trueProbs.sideA * overDecimal - 1) * 100,
            });
            derived.push({
              surface: "straight_bets",
              event_id: game.event_id,
              market_key: "totals",
              selection_key: buildFeaturedSelectionKey(game, "totals", "under", offer.total),
              selection_side: "under",
              line_value: offer.total,
              sportsbook: offer.sportsbook,
              sport: bucket.sport,
              event: game.event,
              event_short: game.event_short,
              commence_time: game.commence_time,
              team: "Under",
              team_short: null,
              opponent_short: null,
              pinnacle_odds: pinnacleTotal.under_odds,
              book_odds: offer.under_odds,
              true_prob: trueProbs.sideB,
              base_kelly_fraction: calculateKellyFraction(trueProbs.sideB, underDecimal),
              book_decimal: underDecimal,
              ev_percentage: (trueProbs.sideB * underDecimal - 1) * 100,
            });
          }
        }
      }
    }
  }

  return derived;
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
  const router = useRouter();
  const queryClient = useQueryClient();
  const applyOnboardingEvent = useApplyOnboardingEvent();
  const { highlight } = useOnboardingHighlight();
  const { data: board, isLoading: isBoardLoading, error: boardError } = useBoard();
  const { data: balances } = useBalances();
  useSettings(); // ensure settings are warmed in cache for LogBetDrawer

  const { useComputedBankroll, bankrollOverride, kellyMultiplier } = useKellySettings();
  const {
    cart,
    addCartLeg,
    onboardingCompleted,
    onboardingDismissed,
    scannerReviewCandidate,
    clearScannerReviewCandidate,
    tutorialSession,
    saveTutorialPracticeBet,
  } = useBettingPlatformStore();
  const tutorialMode = isStraightBetsTutorialActive({
    surface: "straight_bets",
    completed: onboardingCompleted,
    dismissed: onboardingDismissed,
  });
  const tutorialBoardActive = tutorialMode && Boolean(tutorialSession?.has_seeded_scan);
  const [completionQueryFlag, setCompletionQueryFlag] = useState(false);
  const [showCompletionCard, setShowCompletionCard] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const hasCompletionFlag = new URLSearchParams(window.location.search).get("onboarding") === "complete";
    setCompletionQueryFlag(hasCompletionFlag);
  }, []);

  useEffect(() => {
    if (!completionQueryFlag) return;
    setShowCompletionCard(true);
  }, [completionQueryFlag]);

  // ── UI state ─────────────────────────────────────────────────────────────
  const [primaryMode, setPrimaryMode] = useState<PrimaryMode>("player_props");
  const [viewMode, setViewMode] = useState<MarketsViewMode>("opportunities");
  const [promosSubmode, setPromosSubmode] = useState<PromosSubmode>("boosts");

  // Per-surface book selections — persisted in localStorage (see hydrate / persist effects below)
  const [selectedPropBooks, setSelectedPropBooks] = useState<string[]>(DEFAULT_PLAYER_PROP_BOOKS);
  const [selectedGameLineBooks, setSelectedGameLineBooks] = useState<string[]>(DEFAULT_STRAIGHT_BET_BOOKS);
  const [selectedPromoBooks, setSelectedPromoBooks] = useState<string[]>(DEFAULT_PROMO_BOOKS);
  const [booksHydrated, setBooksHydrated] = useState(false);
  const [visibleCount, setVisibleCount] = useState(10);
  const [searchQuery, setSearchQuery] = useState("");
  const [timeFilter, setTimeFilter] = useState<BoardTimeFilter>("today");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [propSportFilter, setPropSportFilter] = useState<string>("all");
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
    sport: string;
    market: string;
    search: string;
  }>(() => ({
    books: [...DEFAULT_PLAYER_PROP_BOOKS].sort(),
    timeFilter: "today",
    sport: "all",
    market: "all",
    search: "",
  }));

  const selectedBooks =
    primaryMode === "straight_bets"
      ? selectedGameLineBooks
      : primaryMode === "promos"
        ? selectedPromoBooks
        : selectedPropBooks;
  const setSelectedBooks =
    primaryMode === "straight_bets"
      ? setSelectedGameLineBooks
      : primaryMode === "promos"
        ? setSelectedPromoBooks
        : setSelectedPropBooks;
  const tzOffsetMinutes = useMemo(() => new Date().getTimezoneOffset(), []);
  const selectedPlayerPropsBooks = primaryMode === "promos" ? selectedPromoBooks : selectedPropBooks;
  const appliedPlayerPropsBooks = playerPropsQueryFilters.books;
  const appliedPlayerPropsTimeFilter = playerPropsQueryFilters.timeFilter;
  const appliedPlayerPropsSportFilter = playerPropsQueryFilters.sport;
  const appliedPlayerPropsMarketFilter = playerPropsQueryFilters.market;
  const appliedPlayerPropsSearchQuery = playerPropsQueryFilters.search;

  const straightSurface = useBoardSurface(
    "straight_bets",
    primaryMode === "straight_bets" || primaryMode === "promos",
  );
  const playerPropsOpportunities = useInfiniteBoardPlayerPropsView({
    view: "opportunities",
    pageSize: PLAYER_PROP_PAGE_SIZE,
    books: appliedPlayerPropsBooks,
    timeFilter: appliedPlayerPropsTimeFilter,
    sport: appliedPlayerPropsSportFilter,
    market: appliedPlayerPropsMarketFilter,
    search: appliedPlayerPropsSearchQuery,
    tzOffsetMinutes,
    enabled: primaryMode === "player_props" && viewMode === "opportunities",
  });
  const playerPropsBrowse = useInfiniteBoardPlayerPropsView({
    view: "browse",
    pageSize: primaryMode === "promos" ? PROMO_PLAYER_PROP_PAGE_SIZE : PLAYER_PROP_PAGE_SIZE,
    books: appliedPlayerPropsBooks,
    timeFilter: appliedPlayerPropsTimeFilter,
    sport: appliedPlayerPropsSportFilter,
    market: appliedPlayerPropsMarketFilter,
    search: appliedPlayerPropsSearchQuery,
    tzOffsetMinutes,
    enabled: (primaryMode === "player_props" && viewMode === "browse") || primaryMode === "promos",
  });
  const playerPropsPickem = useInfiniteBoardPlayerPropsView({
    view: "pickem",
    pageSize: PLAYER_PROP_PAGE_SIZE,
    books: appliedPlayerPropsBooks,
    timeFilter: appliedPlayerPropsTimeFilter,
    sport: appliedPlayerPropsSportFilter,
    market: appliedPlayerPropsMarketFilter,
    search: appliedPlayerPropsSearchQuery,
    tzOffsetMinutes,
    enabled: primaryMode === "player_props" && viewMode === "pickem",
  });
  useEffect(() => {
    try {
      const raw = localStorage.getItem(SCANNER_BOOKS_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as StoredScannerBooks;
        const hydratedPropBooks = sanitizeStoredBooks(
          parsed.player_props,
          PLAYER_PROP_BOOKS,
          DEFAULT_PLAYER_PROP_BOOKS,
        );
        const hydratedGameLineBooks = sanitizeStoredBooks(
          parsed.straight_bets,
          STRAIGHT_BET_BOOKS,
          DEFAULT_STRAIGHT_BET_BOOKS,
        );
        const legacyPromoFallback = PROMO_BOOKS.filter(
          (book) => hydratedPropBooks.includes(book) || hydratedGameLineBooks.includes(book),
        );

        setSelectedPropBooks(hydratedPropBooks);
        setSelectedGameLineBooks(hydratedGameLineBooks);
        setSelectedPromoBooks(
          sanitizeStoredBooks(
            parsed.promos,
            PROMO_BOOKS,
            legacyPromoFallback.length > 0 ? legacyPromoFallback : DEFAULT_PROMO_BOOKS,
          ),
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
        JSON.stringify({
          player_props: selectedPropBooks,
          straight_bets: selectedGameLineBooks,
          promos: selectedPromoBooks,
        }),
      );
    } catch {
      // ignore quota / private mode
    }
  }, [booksHydrated, selectedGameLineBooks, selectedPromoBooks, selectedPropBooks]);

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
    const normalizedPlayerPropsSearch = expandTeamAliasSearchQuery(deferredPlayerPropsSearchQuery.trim());
    const nextFilters = {
      books: [...selectedPlayerPropsBooks].sort(),
      timeFilter,
      sport: propSportFilter,
      market: propMarketFilter,
      search: normalizedPlayerPropsSearch,
    };
    const handle = window.setTimeout(() => {
      setPlayerPropsQueryFilters((current) => {
        if (
          sameStringSet(current.books, nextFilters.books) &&
          current.timeFilter === nextFilters.timeFilter &&
          current.sport === nextFilters.sport &&
          current.market === nextFilters.market &&
          current.search === nextFilters.search
        ) {
          return current;
        }
        return nextFilters;
      });
    }, 250);
    return () => window.clearTimeout(handle);
  }, [
    deferredPlayerPropsSearchQuery,
    propMarketFilter,
    propSportFilter,
    selectedPlayerPropsBooks,
    timeFilter,
  ]);

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
  const [drawerPracticeMode, setDrawerPracticeMode] = useState(false);

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
  const boardViewedSnapshotRef = useRef<string | null>(null);

  useEffect(() => {
    const snapshotId = boardMeta?.snapshot_id;
    if (!snapshotId || snapshotId === "none") {
      return;
    }
    if (boardViewedSnapshotRef.current === snapshotId) {
      return;
    }
    boardViewedSnapshotRef.current = snapshotId;

    void sendAnalyticsEvent({
      eventName: "board_viewed",
      route: "/",
      appArea: "markets",
      properties: {
        snapshot_id: snapshotId,
        scanned_at: boardMeta?.scanned_at ?? null,
      },
      dedupeKey: `board-viewed:${snapshotId}`,
    });
  }, [boardMeta?.snapshot_id, boardMeta?.scanned_at]);

  const activePlayerPropsListPage = useMemo(() => {
    const data =
      primaryMode === "promos"
        ? playerPropsBrowse.data
        : viewMode === "browse"
          ? playerPropsBrowse.data
          : playerPropsOpportunities.data;
    if ((primaryMode !== "promos" && viewMode === "pickem") || !data?.pages?.length) return null;
    const pages = data.pages.filter(Boolean) as PlayerPropBoardPageResponse<PlayerPropBoardItem>[];
    const lastPage = pages[pages.length - 1];
    if (!lastPage) return null;
    return {
      items: pages.flatMap((page) => page?.items ?? []) as PlayerPropBoardItem[],
      total: lastPage.total,
      source_total: lastPage.source_total,
      has_more: lastPage.has_more,
      scanned_at: lastPage.scanned_at,
      available_books: lastPage.available_books,
      available_markets: lastPage.available_markets,
      available_sports: lastPage.available_sports,
    };
  }, [playerPropsBrowse.data, playerPropsOpportunities.data, primaryMode, viewMode]);

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
      available_books: lastPage.available_books,
      available_markets: lastPage.available_markets,
      available_sports: lastPage.available_sports,
    };
  }, [playerPropsPickem.data, viewMode]);

  const activePlayerPropsIsFetchingNextPage = useMemo(() => {
    if (primaryMode === "promos") {
      return playerPropsBrowse.isFetchingNextPage;
    }
    if (viewMode === "browse") {
      return playerPropsBrowse.isFetchingNextPage;
    }
    if (viewMode === "pickem") return playerPropsPickem.isFetchingNextPage;
    return playerPropsOpportunities.isFetchingNextPage;
  }, [playerPropsBrowse.isFetchingNextPage, playerPropsOpportunities.isFetchingNextPage, playerPropsPickem.isFetchingNextPage, primaryMode, viewMode]);

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
      if (tutorialBoardActive) {
        return {
          ...STRAIGHT_BETS_TUTORIAL_SCAN,
          scanned_at: new Date().toISOString(),
        };
      }
      return straightSurface.data ?? null;
    }

    const promoPropSides = (activePlayerPropsListPage?.items as MarketSide[] | undefined) ?? [];
    const promoStraightSides = (straightSurface.data?.sides as MarketSide[] | undefined) ?? [];
    if (promoPropSides.length === 0 && promoStraightSides.length === 0) return null;
    return {
      surface: "straight_bets",
      sport: "all",
      sides: [...promoPropSides, ...promoStraightSides],
      events_fetched: 0,
      events_with_both_books: 0,
      api_requests_remaining: null,
      scanned_at: activePlayerPropsListPage?.scanned_at ?? straightSurface.data?.scanned_at ?? boardMeta?.scanned_at ?? null,
    };
  }, [
    activePlayerPropsListPage,
    activePlayerPropsPickemPage,
    boardMeta?.scanned_at,
    primaryMode,
    straightSurface.data,
    tutorialBoardActive,
    viewMode,
  ]);
  const activeSurfaceError = useMemo(() => {
    if (primaryMode === "player_props") {
      return activePlayerPropsError;
    }
    if (primaryMode === "promos") {
      return playerPropsBrowse.error ?? straightSurface.error;
    }
    if (primaryMode === "straight_bets") {
      return straightSurface.error;
    }
    return null;
  }, [activePlayerPropsError, playerPropsBrowse.error, primaryMode, straightSurface.error]);
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
      return (
        playerPropsBrowse.isLoading ||
        (playerPropsBrowse.isFetching && !activePlayerPropsListPage) ||
        straightSurface.isLoading ||
        (straightSurface.isFetching && !straightSurface.data)
      );
    }
    return straightSurface.isLoading || (straightSurface.isFetching && !straightSurface.data);
  }, [
    activePlayerPropsListPage,
    activePlayerPropsPickemPage,
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
  const featuredDerivedSides = useMemo(() => buildFeaturedDerivedSides(featuredLineBuckets), [featuredLineBuckets]);

  const displayScannedAt = activeScanData?.scanned_at ?? boardMeta?.scanned_at ?? null;

  const boardAgeMinutes = useMemo(() => {
    if (displayScannedAt) return minutesAgo(displayScannedAt);
    return null;
  }, [displayScannedAt]);

  const dailyDropWindows = useMemo(() => getDailyDropWindowsLocal(), []);

  const nextDropLabel = useMemo(() => {
    try {
      const nextDropUtcMs = getNextPhoenixDropUtcMs(new Date());
      const nextDropLocal = new Date(nextDropUtcMs);
      const localTime = nextDropLocal.toLocaleString(undefined, {
        hour: "numeric",
        minute: "2-digit",
      });
      return `Next scan ${localTime}`;
    } catch {
      return `Next scan ${dailyDropWindows.localLabel}`;
    }
  }, [dailyDropWindows.localLabel]);

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

  const boardAgeDetail = useMemo(() => {
    const parts: string[] = [];
    if (scanWindowLabel) parts.push(scanWindowLabel);
    parts.push(nextDropLabel);
    return parts.join(" • ");
  }, [nextDropLabel, scanWindowLabel]);

  const allSides = useMemo(() => {
    if (primaryMode === "player_props") {
      return (activePlayerPropsListPage?.items as MarketSide[]) ?? [];
    }
    if (tutorialBoardActive) {
      return (activeScanData?.sides as MarketSide[] | undefined) ?? [];
    }
    return mergeMarketSides((activeScanData?.sides as MarketSide[] | undefined) ?? [], featuredDerivedSides);
  }, [activePlayerPropsListPage?.items, activeScanData, featuredDerivedSides, primaryMode, tutorialBoardActive]);

  const activeLens = useMemo(() => {
    if (primaryMode !== "promos") return "standard";
    if (promosSubmode === "bonus_bets") return "bonus_bet";
    if (promosSubmode === "qualifiers") return "qualifier";
    return "profit_boost";
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
        selectedBooks: selectedPromoBooks,
        activeLens,
        boostPercent,
      });
      const promoStraight = rankScannerSidesByLens({
        sides: sidesForRanking.filter((side) => side.surface !== "player_props"),
        selectedBooks: selectedPromoBooks,
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
    selectedPromoBooks,
    viewMode,
    activeLens,
    primaryMode,
    boostPercent,
  ]);

  const filteredSides = useMemo(() => {
    if (primaryMode === "player_props") {
      const items = ((activePlayerPropsListPage?.items as MarketSide[]) ?? []);
      if (propSportFilter === "all") return items;
      return items.filter((side) => side.sport === propSportFilter);
    }
    const timeFiltered = rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, timeFilter));
    const marketFiltered =
      primaryMode === "straight_bets" && straightBetMarketFilter !== "all"
        ? timeFiltered.filter((s) => String(s.market_key ?? "").toLowerCase() === straightBetMarketFilter)
        : timeFiltered;
    if (!searchQuery.trim()) return marketFiltered;
    const q = searchQuery.trim();
    return marketFiltered.filter((s) => {
      const marketTokens = getSearchableMarketTokens(s);
      return matchesTeamAliasSearch(q, [
        s.event,
        s.event_short ?? "",
        s.sport,
        s.sportsbook,
        "player_name" in s ? (s as { player_name?: string }).player_name : "",
        ...marketTokens,
        "team" in s ? (s as { team?: string }).team : "",
        "team_short" in s ? (s as { team_short?: string }).team_short : "",
        "opponent" in s ? (s as { opponent?: string }).opponent : "",
        "opponent_short" in s ? (s as { opponent_short?: string }).opponent_short : "",
      ]);
    });
  }, [activePlayerPropsListPage?.items, primaryMode, propSportFilter, rankedSides, searchQuery, straightBetMarketFilter, timeFilter]);
  const todayOpenCount = useMemo(
    () => (primaryMode === "player_props" ? 0 : rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, "today")).length),
    [primaryMode, rankedSides],
  );
  const todayClosedCount = useMemo(
    () => (primaryMode === "player_props" ? 0 : rankedSides.filter((s) => matchesBoardTimeFilter(s.commence_time, "today_closed")).length),
    [primaryMode, rankedSides],
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
        if (propSportFilter !== "all" && card.sport !== propSportFilter) return false;
        if (propSideFilter !== "all" && card.consensus_side !== propSideFilter) return false;
        return true;
      }),
    [pickEmCards, primaryMode, propSideFilter, propSportFilter],
  );
  const availablePropSports = useMemo(() => {
    if (primaryMode === "player_props") {
      const sports = activePlayerPropsListPage?.available_sports ?? activePlayerPropsPickemPage?.available_sports;
      if (Array.isArray(sports) && sports.length > 0) {
        return sports;
      }
    }
    const sports = new Set<string>();
    for (const side of allSides) {
      if (side.surface === "player_props" && side.sport) {
        sports.add(side.sport);
      }
    }
    return Array.from(sports).sort();
  }, [activePlayerPropsListPage?.available_sports, activePlayerPropsPickemPage?.available_sports, allSides, primaryMode]);
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
  const availablePropMarketsForSport = useMemo(() => {
    if (propSportFilter === "all") return availablePropMarkets;
    const scoped = availablePropMarkets.filter((market) =>
      isSupportedPlayerPropMarketForSport(propSportFilter, market),
    );
    return scoped;
  }, [availablePropMarkets, propSportFilter]);
  const isPickEmView = primaryMode === "player_props" && viewMode === "pickem";
  const activeFilterChips = useMemo(() => {
    const chips: string[] = [];
    const activeTimeFilter = primaryMode === "player_props" ? appliedPlayerPropsTimeFilter : timeFilter;
    const activeSportFilter = primaryMode === "player_props" ? appliedPlayerPropsSportFilter : propSportFilter;
    const activeMarketFilter = primaryMode === "player_props" ? appliedPlayerPropsMarketFilter : propMarketFilter;
    const activeSearchValue = primaryMode === "player_props" ? appliedPlayerPropsSearchQuery : searchQuery.trim();
    if (activeTimeFilter !== "today") {
      const label =
        activeTimeFilter === "upcoming"
          ? "Upcoming"
          : activeTimeFilter === "all_games"
            ? "All Games"
            : "Closed Today";
      chips.push(`Time: ${label}`);
    }
    if (primaryMode === "promos") {
      if (!sameStringSet(selectedPromoBooks, DEFAULT_PROMO_BOOKS)) {
        chips.push(`Books: ${selectedPromoBooks.length}`);
      }
    } else {
      const activeBooks = primaryMode === "player_props" ? appliedPlayerPropsBooks : selectedBooks;
      const defaultBooks = primaryMode === "straight_bets" ? DEFAULT_STRAIGHT_BET_BOOKS : DEFAULT_PLAYER_PROP_BOOKS;
      if (!sameStringSet(activeBooks, defaultBooks)) {
        chips.push(`Books: ${activeBooks.length}`);
      }
    }
    if ((primaryMode === "player_props" || primaryMode === "promos") && activeSportFilter !== "all") {
      const label = SPORT_KEY_TO_DISPLAY[activeSportFilter] ?? activeSportFilter;
      chips.push(primaryMode === "promos" ? `Prop Sport: ${label}` : `Sport: ${label}`);
    }
    if ((primaryMode === "player_props" || primaryMode === "promos") && activeMarketFilter !== "all") {
      const label = formatPlayerPropMarketLabel(activeMarketFilter);
      chips.push(primaryMode === "promos" ? `Prop Market: ${label}` : `Market: ${label}`);
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
    appliedPlayerPropsSportFilter,
    appliedPlayerPropsTimeFilter,
    isPickEmView,
    primaryMode,
    propMarketFilter,
    propSideFilter,
    propSportFilter,
    searchQuery,
    selectedBooks,
    selectedPromoBooks,
    straightBetMarketFilter,
    timeFilter,
  ]);

  const resetFilters = () => {
    setTimeFilter("today");
    setPropSportFilter("all");
    setPropMarketFilter("all");
    setPropSideFilter("all");
    setStraightBetMarketFilter("all");
    setSearchQuery("");
    if (primaryMode === "straight_bets") {
      setSelectedGameLineBooks(DEFAULT_STRAIGHT_BET_BOOKS);
    } else if (primaryMode === "promos") {
      setSelectedPromoBooks(DEFAULT_PROMO_BOOKS);
    } else {
      setSelectedPropBooks(DEFAULT_PLAYER_PROP_BOOKS);
    }
  };

  useEffect(() => {
    if (!isPickEmView && propSideFilter !== "all") {
      setPropSideFilter("all");
    }
  }, [isPickEmView, propSideFilter]);

  useEffect(() => {
    if (primaryMode === "straight_bets") return;
    if (propMarketFilter === "all") return;
    if (availablePropMarketsForSport.includes(propMarketFilter)) return;
    setPropMarketFilter("all");
  }, [availablePropMarketsForSport, primaryMode, propMarketFilter]);

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
      : primaryMode === "promos"
        ? (results.length < filteredSides.length) || (playerPropsBrowse.hasNextPage ?? false)
        : results.length < filteredSides.length;
  const isLoadingMore = (primaryMode === "player_props" || primaryMode === "promos") ? activePlayerPropsIsFetchingNextPage : false;

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
    if (primaryMode === "promos") {
      const nextVisibleCount = visibleCount + 10;
      if (nextVisibleCount >= filteredSides.length && (playerPropsBrowse.hasNextPage ?? false)) {
        void playerPropsBrowse.fetchNextPage();
      }
      setVisibleCount(nextVisibleCount);
      return;
    }
    setVisibleCount((v) => v + 10);
  };

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleViewModeChange = (mode: MarketsViewMode) => {
    setViewMode(mode);
    setVisibleCount(10);
    setSearchQuery("");
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
      void sendAnalyticsEvent({
        eventName: "log_bet_opened",
        route: "/",
        appArea: "scanner",
        properties: {
          surface: actionSide.surface,
          drawer_mode: tutorialBoardActive ? "tutorial_practice" : "standard",
          tutorial_mode: tutorialBoardActive,
        },
      });
      setDrawerInitialValues(betData);
      setDrawerPracticeMode(tutorialBoardActive);
      setDrawerKey(Date.now());
      setDrawerOpen(true);
    })();
  };

  const handleBetLogged = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.boardSurface("straight_bets") });
    queryClient.invalidateQueries({ queryKey: ["board_player_props"] });
    queryClient.invalidateQueries({ queryKey: ["board_promos"] });
    clearScannerReviewCandidate();
    if (tutorialMode) {
      applyOnboardingEvent.mutate({
        event: "complete_step",
        step: ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
      });
    }
  };

  const handleReviewSavedCandidate = () => {
    if (!scannerReviewCandidate) return;
    void sendAnalyticsEvent({
      eventName: "log_bet_opened",
      route: "/",
      appArea: "scanner",
      properties: {
        surface: scannerReviewCandidate.surface,
        drawer_mode: tutorialBoardActive ? "tutorial_practice" : "standard",
        tutorial_mode: tutorialBoardActive,
        source: "saved_candidate",
      },
    });
    setDrawerInitialValues(scannerReviewCandidate.bet);
    setDrawerPracticeMode(tutorialBoardActive);
    setDrawerKey(Date.now());
    setDrawerOpen(true);
    window.setTimeout(() => {
      highlight(ONBOARDING_HIGHLIGHT_TARGETS.DRAWER_SAVE_PRACTICE_TICKET);
    }, 120);
  };

  const handlePracticeLogged = (bet: TutorialPracticeBet) => {
    saveTutorialPracticeBet(bet);
    clearScannerReviewCandidate();
    setDrawerPracticeMode(false);
  };

  const handleDrawerOpenChange = (open: boolean) => {
    setDrawerOpen(open);
    if (!open) {
      setDrawerPracticeMode(false);
    }
  };

  const handleStartTutorial = () => {
    setPrimaryMode("straight_bets");
    setViewMode("opportunities");
    setTimeFilter("today");
    setSearchQuery("");
  };

  const handleDismissCompletionCard = () => {
    setShowCompletionCard(false);
    if (completionQueryFlag) {
      router.replace("/", { scroll: false });
    }
  };

  const handleStartPlaceFlow = (side: MarketSide) => {
    void (async () => {
      const betData = buildScannerLogBetInitialValues({
        side,
        activeLens,
        boostPercent,
        sportDisplayMap: SPORT_KEY_TO_DISPLAY,
        kellyMultiplier,
        bankroll,
      });

      clearScannerReviewCandidate();

      void sendAnalyticsEvent({
        eventName: "log_bet_opened",
        route: "/",
        appArea: "scanner",
        properties: {
          surface: side.surface,
          drawer_mode: tutorialBoardActive ? "tutorial_practice" : "standard",
          tutorial_mode: tutorialBoardActive,
          source: "place_flow",
        },
      });

      setDrawerInitialValues(betData);
      setDrawerPracticeMode(tutorialBoardActive);
      setDrawerKey(Date.now());
      setDrawerOpen(true);
    })();
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
      if (!tutorialMode) {
        toast.success(`Added to slip (${cart.length + 1} ${cart.length + 1 === 1 ? "leg" : "legs"})`);
      }
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
    if (!tutorialMode) {
      toast.success(`Added to slip (${cart.length + 1} ${cart.length + 1 === 1 ? "leg" : "legs"})`, {
        description: `${card.player_name} ${sideLabel} ${card.line_value} (${pct}%)`,
      });
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="container mx-auto max-w-2xl space-y-3 px-4 py-4">

      <JourneyCoach
        route="home"
        tutorialMode={tutorialMode}
        onReviewScannerPick={handleReviewSavedCandidate}
        onStartTutorial={handleStartTutorial}
      />

      {showCompletionCard && (
        <div className="rounded-lg border border-primary/30 bg-primary/8 overflow-hidden animate-slide-up">
          <div className="h-0.5 w-full bg-gradient-to-r from-primary/40 via-primary to-primary/40" />
          <div className="px-4 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">Tutorial Complete</p>
            <p className="mt-1 text-sm font-semibold text-foreground">You are all set. Good luck out there.</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Onboarding walkthrough finished. You are now on the live Markets workflow.
            </p>
            <button
              type="button"
              className="mt-3 inline-flex h-8 items-center rounded-md border border-border/70 bg-background/80 px-3 text-xs font-medium text-foreground transition-colors hover:bg-background hover:border-border active:scale-[0.98]"
              onClick={handleDismissCompletionCard}
            >
              I&apos;m all set
            </button>
          </div>
        </div>
      )}

      {tutorialBoardActive && primaryMode === "straight_bets" && (
        <div className="rounded-lg border border-primary/25 bg-primary/6 overflow-hidden animate-slide-up">
          <div className="h-0.5 w-full bg-gradient-to-r from-primary/30 via-primary/60 to-primary/30" />
          <div className="px-4 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">Simulated Daily Drops Board</p>
            <p className="mt-1 text-xs text-foreground">
              These lines are tutorial-only samples. No live odds, no real sportsbook deep links, and no real bet logging.
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Live board windows are {dailyDropWindows.mstLabel}, about {dailyDropWindows.localLabel} in your timezone.
            </p>
          </div>
        </div>
      )}

      {/* ── Board header ─────────────────────────────────────────── */}
      <div className="flex min-w-0 items-baseline justify-between gap-2 animate-slide-up" style={{ animationDelay: "0ms", animationFillMode: "both" }}>
        <h1 className="text-sm font-semibold text-foreground">Markets</h1>
        {isBoardLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading…</p>
        ) : boardAgeMinutes !== null ? (
          <p className="flex items-center gap-1 text-[11px] text-muted-foreground" title={boardAgeDetail}>
            <Clock className="h-3 w-3 shrink-0" />
            <span>Updated {formatBoardAge(boardAgeMinutes)} • {nextDropLabel}</span>
          </p>
        ) : isEmptyBoard && !isBoardLoading ? (
          <p className="text-[11px] text-muted-foreground">
            Scans around {dailyDropWindows.localLabel}
          </p>
        ) : null}
      </div>

      {/* ── Row 1: Primary mode ───────────────────────────────────── */}
      <FolderTabs
        className="animate-slide-up"
        triggerClassName="px-3 py-2 text-sm font-semibold"
        value={primaryMode}
        onValueChange={handlePrimaryModeChange}
        items={[
          { value: "player_props", content: "Player Props" },
          { value: "straight_bets", content: "Game Lines" },
          { value: "promos", content: "Promos" },
        ]}
      />

      {/* ── Row 2: Contextual submode ─────────────────────────────── */}
      <div 
        key={`submode-${primaryMode}`}
        className="flex gap-1.5 overflow-x-auto pb-0.5 no-scrollbar animate-fade-in"
      >
        {primaryMode !== "promos" &&
          VIEW_MODES
            .filter((mode) => mode.id !== "pickem" || primaryMode === "player_props")
            .map((mode) => (
              <button
                key={mode.id}
                onClick={() => handleViewModeChange(mode.id)}
                className={cn(
                  "shrink-0 rounded-md border px-3 py-1.5 text-xs font-medium transition-all duration-200 active:scale-95",
                  viewMode === mode.id
                    ? "border-primary/40 bg-primary/12 text-primary shadow-sm"
                    : "border-border/60 bg-card/60 text-muted-foreground hover:text-foreground hover:bg-muted/40 hover:border-border",
                )}
              >
                {mode.label}
              </button>
            ))}
        {primaryMode === "promos" && (
          <div className="w-full space-y-2 animate-fade-in">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {PROMOS_SUBMODES.map((mode, index) => {
                const Icon = mode.icon;
                const isActive = promosSubmode === mode.id;
                return (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => setPromosSubmode(mode.id)}
                    aria-pressed={isActive}
                    style={{ animationDelay: `${index * 40}ms`, animationFillMode: "both" }}
                    className={cn(
                      "rounded border px-3 py-2.5 text-left transition-all duration-200 active:scale-[0.98] animate-slide-up",
                      isActive
                        ? `${mode.activeBg} ${mode.activeBorder}`
                        : "border-border/40 bg-card/60 hover:bg-muted/40",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "inline-flex h-5 w-5 items-center justify-center rounded transition-colors",
                          isActive ? mode.iconText : "text-muted-foreground",
                        )}
                      >
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className={cn("text-xs font-medium", isActive ? mode.activeText : "text-foreground")}>
                        {mode.label}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] leading-tight text-muted-foreground/70">{mode.description}</p>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* ── Search + single Filters control ───────────────────────── */}
      {activeScanData !== null && (
        <div className="space-y-2 animate-slide-up" style={{ animationDelay: "80ms", animationFillMode: "both" }}>
          <div className="flex items-center gap-2">
            <div className="flex flex-1 items-center gap-2 rounded border border-border/60 bg-background/60 px-3 py-2 focus-within:border-border focus-within:bg-background transition-all duration-200">
              <input
                type="text"
                placeholder={
                  primaryMode === "straight_bets"
                    ? "Search teams, events…"
                    : "Search players, teams, books, markets…"
                }
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/50 outline-none"
              />
            </div>
            <button
              type="button"
              onClick={() => setFiltersOpen((prev) => !prev)}
              className={cn(
                "shrink-0 rounded border px-3 py-2 text-[11px] font-semibold uppercase tracking-wider transition-all duration-200 active:scale-95",
                filtersOpen
                  ? "border-primary/50 bg-primary/12 text-primary"
                  : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground",
              )}
            >
              Filters
            </button>
          </div>
          {filtersOpen && (
            <div className="rounded-md border border-border bg-card p-3 space-y-3 animate-slide-up" style={{ animationDelay: "0ms", animationFillMode: "both" }}>
              {primaryMode === "promos" ? (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Books</p>
                  <MultiSelectFilterPills
                    selectedValues={selectedPromoBooks}
                    options={PROMO_BOOKS.map((book) => ({
                      value: book,
                      label: book,
                    }))}
                    onToggleValue={(book) =>
                      setSelectedPromoBooks((prev) => toggleBookSelection(prev, book))
                    }
                    className="flex flex-wrap gap-1.5"
                    baseButtonClassName="rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-200 active:scale-95"
                    activeClassName="text-white"
                    inactiveClassName="bg-muted text-muted-foreground hover:text-foreground"
                    getButtonClassName={(option, active) =>
                      active ? BOOK_COLORS[option.value] || "bg-foreground" : undefined
                    }
                  />
                </div>
              ) : (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Books</p>
                  <MultiSelectFilterPills
                    selectedValues={selectedBooks}
                    options={(primaryMode === "straight_bets" ? STRAIGHT_BET_BOOKS : PLAYER_PROP_BOOKS).map((book) => ({
                      value: book,
                      label: book,
                    }))}
                    onToggleValue={(book) =>
                      setSelectedBooks((prev) => toggleBookSelection(prev, book))
                    }
                    className="flex flex-wrap gap-1.5"
                    baseButtonClassName="rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-200 active:scale-95"
                    activeClassName="text-white"
                    inactiveClassName="bg-muted text-muted-foreground hover:text-foreground"
                    getButtonClassName={(option, active) =>
                      active ? BOOK_COLORS[option.value] || "bg-foreground" : undefined
                    }
                  />
                </div>
              )}
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Time</p>
                <SingleSelectFilterPills<BoardTimeFilter>
                  value={timeFilter}
                  onValueChange={setTimeFilter}
                  options={[
                    { id: "today", label: "Today" },
                    { id: "today_closed", label: "Closed Today" },
                    { id: "upcoming", label: "Upcoming" },
                    { id: "all_games", label: "All Games" },
                  ].map((option) => ({
                    value: option.id as BoardTimeFilter,
                    label: option.label,
                  }))}
                />
              </div>
              {primaryMode === "straight_bets" && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Market Type</p>
                  <SingleSelectFilterPills<StraightBetMarketFilter>
                    value={straightBetMarketFilter}
                    onValueChange={setStraightBetMarketFilter}
                    options={([
                      { id: "all", label: "All" },
                      { id: "h2h", label: "Moneyline" },
                      { id: "spreads", label: "Spreads" },
                      { id: "totals", label: "Totals" },
                    ] as const).map((option) => ({
                      value: option.id,
                      label: option.label,
                    }))}
                  />
                </div>
              )}
              {(primaryMode === "player_props" || primaryMode === "promos") && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                    {primaryMode === "promos" ? "Prop Sport" : "Sport"}
                  </p>
                  <SingleSelectFilterPills
                    value={propSportFilter}
                    onValueChange={setPropSportFilter}
                    options={[
                      { value: "all", label: "All" },
                      ...availablePropSports.map((sport) => ({
                        value: sport,
                        label: SPORT_KEY_TO_DISPLAY[sport] ?? sport,
                      })),
                    ]}
                  />
                </div>
              )}
              {(primaryMode === "player_props" || primaryMode === "promos") && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                    {primaryMode === "promos" ? "Prop Market" : "Market Type"}
                  </p>
                  <SingleSelectFilterPills
                    value={propMarketFilter}
                    onValueChange={setPropMarketFilter}
                    options={[
                      { value: "all", label: "All" },
                      ...availablePropMarketsForSport.map((market) => ({
                        value: market,
                        label: formatMarketTypeLabel(market),
                      })),
                    ]}
                  />
                </div>
              )}
              {isPickEmView && (
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Pick&apos;em Side</p>
                  <SingleSelectFilterPills<"all" | "over" | "under">
                    value={propSideFilter}
                    onValueChange={setPropSideFilter}
                    options={(["all", "over", "under"] as const).map((side) => ({
                      value: side,
                      label: side,
                    }))}
                    getButtonClassName={() => "capitalize"}
                  />
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
        <div className="flex items-center justify-between gap-2 animate-fade-in">
          <div className="flex flex-wrap items-center gap-1.5">
            {activeLens === "profit_boost" && (
              <button
                type="button"
                onClick={() => setBoostSheetOpen(true)}
                className="rounded border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary transition-all duration-200 active:scale-95 hover:bg-primary/15"
                aria-label="Set profit boost percentage"
              >
                Boost {boostPercent}%
              </button>
            )}
            <FilterChipList
              chips={activeFilterChips.map((chip, index) => ({
                key: chip,
                label: chip,
                className: "animate-fade-in",
                style: { animationDelay: `${index * 30}ms`, animationFillMode: "both" },
              }))}
              className="flex flex-wrap items-center gap-1.5"
            />
          </div>
          <button
            type="button"
            onClick={resetFilters}
            className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2 transition-colors"
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
                    "rounded-md border px-2 py-1.5 text-xs font-medium transition-all duration-200 active:scale-95",
                    boostPercent === preset && customBoostInput === ""
                      ? "border-color-pending/40 bg-color-pending-subtle text-color-pending-fg"
                      : "border-border bg-background text-foreground hover:bg-muted/40",
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
                  "h-8 w-20 rounded-md border bg-background px-2 text-xs font-medium text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50",
                  customBoostInput !== "" ? "border-color-pending/40" : "border-border",
                )}
              />
              <span className="text-xs text-muted-foreground">%</span>
            </div>
          </div>
        </SheetContent>
      </Sheet>

      {/* ── Board error ───────────────────────────────────────────── */}
      {boardError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs text-destructive animate-slide-up">
          Failed to load board:{" "}
          {boardError instanceof Error ? boardError.message : "Unknown error"}
        </div>
      )}

      {!boardError && activeSurfaceError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs text-destructive animate-slide-up">
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
        <div className="rounded-lg border border-border bg-card px-4 py-10 text-center animate-slide-up" style={{ animationDelay: "120ms", animationFillMode: "both" }}>
          <Layers className="mx-auto mb-3 h-8 w-8 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">No lines loaded yet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Daily Drops post at {dailyDropWindows.mstLabel}, which is about {dailyDropWindows.localLabel} for you.
          </p>
        </div>
      )}

      {/* 2. Board exists but this surface has no data in today's snapshot */}
      {!activeContentIsLoading && !isBoardLoading && !isEmptyBoard && !boardError && !activeSurfaceError && activeScanData === null && (
        <div className="rounded-lg border border-border bg-card px-4 py-8 text-center animate-slide-up" style={{ animationDelay: "120ms", animationFillMode: "both" }}>
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
        <div 
          key={`results-${primaryMode}-${viewMode}-${promosSubmode}`}
          className="animate-fade-in"
        >
          {(primaryMode !== "straight_bets" || allSides.length > 0) && (
            <ScannerResultsPane
              surface={primaryMode === "player_props" ? "player_props" : "straight_bets"}
              playerPropsView={isPickEmView ? "pickem" : "sportsbooks"}
              activeLens={activeLens}
              tutorialMode={tutorialBoardActive && primaryMode === "straight_bets"}
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
              onStartPlaceFlow={handleStartPlaceFlow}
              onAddPickEmToSlip={handleAddPickEmToSlip}
              bookColors={BOOK_COLORS}
              sportDisplayMap={SPORT_KEY_TO_DISPLAY}
            />
          )}
          {timeFilter === "today" && todayOpenCount === 0 && todayClosedCount > 0 && (
            <div className="rounded-md border border-border bg-card px-3 py-2 text-center animate-slide-up">
              <p className="text-xs text-muted-foreground">No still-open markets today.</p>
              <button
                type="button"
                onClick={() => setTimeFilter("today_closed")}
                className="mt-1 text-xs font-medium text-foreground underline underline-offset-2 transition-colors hover:text-primary"
              >
                View Closed Today
              </button>
            </div>
          )}
        </div>
      )}

      {/* 3b. Featured Game Lines
      {false && primaryMode === "straight_bets" && !activeContentIsLoading && !isBoardLoading && !boardError && (filteredFeaturedGames.length > 0 || allSides.length === 0) && (
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
      */}
      <LogBetDrawer
        key={drawerKey}
        open={drawerOpen}
        onOpenChange={handleDrawerOpenChange}
        initialValues={drawerInitialValues}
        practiceMode={drawerPracticeMode}
        onPracticeLogged={handlePracticeLogged}
        onLogged={handleBetLogged}
      />
    </div>
  );
}
