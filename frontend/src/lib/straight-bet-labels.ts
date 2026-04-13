import type { Bet, MarketSide } from "@/lib/types";

export type StraightBetLabelSide = {
  market_key?: string | null;
  selection_side?: string | null;
  line_value?: number | null;
  team?: string | null;
  event?: string | null;
  sport?: string | null;
};

function formatLineToken(value: number, options?: { includePlus?: boolean }): string {
  const includePlus = options?.includePlus ?? false;
  const normalized = Number.parseFloat(value.toFixed(2));
  const token = `${normalized}`.replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
  if (includePlus && normalized > 0 && !token.startsWith("+")) return `+${token}`;
  return token;
}

function totalUnitForSport(sport: string | null | undefined, lineValue: number): string | null {
  const normalizedSport = (sport ?? "").trim().toLowerCase();
  const singular = Math.abs(lineValue) === 1;

  if (normalizedSport.includes("baseball") || normalizedSport.includes("mlb")) {
    return singular ? "run" : "runs";
  }
  if (
    normalizedSport.includes("basketball") ||
    normalizedSport.includes("nba") ||
    normalizedSport.includes("wnba") ||
    normalizedSport.includes("ncaab")
  ) {
    return singular ? "point" : "points";
  }
  if (
    normalizedSport.includes("football") ||
    normalizedSport.includes("nfl") ||
    normalizedSport.includes("ncaaf")
  ) {
    return singular ? "point" : "points";
  }
  if (normalizedSport.includes("hockey") || normalizedSport.includes("nhl")) {
    return singular ? "goal" : "goals";
  }
  if (normalizedSport.includes("soccer") || normalizedSport.includes("epl") || normalizedSport.includes("mls")) {
    return singular ? "goal" : "goals";
  }

  return null;
}

function looksLikeMatchupLabel(value: string | null | undefined): boolean {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return false;
  return normalized.includes("@") || /\b(vs\.?|v\.?|at)\b/.test(normalized);
}

function eventAlreadyIncludesLine(
  event: string | null | undefined,
  lineValue: number | null | undefined,
  marketKey: string,
): boolean {
  if (lineValue == null || !Number.isFinite(lineValue)) return false;

  const normalizedEvent = String(event || "").trim().toLowerCase();
  if (!normalizedEvent) return false;

  const primaryToken = formatLineToken(lineValue, { includePlus: marketKey === "spreads" }).toLowerCase();
  const fallbackToken = formatLineToken(lineValue).toLowerCase();

  return normalizedEvent.includes(primaryToken) || normalizedEvent.includes(fallbackToken);
}

export function buildStraightBetCardTitle(side: StraightBetLabelSide): string {
  const marketKey = String(side.market_key || "h2h").toLowerCase();
  const selectionSide = String(side.selection_side || "").toLowerCase();

  if (marketKey === "totals") {
    const sideLabel =
      selectionSide === "under"
        ? "Under"
        : selectionSide === "over"
          ? "Over"
          : side.team || "Total";

    if (typeof side.line_value === "number" && Number.isFinite(side.line_value)) {
      const unit = totalUnitForSport(side.sport, side.line_value);
      if (unit) {
        return `${sideLabel} ${formatLineToken(side.line_value)} ${unit}`;
      }
      return `${sideLabel} ${formatLineToken(side.line_value)}`;
    }

    return sideLabel;
  }

  if (marketKey === "spreads") {
    const teamLabel =
      side.team ||
      (selectionSide === "home" ? "Home" : selectionSide === "away" ? "Away" : "Team");

    if (typeof side.line_value === "number" && Number.isFinite(side.line_value)) {
      return `${teamLabel} ${formatLineToken(side.line_value, { includePlus: true })}`;
    }

    return teamLabel;
  }

  return side.team || side.event || "Moneyline";
}

export function buildStraightBetEntryLabel(side: StraightBetLabelSide): string {
  const marketKey = String(side.market_key || "h2h").toLowerCase();
  if (marketKey === "totals" || marketKey === "spreads") {
    return buildStraightBetCardTitle(side);
  }
  return side.team ? `${side.team} ML` : side.event || "Moneyline";
}

export function getStraightBetMarketValue(side: Pick<MarketSide, "market_key">): "ML" | "Spread" | "Total" {
  const marketKey = String(side.market_key || "h2h").toLowerCase();
  if (marketKey === "spreads") return "Spread";
  if (marketKey === "totals") return "Total";
  return "ML";
}

export function getStraightBetMarketDisplay(side: Pick<MarketSide, "market_key">): "Moneyline" | "Spread" | "Total" {
  const marketKey = String(side.market_key || "h2h").toLowerCase();
  if (marketKey === "spreads") return "Spread";
  if (marketKey === "totals") return "Total";
  return "Moneyline";
}

export function buildTrackedBetCardTitle(
  bet: Pick<Bet, "event" | "sport" | "source_market_key" | "selection_side" | "line_value" | "clv_team">,
): string {
  const marketKey = String(bet.source_market_key || "").toLowerCase();
  if (marketKey !== "spreads" && marketKey !== "totals") {
    return bet.event || "Bet";
  }

  if (eventAlreadyIncludesLine(bet.event, bet.line_value, marketKey)) {
    return bet.event || "Bet";
  }

  const fallbackTeam =
    bet.clv_team || (looksLikeMatchupLabel(bet.event) ? null : bet.event);

  if (bet.line_value == null || !Number.isFinite(bet.line_value)) {
    return bet.event || "Bet";
  }

  if (marketKey === "spreads" && !fallbackTeam && !bet.selection_side) {
    return bet.event || "Bet";
  }

  if (marketKey === "totals" && !bet.selection_side && !fallbackTeam) {
    return bet.event || "Bet";
  }

  return buildStraightBetCardTitle({
    market_key: marketKey,
    selection_side: bet.selection_side,
    line_value: bet.line_value,
    team: fallbackTeam,
    event: bet.event,
    sport: bet.sport,
  });
}
