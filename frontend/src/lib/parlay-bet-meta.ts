import type { Bet, LoggedParlayLeg, ScannerSurface } from "@/lib/types";

export type ParlayLegForDisplay = LoggedParlayLeg;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pick(raw: Record<string, unknown>, camel: string, snake: string): unknown {
  if (camel in raw) return raw[camel];
  if (snake in raw) return raw[snake];
  return undefined;
}

function pickStr(raw: Record<string, unknown>, camel: string, snake: string, fallback = ""): string {
  const v = pick(raw, camel, snake);
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return fallback;
}

function pickNum(raw: Record<string, unknown>, camel: string, snake: string): number | null {
  const v = pick(raw, camel, snake);
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim()) {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function pickNumOrNull(raw: Record<string, unknown>, camel: string, snake: string): number | null {
  const n = pickNum(raw, camel, snake);
  return n;
}

function pickBool(raw: Record<string, unknown>, camel: string, snake: string): boolean | null {
  const v = pick(raw, camel, snake);
  if (typeof v === "boolean") return v;
  return null;
}

function pickStringArray(raw: Record<string, unknown>, camel: string, snake: string): string[] {
  const v = pick(raw, camel, snake);
  if (!Array.isArray(v)) return [];
  return v.filter((item): item is string => typeof item === "string");
}

function normalizeSurface(value: unknown): ScannerSurface {
  const s = String(value ?? "").toLowerCase();
  if (s === "player_props") return "player_props";
  return "straight_bets";
}

/**
 * Normalizes one raw leg object (camelCase or snake_case) into `ParlayCartLeg` + optional CLV fields.
 */
export function normalizeParlayLegFromRaw(raw: unknown, index: number): ParlayLegForDisplay | null {
  if (!isRecord(raw)) return null;

  const id =
    pickStr(raw, "id", "id").trim() ||
    `leg-${index}-${pickStr(raw, "selectionKey", "selection_key").slice(0, 24) || index}`;

  const sportsbook = pickStr(raw, "sportsbook", "sportsbook");
  const display = pickStr(raw, "display", "display");
  const marketKey = pickStr(raw, "marketKey", "market_key");
  const selectionKey = pickStr(raw, "selectionKey", "selection_key");
  const event = pickStr(raw, "event", "event");
  const sport = pickStr(raw, "sport", "sport");

  if (!sportsbook || !display) {
    return null;
  }

  const oddsAmerican = pickNum(raw, "oddsAmerican", "odds_american");
  if (oddsAmerican === null) {
    return null;
  }

  const leg: ParlayLegForDisplay = {
    id,
    surface: normalizeSurface(pick(raw, "surface", "surface")),
    eventId: pickStr(raw, "eventId", "event_id") || null,
    marketKey: marketKey || "h2h",
    selectionKey: selectionKey || id,
    sportsbook,
    oddsAmerican,
    referenceOddsAmerican: pickNumOrNull(raw, "referenceOddsAmerican", "reference_odds_american"),
    referenceTrueProbability: pickNumOrNull(raw, "referenceTrueProbability", "reference_true_probability"),
    referenceSource: pickStr(raw, "referenceSource", "reference_source") || null,
    display,
    event: event || "—",
    sport: sport || "",
    commenceTime: pickStr(raw, "commenceTime", "commence_time"),
    correlationTags: pickStringArray(raw, "correlationTags", "correlation_tags"),
    team: pickStr(raw, "team", "team") || null,
    participantName: pickStr(raw, "participantName", "participant_name") || null,
    participantId: pickStr(raw, "participantId", "participant_id") || null,
    selectionSide: pickStr(raw, "selectionSide", "selection_side") || null,
    lineValue: pickNumOrNull(raw, "lineValue", "line_value"),
    marketDisplay: pickStr(raw, "marketDisplay", "market_display") || null,
    sourceEventId: pickStr(raw, "sourceEventId", "source_event_id") || null,
    sourceMarketKey: pickStr(raw, "sourceMarketKey", "source_market_key") || null,
    sourceSelectionKey: pickStr(raw, "sourceSelectionKey", "source_selection_key") || null,
    selectionMeta: (() => {
      const m = pick(raw, "selectionMeta", "selection_meta");
      return isRecord(m) ? m : null;
    })(),
    latest_reference_odds: pickNumOrNull(raw, "latest_reference_odds", "latest_reference_odds"),
    latest_reference_updated_at:
      pickStr(raw, "latest_reference_updated_at", "latest_reference_updated_at") || null,
    pinnacle_odds_at_close: pickNumOrNull(raw, "pinnacle_odds_at_close", "pinnacle_odds_at_close"),
    reference_updated_at: pickStr(raw, "reference_updated_at", "reference_updated_at") || null,
    clv_ev_percent: pickNumOrNull(raw, "clv_ev_percent", "clv_ev_percent"),
    beat_close: pickBool(raw, "beat_close", "beat_close"),
  };

  return leg;
}

/**
 * Parses `bet.selection_meta.legs` for logged parlay bets. Returns `null` if not a parlay or no legs.
 */
export function parseParlayLegsFromBet(bet: Bet): ParlayLegForDisplay[] | null {
  if (bet.surface !== "parlay") return null;
  const meta = bet.selection_meta;
  if (!isRecord(meta)) return null;
  if (String(meta.type ?? "").toLowerCase() !== "parlay") return null;
  const legsRaw = meta.legs;
  if (!Array.isArray(legsRaw) || legsRaw.length === 0) return null;

  const out: ParlayLegForDisplay[] = [];
  legsRaw.forEach((item, index) => {
    const leg = normalizeParlayLegFromRaw(item, index);
    if (leg) out.push(leg);
  });

  return out.length > 0 ? out : null;
}

export function countParlayLegsForSubtitle(bet: Bet): number | null {
  const fromMeta = parseParlayLegsFromBet(bet);
  if (fromMeta) return fromMeta.length;
  return null;
}
