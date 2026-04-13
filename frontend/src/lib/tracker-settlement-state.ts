import type { Bet } from "@/lib/types";

export type TrackerSettlementStateKind =
  | "awaiting_auto_settle"
  | "needs_grading"
  | "manual_only";

export interface TrackerSettlementState {
  kind: TrackerSettlementStateKind;
  badgeLabel: string;
  title: string;
  description: string;
  showManualControlsByDefault: boolean;
}

const AUTO_SETTLE_GRACE_HOURS = 18;

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

function getAutoSettleReferenceTime(bet: Bet): Date | null {
  if (normalizeToken(bet.surface) === "parlay") {
    return getParlayLatestLegStart(bet) ?? parseIsoDate(bet.commence_time);
  }
  return parseIsoDate(bet.commence_time);
}

function canAutoSettle(bet: Bet): boolean {
  const surface = normalizeToken(bet.surface);
  const market = normalizeToken(bet.market).replace(/\s+/g, "");
  const sportKey = normalizeToken(bet.clv_sport_key);

  if (surface === "parlay" || market === "parlay") {
    return getParlayLatestLegStart(bet) !== null;
  }

  if (surface === "player_props") {
    return (
      sportKey === "basketball_nba" &&
      Boolean(bet.source_market_key) &&
      Boolean(bet.participant_name) &&
      Boolean(bet.selection_side) &&
      bet.line_value != null &&
      getAutoSettleReferenceTime(bet) !== null
    );
  }

  return (
    market === "ml" &&
    Boolean(bet.clv_team) &&
    Boolean(sportKey) &&
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
      badgeLabel: "Manual only",
      title: "Manual grading",
      description:
        "This ticket will stay open until you grade it yourself. Use manual settlement when the result is final.",
      showManualControlsByDefault: true,
    };
  }

  const referenceTime = getAutoSettleReferenceTime(bet);
  if (!referenceTime) {
    return {
      kind: "manual_only",
      badgeLabel: "Manual only",
      title: "Manual grading",
      description:
        "This ticket is missing settle metadata, so it should be closed manually when the game is final.",
      showManualControlsByDefault: true,
    };
  }

  const elapsedMs = now.getTime() - referenceTime.getTime();
  const elapsedHours = elapsedMs / (1000 * 60 * 60);

  if (elapsedMs < 0) {
    return {
      kind: "awaiting_auto_settle",
      badgeLabel: "Auto-settle",
      title: "Open ticket",
      description:
        "This ticket is still waiting on game time. Eligible bets usually settle automatically after results post.",
      showManualControlsByDefault: false,
    };
  }

  if (elapsedHours >= AUTO_SETTLE_GRACE_HOURS) {
    return {
      kind: "needs_grading",
      badgeLabel: "Needs grading",
      title: "Needs manual review",
      description:
        "This ticket is still open well after game time. The auto-settler may have missed it, so manual grading is ready.",
      showManualControlsByDefault: true,
    };
  }

  return {
    kind: "awaiting_auto_settle",
    badgeLabel: "Auto-settle",
    title: "Awaiting auto-settle",
    description:
      "Eligible tickets usually settle automatically after the game finishes. Manual grading is still available if you need it.",
    showManualControlsByDefault: false,
  };
}
