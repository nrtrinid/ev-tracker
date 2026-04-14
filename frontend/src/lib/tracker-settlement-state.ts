import type { Bet } from "@/lib/types";
import { isSupportedPlayerPropMarketForSport } from "@/lib/player-prop-markets";

export type TrackerSettlementStateKind =
  | "open_ticket"
  | "awaiting_auto_settle"
  | "needs_grading"
  | "manual_only";

export interface TrackerSettlementState {
  kind: TrackerSettlementStateKind;
  badgeLabel: string;
  title: string;
  description: string;
  showManualControlsByDefault: boolean;
  showStatusBadge: boolean;
}

const AUTO_SETTLE_GRACE_HOURS = 18;
const OPEN_TICKET_BUFFER_HOURS = 4;

function normalizeToken(value: string | null | undefined): string {
  return String(value || "").trim().toLowerCase();
}

function parseIsoDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function getParlayLatestLegStart(bet: Bet): Date | null {
  const meta = bet.selection_meta;
  if (!meta || typeof meta !== "object" || !("legs" in meta)) {
    return null;
  }

  const legs = Array.isArray(meta.legs) ? meta.legs : [];
  let latest: Date | null = null;

  for (const leg of legs) {
    if (!leg || typeof leg !== "object") {
      continue;
    }

    const raw =
      "commenceTime" in leg && typeof leg.commenceTime === "string"
        ? leg.commenceTime
        : "commence_time" in leg && typeof leg.commence_time === "string"
          ? leg.commence_time
          : null;
    const parsed = parseIsoDate(raw);
    if (!parsed) {
      continue;
    }
    if (!latest || parsed > latest) {
      latest = parsed;
    }
  }

  return latest;
}

function hasValidSelectionTime(value: string | null | undefined): boolean {
  return parseIsoDate(value) !== null;
}

function canAutoSettlePlayerPropSelection(input: {
  sportKey: string | null | undefined;
  marketKey: string | null | undefined;
  participantName: string | null | undefined;
  selectionSide: string | null | undefined;
  lineValue: number | null | undefined;
  commenceTime: string | null | undefined;
}): boolean {
  return (
    isSupportedPlayerPropMarketForSport(input.sportKey, input.marketKey) &&
    Boolean(input.participantName) &&
    Boolean(input.selectionSide) &&
    input.lineValue != null &&
    hasValidSelectionTime(input.commenceTime)
  );
}

function canAutoSettleParlay(bet: Bet): boolean {
  const latestLegStart = getParlayLatestLegStart(bet);
  if (!latestLegStart) {
    return false;
  }

  const meta = bet.selection_meta;
  if (!meta || typeof meta !== "object" || !("legs" in meta) || !Array.isArray(meta.legs) || meta.legs.length === 0) {
    return false;
  }

  for (const leg of meta.legs) {
    if (!leg || typeof leg !== "object") {
      return false;
    }

    const surface =
      "surface" in leg && typeof leg.surface === "string"
        ? normalizeToken(leg.surface)
        : "";
    const commenceTime =
      "commenceTime" in leg && typeof leg.commenceTime === "string"
        ? leg.commenceTime
        : "commence_time" in leg && typeof leg.commence_time === "string"
          ? leg.commence_time
          : null;

    if (surface === "straight_bets") {
      const marketKey =
        "marketKey" in leg && typeof leg.marketKey === "string"
          ? normalizeToken(leg.marketKey)
          : "market_key" in leg && typeof leg.market_key === "string"
            ? normalizeToken(leg.market_key)
            : "";
      if (marketKey !== "h2h" || !hasValidSelectionTime(commenceTime)) {
        return false;
      }
      continue;
    }

    if (surface === "player_props") {
      const sportKey =
        "sport" in leg && typeof leg.sport === "string" ? leg.sport : null;
      const marketKey =
        "marketKey" in leg && typeof leg.marketKey === "string"
          ? leg.marketKey
          : "market_key" in leg && typeof leg.market_key === "string"
            ? leg.market_key
            : null;
      const participantName =
        "participantName" in leg && typeof leg.participantName === "string"
          ? leg.participantName
          : "participant_name" in leg && typeof leg.participant_name === "string"
            ? leg.participant_name
            : "display" in leg && typeof leg.display === "string"
              ? leg.display
              : null;
      const selectionSide =
        "selectionSide" in leg && typeof leg.selectionSide === "string"
          ? leg.selectionSide
          : "selection_side" in leg && typeof leg.selection_side === "string"
            ? leg.selection_side
            : null;
      const lineValue =
        "lineValue" in leg && typeof leg.lineValue === "number"
          ? leg.lineValue
          : "line_value" in leg && typeof leg.line_value === "number"
            ? leg.line_value
            : null;

      if (
        !canAutoSettlePlayerPropSelection({
          sportKey,
          marketKey,
          participantName,
          selectionSide,
          lineValue,
          commenceTime,
        })
      ) {
        return false;
      }
      continue;
    }

    return false;
  }

  return true;
}

function getAutoSettleReferenceTime(bet: Bet): Date | null {
  if (normalizeToken(bet.surface) === "parlay") {
    return getParlayLatestLegStart(bet) ?? parseIsoDate(bet.commence_time);
  }
  return parseIsoDate(bet.commence_time);
}

function canAutoSettle(bet: Bet): boolean {
  const surface = normalizeToken(bet.surface);
  const market = normalizeToken(bet.market).replace(/\s+/g, "");

  if (surface === "parlay" || market === "parlay") {
    return canAutoSettleParlay(bet);
  }

  if (surface === "player_props") {
    return canAutoSettlePlayerPropSelection({
      sportKey: bet.clv_sport_key,
      marketKey: bet.source_market_key,
      participantName: bet.participant_name,
      selectionSide: bet.selection_side,
      lineValue: bet.line_value,
      commenceTime: bet.commence_time,
    });
  }

  return (
    market === "ml" &&
    Boolean(bet.clv_team) &&
    Boolean(normalizeToken(bet.clv_sport_key)) &&
    getAutoSettleReferenceTime(bet) !== null
  );
}

export function getTrackerSettlementState(
  bet: Bet,
  nowInput: Date = new Date(),
): TrackerSettlementState {
  const now = Number.isNaN(nowInput.getTime()) ? new Date() : nowInput;

  if (!canAutoSettle(bet)) {
    return {
      kind: "manual_only",
      badgeLabel: "Manual grading needed",
      title: "Manual grading needed",
      description: "This ticket could not be settled automatically.",
      showManualControlsByDefault: true,
      showStatusBadge: true,
    };
  }

  const referenceTime = getAutoSettleReferenceTime(bet);
  if (!referenceTime) {
    return {
      kind: "manual_only",
      badgeLabel: "Manual grading needed",
      title: "Manual grading needed",
      description: "This ticket could not be settled automatically.",
      showManualControlsByDefault: true,
      showStatusBadge: true,
    };
  }

  const elapsedMs = now.getTime() - referenceTime.getTime();
  const elapsedHours = elapsedMs / (1000 * 60 * 60);

  if (elapsedMs < OPEN_TICKET_BUFFER_HOURS * 60 * 60 * 1000) {
    return {
      kind: "open_ticket",
      badgeLabel: "",
      title: "Open ticket",
      description: "Waiting for result.",
      showManualControlsByDefault: false,
      showStatusBadge: false,
    };
  }

  if (elapsedHours >= AUTO_SETTLE_GRACE_HOURS) {
    return {
      kind: "needs_grading",
      badgeLabel: "Manual grading needed",
      title: "Manual grading needed",
      description: "This ticket could not be settled automatically.",
      showManualControlsByDefault: true,
      showStatusBadge: true,
    };
  }

  return {
    kind: "awaiting_auto_settle",
    badgeLabel: "Awaiting auto-settle",
    title: "Awaiting auto-settle",
    description: "Results are in. This ticket should settle shortly.",
    showManualControlsByDefault: false,
    showStatusBadge: true,
  };
}
