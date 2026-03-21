export type ScannerLens = "standard" | "profit_boost" | "bonus_bet" | "qualifier";

export interface ScannerActionModel {
  primary: {
    kind: "open" | "log";
    label: string;
    href?: string;
    external?: boolean;
  };
  secondary?: {
    kind: "log";
    label: string;
  };
  trustHint?: string;
}

export function normalizeSportsbookDeeplink(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

export function buildScannerActionModel(params: {
  sportsbook: string;
  sportsbookDeeplinkUrl?: string | null;
}): ScannerActionModel {
  const normalizedLink = normalizeSportsbookDeeplink(params.sportsbookDeeplinkUrl);

  if (!normalizedLink) {
    return {
      primary: {
        kind: "log",
        label: "Log Bet",
      },
    };
  }

  return {
    primary: {
      kind: "open",
      label: `Open in ${params.sportsbook}`,
      href: normalizedLink,
      external: true,
    },
    secondary: {
      kind: "log",
      label: "Log Bet",
    },
    trustHint: "Check line before placing",
  };
}

export function shouldShowProfitBoostContextControls(activeLens: ScannerLens): boolean {
  return activeLens === "profit_boost";
}
