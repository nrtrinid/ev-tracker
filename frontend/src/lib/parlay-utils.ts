import type { ParlayCartLeg, ParlayPricingPreview, ParlayWarning } from "@/lib/types";
import { americanToDecimal, calculateStealthStake, decimalToAmerican } from "@/lib/utils";

const PICKEM_UNAVAILABLE = "Pick'em slip — pricing is handled in your app.";

export function isPickEmParlayLeg(leg: ParlayCartLeg): boolean {
  const meta = leg.selectionMeta;
  if (!meta || typeof meta !== "object") {
    return false;
  }
  const key = (meta as { pickEmComparisonKey?: unknown }).pickEmComparisonKey;
  return typeof key === "string" && key.trim().length > 0;
}

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

function truncateText(value: string, maxLength: number) {
  const normalized = value.trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  if (maxLength <= 3) {
    return normalized.slice(0, maxLength);
  }
  return `${normalized.slice(0, maxLength - 3).trimEnd()}...`;
}

function formatSelectionSide(value: string | null | undefined) {
  const raw = (value ?? "").trim();
  if (!raw) {
    return null;
  }

  const normalized = raw.toLowerCase();
  if (normalized === "over" || normalized === "under" || normalized === "yes" || normalized === "no") {
    return `${normalized[0].toUpperCase()}${normalized.slice(1)}`;
  }
  return raw;
}

function formatLineValue(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) {
    return null;
  }
  if (Number.isInteger(value)) {
    return `${value}`;
  }
  return `${Number.parseFloat(value.toFixed(2))}`;
}

function buildParlayLegLabel(leg: ParlayCartLeg) {
  const display = leg.display.trim();
  if (display) {
    return display;
  }

  const participant = (leg.participantName ?? "").trim();
  const selectionSide = formatSelectionSide(leg.selectionSide);
  const lineValue = formatLineValue(leg.lineValue);
  const team = (leg.team ?? "").trim();
  const marketDisplay = (leg.marketDisplay ?? "").trim();
  const marketKey = normalizeText(leg.marketKey);

  if (participant && selectionSide && lineValue != null) {
    return `${participant} ${selectionSide} ${lineValue}`;
  }
  if (participant && selectionSide) {
    return `${participant} ${selectionSide}`;
  }
  if (participant && marketDisplay) {
    return `${participant} ${marketDisplay}`;
  }
  if (team && (marketKey === "h2h" || normalizeText(marketDisplay) === "moneyline")) {
    return `${team} ML`;
  }
  if (team && selectionSide && lineValue != null) {
    return `${team} ${selectionSide} ${lineValue}`;
  }
  if (team && marketDisplay) {
    return `${team} ${marketDisplay}`;
  }
  if (team) {
    return team;
  }
  if (marketDisplay) {
    return marketDisplay;
  }
  if (leg.event.trim()) {
    return leg.event.trim();
  }
  return "Parlay leg";
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

function getLegReferenceTrueProbability(leg: ParlayCartLeg): number | null {
  const explicitTrueProbability = leg.referenceTrueProbability;
  if (
    typeof explicitTrueProbability === "number" &&
    Number.isFinite(explicitTrueProbability) &&
    explicitTrueProbability > 0 &&
    explicitTrueProbability < 1
  ) {
    return explicitTrueProbability;
  }

  if (leg.referenceOddsAmerican == null || !Number.isFinite(leg.referenceOddsAmerican)) {
    return null;
  }

  const referenceDecimal = americanToDecimal(leg.referenceOddsAmerican);
  if (!Number.isFinite(referenceDecimal) || referenceDecimal <= 1) {
    return null;
  }
  return 1 / referenceDecimal;
}

export function buildParlayWarnings(cart: ParlayCartLeg[]): ParlayWarning[] {
  if (cart.length > 0 && cart.every(isPickEmParlayLeg)) {
    return [];
  }

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

type BuildParlayPreviewOptions = {
  bankroll?: number | null;
  kellyMultiplier?: number | null;
};

function calculateKellyFraction(trueProbability: number, decimalOdds: number): number {
  if (!Number.isFinite(trueProbability) || !Number.isFinite(decimalOdds)) {
    return 0;
  }
  if (trueProbability <= 0 || trueProbability >= 1 || decimalOdds <= 1) {
    return 0;
  }
  const edge = (trueProbability * decimalOdds - 1) / (decimalOdds - 1);
  if (!Number.isFinite(edge) || edge <= 0) {
    return 0;
  }
  return edge;
}

export function buildParlayPreview(
  cart: ParlayCartLeg[],
  stakeInput: number,
  options?: BuildParlayPreviewOptions,
): ParlayPricingPreview | null {
  if (cart.length === 0) {
    return null;
  }

  const stake = Number.isFinite(stakeInput) && stakeInput > 0 ? stakeInput : null;

  if (cart.every(isPickEmParlayLeg)) {
    return {
      slipMode: "pickem_notes",
      legCount: cart.length,
      sportsbook: null,
      combinedDecimalOdds: null,
      combinedAmericanOdds: null,
      stake,
      totalPayout: null,
      profit: null,
      estimatedFairDecimalOdds: null,
      estimatedFairAmericanOdds: null,
      estimatedTrueProbability: null,
      estimatedEvPercent: null,
      baseKellyFraction: null,
      rawKellyStake: null,
      stealthKellyStake: null,
      bankrollUsed:
        typeof options?.bankroll === "number" && Number.isFinite(options.bankroll) && options.bankroll > 0
          ? options.bankroll
          : null,
      kellyMultiplierUsed:
        typeof options?.kellyMultiplier === "number" &&
        Number.isFinite(options.kellyMultiplier) &&
        options.kellyMultiplier > 0
          ? options.kellyMultiplier
          : null,
      estimateAvailable: false,
      estimateUnavailableReason: PICKEM_UNAVAILABLE,
      hasBlockingCorrelation: false,
      warnings: [],
    };
  }

  const warnings = buildParlayWarnings(cart);
  const hasBlockingCorrelation = warnings.some((warning) => warning.severity === "blocking");
  const combinedDecimalOdds = cart.reduce(
    (running, leg) => running * americanToDecimal(leg.oddsAmerican),
    1
  );
  const sportsbook = cart[0]?.sportsbook ?? null;
  const totalPayout = stake != null ? stake * combinedDecimalOdds : null;
  const profit = totalPayout != null && stake != null ? totalPayout - stake : null;
  const referenceTrueProbabilities = cart.map((leg) => getLegReferenceTrueProbability(leg));
  const missingReferencePrice = referenceTrueProbabilities.some((value) => value == null);

  let estimatedFairDecimalOdds: number | null = null;
  let estimatedFairAmericanOdds: number | null = null;
  let estimatedTrueProbability: number | null = null;
  let estimatedEvPercent: number | null = null;
  let baseKellyFraction: number | null = null;
  let rawKellyStake: number | null = null;
  let stealthKellyStake: number | null = null;
  let estimateAvailable = false;
  let estimateUnavailableReason: string | null = null;
  const bankroll =
    typeof options?.bankroll === "number" && Number.isFinite(options.bankroll) && options.bankroll > 0
      ? options.bankroll
      : null;
  const kellyMultiplier =
    typeof options?.kellyMultiplier === "number" && Number.isFinite(options.kellyMultiplier) && options.kellyMultiplier > 0
      ? options.kellyMultiplier
      : null;

  if (hasBlockingCorrelation) {
    estimateUnavailableReason = "Correlation warning";
  } else if (missingReferencePrice) {
    estimateUnavailableReason = "Missing reference price";
  } else {
    const resolvedReferenceTrueProbabilities = referenceTrueProbabilities as number[];
    estimatedTrueProbability = resolvedReferenceTrueProbabilities.reduce(
      (running, probability) => running * probability,
      1
    );
    estimatedFairDecimalOdds = estimatedTrueProbability > 0 ? 1 / estimatedTrueProbability : null;
    estimatedFairAmericanOdds =
      estimatedFairDecimalOdds != null && Number.isFinite(estimatedFairDecimalOdds)
        ? decimalToAmerican(estimatedFairDecimalOdds)
        : null;
    estimatedEvPercent =
      estimatedTrueProbability != null
        ? (estimatedTrueProbability * combinedDecimalOdds - 1) * 100
        : null;
    baseKellyFraction =
      estimatedTrueProbability != null
        ? calculateKellyFraction(estimatedTrueProbability, combinedDecimalOdds)
        : null;
    if (
      baseKellyFraction != null &&
      baseKellyFraction > 0 &&
      bankroll != null &&
      kellyMultiplier != null
    ) {
      rawKellyStake = baseKellyFraction * kellyMultiplier * bankroll;
      stealthKellyStake = calculateStealthStake(rawKellyStake);
    }
    estimateAvailable = estimatedTrueProbability != null;
  }

  return {
    slipMode: "standard",
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
    baseKellyFraction,
    rawKellyStake,
    stealthKellyStake,
    bankrollUsed: bankroll,
    kellyMultiplierUsed: kellyMultiplier,
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

export function getParlayRecommendedStake(preview: ParlayPricingPreview | null | undefined): number | null {
  if (!preview?.estimateAvailable) {
    return null;
  }
  return preview.stealthKellyStake ?? 0;
}

export function buildParlayEventSummary(cart: ParlayCartLeg[], sportsbook?: string | null): string {
  const book = sportsbook ?? cart[0]?.sportsbook ?? "Parlay";
  if (cart.length === 0) {
    return `${book} parlay`;
  }

  const maxLabelLength = cart.length === 1 ? 72 : cart.length === 2 ? 32 : cart.length === 3 ? 22 : 24;
  const legLabels = cart.map((leg) => truncateText(buildParlayLegLabel(leg), maxLabelLength));
  if (legLabels.length === 1) {
    return legLabels[0];
  }

  if (legLabels.length === 2) {
    return `${legLabels[0]} + ${legLabels[1]}`;
  }

  const fullSummary = legLabels.join(" + ");
  if (legLabels.length === 3 && fullSummary.length <= 72) {
    return fullSummary;
  }

  return `${legLabels[0]} + ${legLabels[1]} + ${cart.length - 2} more`;
}
