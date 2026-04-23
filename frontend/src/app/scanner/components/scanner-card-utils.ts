type ScannerDuplicateState = "new" | "better_now" | "already_logged" | "logged_elsewhere" | null | undefined;

type ScannerDuplicateBadgeTone = "semantic" | "legacy";

const SPORTSBOOK_ABBREVIATIONS: Record<string, string> = {
  DraftKings: "DK",
  FanDuel: "FD",
  BetMGM: "MGM",
  Caesars: "CZR",
  Bovada: "BVD",
  "BetOnline.ag": "BOL",
  "ESPN Bet": "ESPN",
};

export function formatScannerGameTime(isoString: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function abbreviateSportsbookLabel(
  name: string | null | undefined,
  fallback = "Book",
): string {
  const label = String(name || "").trim();
  if (!label) return fallback;
  return SPORTSBOOK_ABBREVIATIONS[label] || label;
}

export function formatScannerProbabilityPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function getScannerDuplicateBadge(
  state: ScannerDuplicateState,
  tone: ScannerDuplicateBadgeTone = "semantic",
): { label: string; className: string } | null {
  if (state === "better_now") {
    return {
      label: "Better Now",
      className:
        tone === "legacy"
          ? "rounded border border-profit/35 bg-profit/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-profit"
          : "rounded border border-color-profit/35 bg-color-profit-subtle px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-color-profit-fg",
    };
  }

  if (state === "already_logged") {
    return {
      label: "Already Placed",
      className:
        tone === "legacy"
          ? "rounded border border-primary/40 bg-primary/12 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary"
          : "rounded border border-color-pending/40 bg-color-pending-subtle px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-color-pending-fg",
    };
  }

  if (state === "logged_elsewhere") {
    return {
      label: "Placed Elsewhere",
      className:
        tone === "legacy"
          ? "rounded border border-primary/35 bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
          : "rounded border border-primary/30 bg-primary/8 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground",
    };
  }

  return null;
}
