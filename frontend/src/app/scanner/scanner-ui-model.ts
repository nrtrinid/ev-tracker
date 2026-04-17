import type { SportsbookDeeplinkLevel } from "@/lib/types";

export type ScannerLens = "standard" | "profit_boost" | "bonus_bet" | "qualifier";

const SPORTSBOOK_HOMEPAGES: Record<string, string> = {
  BetMGM: "https://sports.betmgm.com/",
  "BetOnline.ag": "https://www.betonline.ag/sportsbook",
  Bovada: "https://www.bovada.lv/sports",
  Caesars: "https://www.caesars.com/sportsbook",
  DraftKings: "https://sportsbook.draftkings.com/",
  "ESPN Bet": "https://sportsbook.thescore.bet/",
  FanDuel: "https://sportsbook.fanduel.com/",
};

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

const BETMGM_STATE_TEMPLATE_HOST_REGEX = /(https?:\/\/)sports\.\{state\}\.betmgm\.com(?=[:\/]|$)/i;

function canonicalizeBetmgmTemplateHost(value: string): string {
  return value.replace(BETMGM_STATE_TEMPLATE_HOST_REGEX, (_, protocol: string) => {
    return `${protocol}sports.betmgm.com`;
  });
}

export function normalizeSportsbookDeeplink(value: string | null | undefined): string | null {
  if (!value) return null;
  const candidate = canonicalizeBetmgmTemplateHost(value.trim());
  if (candidate.includes("{") || candidate.includes("}")) {
    return null;
  }
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

function normalizeSportsbookDeeplinkLevel(
  value: SportsbookDeeplinkLevel | null | undefined,
  hasLink: boolean
): SportsbookDeeplinkLevel | null {
  if (!hasLink) return null;
  if (value === "selection" || value === "market" || value === "event" || value === "homepage") {
    return value;
  }
  // Backward compatibility for older cached payloads that only stored a bookmaker/event URL.
  return "event";
}

export function buildScannerActionModel(params: {
  sportsbook: string;
  sportsbookDeeplinkUrl?: string | null;
  sportsbookDeeplinkLevel?: SportsbookDeeplinkLevel | null;
}): ScannerActionModel {
  const explicitLink = normalizeSportsbookDeeplink(params.sportsbookDeeplinkUrl);
  const explicitLevel = normalizeSportsbookDeeplinkLevel(
    params.sportsbookDeeplinkLevel,
    Boolean(explicitLink)
  );
  const homepageFallback = normalizeSportsbookDeeplink(SPORTSBOOK_HOMEPAGES[params.sportsbook]);
  const normalizedLink = explicitLink ?? homepageFallback;
  const normalizedLevel =
    explicitLink && explicitLevel
      ? explicitLevel
      : homepageFallback
        ? "homepage"
        : null;

  if (!normalizedLink || !normalizedLevel) {
    return {
      primary: {
        kind: "log",
        label: "Review & Log",
      },
    };
  }

  const actionCopyByLevel: Record<SportsbookDeeplinkLevel, { label: string; trustHint: string }> = {
    selection: {
      label: `Place at ${params.sportsbook}`,
      trustHint: "Place the ticket at the book, then come back here to log it.",
    },
    market: {
      label: `Open Market at ${params.sportsbook}`,
      trustHint: "This opens the market at the book, so double-check the bet slip before you log it.",
    },
    event: {
      label: `Open Event at ${params.sportsbook}`,
      trustHint: "This opens the event at the book, so find the line there before you log it.",
    },
    homepage: {
      label: `Open ${params.sportsbook}`,
      trustHint: "This opens the sportsbook home page, so navigate to the game before you log it.",
    },
  };

  return {
    primary: {
      kind: "open",
      label: actionCopyByLevel[normalizedLevel].label,
      href: normalizedLink,
      external: true,
    },
    secondary: {
      kind: "log",
      label: "Review & Log",
    },
    trustHint: actionCopyByLevel[normalizedLevel].trustHint,
  };
}

export function shouldShowProfitBoostContextControls(activeLens: ScannerLens): boolean {
  return activeLens === "profit_boost";
}

export function canAddScannerLensToParlayCart(activeLens: ScannerLens): boolean {
  return activeLens === "standard" || activeLens === "qualifier";
}
