import type { ParlayCartLeg, ParlayPricingPreview, ParlayWarning } from "@/lib/types";
import { americanToDecimal, decimalToAmerican } from "@/lib/utils";

const SPORT_DISPLAY_MAP: Record<string, string> = {
  americanfootball_nfl: "NFL",
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
  baseball_mlb: "MLB",
  icehockey_nhl: "NHL",
};

function normalizeText(value: string | null | undefined) {
  return (value ?? "").trim().toLowerCase();
}

function uniqueValues(values: Array<string | null | undefined>) {
  const out: string[] = [];
  for (const value of values) {
    const normalized = (value ?? "").trim();
    if (!normalized || out.includes(normalized)) {
      continue;
    }
    out.push(normalized);
  }
  return out;
}

function getEventGroupKey(leg: ParlayCartLeg) {
  return normalizeText(leg.eventId ?? leg.event);
}

function getMeaningfulCorrelationTags(leg: ParlayCartLeg) {
  const eventGroupKey = getEventGroupKey(leg);
  const marketKey = normalizeText(leg.marketKey);

  return (leg.correlationTags ?? []).filter((rawTag) => {
    const tag = normalizeText(rawTag);
    if (!tag) {
      return false;
    }
    if (tag === eventGroupKey || tag === marketKey) {
      return false;
    }
    if (tag === "h2h" || tag === "moneyline" || tag === "ml") {
      return false;
    }
    return true;
  });
}

export function buildParlayWarnings(cart: ParlayCartLeg[]): ParlayWarning[] {
  if (cart.length <= 1) {
    return [];
  }

  const warnings: ParlayWarning[] = [];
  const seenWarningKeys = new Set<string>();
  const eventGroups = new Map<string, ParlayCartLeg[]>();
  for (const leg of cart) {
    const key = getEventGroupKey(leg);
    if (!key) {
      continue;
    }
    const group = eventGroups.get(key);
    if (group) {
      group.push(leg);
    } else {
      eventGroups.set(key, [leg]);
    }
  }

  for (const groupedLegs of Array.from(eventGroups.values())) {
    if (groupedLegs.length < 2) {
      continue;
    }
    const warningKey = `same-event:${groupedLegs.map((leg) => leg.id).sort().join("|")}`;
    if (seenWarningKeys.has(warningKey)) {
      continue;
    }
    seenWarningKeys.add(warningKey);
    warnings.push({
      code: "same_event_correlation",
      severity: "blocking",
      title: "Same-event legs detected",
      detail: `These ${groupedLegs.length} legs come from the same event, so the fair-odds estimate is hidden instead of assuming independence.`,
      relatedLegIds: groupedLegs.map((leg) => leg.id),
    });
  }

  const tagGroups = new Map<string, ParlayCartLeg[]>();
  for (const leg of cart) {
    const uniqueTagsForLeg = new Set<string>(
      getMeaningfulCorrelationTags(leg)
    );
    for (const tag of Array.from(uniqueTagsForLeg.values())) {
      const group = tagGroups.get(tag);
      if (group) {
        group.push(leg);
      } else {
        tagGroups.set(tag, [leg]);
      }
    }
  }

  const sharedTagGroups: Array<[string, ParlayCartLeg[]]> = Array.from(tagGroups.entries())
    .filter(([, groupedLegs]) => groupedLegs.length > 1)
    .sort((left, right) => right[1].length - left[1].length)
    .slice(0, 2);

  for (const [tag, groupedLegs] of sharedTagGroups) {
    const relatedEventKeys = new Set(groupedLegs.map((leg) => getEventGroupKey(leg)).filter(Boolean));
    if (relatedEventKeys.size <= 1) {
      continue;
    }
    const warningKey = `shared-tag:${tag}:${groupedLegs.map((leg) => leg.id).sort().join("|")}`;
    if (seenWarningKeys.has(warningKey)) {
      continue;
    }
    seenWarningKeys.add(warningKey);
    warnings.push({
      code: "shared_correlation_tag",
      severity: "warning",
      title: "Shared correlation signal",
      detail: `Multiple legs share the tag "${tag}", so it is worth double-checking whether the outcomes move together.`,
      relatedLegIds: groupedLegs.map((leg) => leg.id),
    });
  }

  return warnings;
}

export function buildParlayPreview(cart: ParlayCartLeg[], stakeInput: number): ParlayPricingPreview | null {
  if (cart.length === 0) {
    return null;
  }

  const warnings = buildParlayWarnings(cart);
  const hasBlockingCorrelation = warnings.some((warning) => warning.severity === "blocking");
  const combinedDecimalOdds = cart.reduce(
    (running, leg) => running * americanToDecimal(leg.oddsAmerican),
    1
  );
  const sportsbook = cart[0]?.sportsbook ?? null;
  const stake = Number.isFinite(stakeInput) && stakeInput > 0 ? stakeInput : null;
  const totalPayout = stake != null ? stake * combinedDecimalOdds : null;
  const profit = totalPayout != null && stake != null ? totalPayout - stake : null;
  const missingReferencePrice = cart.some((leg) => leg.referenceOddsAmerican == null);

  let estimatedFairDecimalOdds: number | null = null;
  let estimatedFairAmericanOdds: number | null = null;
  let estimatedTrueProbability: number | null = null;
  let estimatedEvPercent: number | null = null;
  let estimateAvailable = false;
  let estimateUnavailableReason: string | null = null;

  if (hasBlockingCorrelation) {
    estimateUnavailableReason = "Correlation warning";
  } else if (missingReferencePrice) {
    estimateUnavailableReason = "Missing reference price";
  } else {
    estimatedFairDecimalOdds = cart.reduce(
      (running, leg) => running * americanToDecimal(leg.referenceOddsAmerican as number),
      1
    );
    estimatedFairAmericanOdds = decimalToAmerican(estimatedFairDecimalOdds);
    estimatedTrueProbability = estimatedFairDecimalOdds > 0 ? 1 / estimatedFairDecimalOdds : null;
    estimatedEvPercent =
      estimatedTrueProbability != null
        ? (estimatedTrueProbability * combinedDecimalOdds - 1) * 100
        : null;
    estimateAvailable = estimatedTrueProbability != null;
  }

  return {
    legCount: cart.length,
    sportsbook,
    combinedDecimalOdds,
    combinedAmericanOdds: decimalToAmerican(combinedDecimalOdds),
    stake,
    totalPayout,
    profit,
    estimatedFairDecimalOdds,
    estimatedFairAmericanOdds,
    estimatedTrueProbability,
    estimatedEvPercent,
    estimateAvailable,
    estimateUnavailableReason,
    hasBlockingCorrelation,
    warnings,
  };
}

export function buildParlaySportLabel(cart: ParlayCartLeg[]): string {
  const sports = uniqueValues(cart.map((leg) => SPORT_DISPLAY_MAP[leg.sport] ?? leg.sport));
  if (sports.length === 1) {
    return sports[0];
  }
  if (sports.length > 1) {
    return "Mixed";
  }
  return "Other";
}

export function buildParlayEventSummary(cart: ParlayCartLeg[], sportsbook?: string | null): string {
  const book = sportsbook ?? cart[0]?.sportsbook ?? "Parlay";
  if (cart.length === 0) {
    return `${book} parlay`;
  }

  const events = uniqueValues(cart.map((leg) => leg.event));
  if (events.length === 1) {
    return `${cart.length}-leg ${events[0]} parlay`;
  }
  return `${cart.length}-leg ${book} parlay`;
}
