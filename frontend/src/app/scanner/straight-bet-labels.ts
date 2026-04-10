import type { MarketSide } from "@/lib/types";

type StraightBetLabelSide = Pick<
  MarketSide,
  "market_key" | "selection_side" | "line_value" | "team" | "event" | "sport"
>;

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

  if (normalizedSport.includes("baseball")) {
    return singular ? "run" : "runs";
  }
  if (normalizedSport.includes("basketball") || normalizedSport.includes("football")) {
    return singular ? "point" : "points";
  }
  if (normalizedSport.includes("hockey") || normalizedSport.includes("soccer")) {
    return singular ? "goal" : "goals";
  }

  return null;
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
