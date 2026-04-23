import { createClient } from "./supabase";

const SESSION_STORAGE_KEY = "ev-tracker-analytics-session-id";
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const MAX_DEDUPE_KEY_LENGTH = 180;

type AnalyticsDedupeScope = "raw" | "user_or_session";

type AnalyticsEventPayload = {
  eventName: string;
  route?: string;
  appArea?: string;
  properties?: Record<string, unknown>;
  dedupeKey?: string;
  dedupeScope?: AnalyticsDedupeScope;
  sessionId?: string | null;
};

function newSessionId(): string {
  try {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
  } catch {
    // Fall through to timestamp fallback.
  }
  return `sess_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
}

function trimmedString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().replace(/%$/, "");
    if (!normalized) {
      return null;
    }
    const parsed = Number(normalized);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function edgeBucketForValue(value: unknown): string | null {
  const evPercentage = coerceNumber(value);
  if (evPercentage === null) {
    return null;
  }
  if (evPercentage < 0.5) return "0-0.5%";
  if (evPercentage < 1) return "0.5-1%";
  if (evPercentage < 2) return "1-2%";
  if (evPercentage < 4) return "2-4%";
  return "4%+";
}

function normalizeAnalyticsProperties(properties?: Record<string, unknown>): Record<string, unknown> {
  const base = { ...(properties ?? {}) };

  const originSurface = trimmedString(base.origin_surface) ?? trimmedString(base.surface);
  if (originSurface && trimmedString(base.origin_surface) === null) {
    base.origin_surface = originSurface;
  }

  const book = trimmedString(base.book) ?? trimmedString(base.sportsbook);
  if (book && trimmedString(base.book) === null) {
    base.book = book;
  }

  const market =
    trimmedString(base.market)
    ?? trimmedString(base.source_market_key)
    ?? trimmedString(base.market_key);
  if (market && trimmedString(base.market) === null) {
    base.market = market;
  }

  const opportunityId =
    trimmedString(base.opportunity_id)
    ?? trimmedString(base.opportunity_key)
    ?? trimmedString(base.source_selection_key)
    ?? trimmedString(base.selection_key);
  if (opportunityId && trimmedString(base.opportunity_id) === null) {
    base.opportunity_id = opportunityId;
  }

  const edgeBucket =
    trimmedString(base.edge_bucket)
    ?? edgeBucketForValue(base.ev_percentage ?? base.scan_ev_percent_at_log);
  if (edgeBucket && trimmedString(base.edge_bucket) === null) {
    base.edge_bucket = edgeBucket;
  }

  return base;
}

function scopedDedupeKey(
  dedupeKey: string | undefined,
  scope: AnalyticsDedupeScope,
  actorKey: string | null,
): string | undefined {
  const base = trimmedString(dedupeKey);
  if (!base) {
    return undefined;
  }
  const scoped = scope === "user_or_session" && actorKey ? `${actorKey}:${base}` : base;
  return scoped.slice(0, MAX_DEDUPE_KEY_LENGTH);
}

export function getSessionId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const existing = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (existing && existing.trim()) {
    return existing;
  }

  const created = newSessionId();
  window.sessionStorage.setItem(SESSION_STORAGE_KEY, created);
  return created;
}

export async function sendAnalyticsEvent(payload: AnalyticsEventPayload): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }

  const eventName = payload.eventName.trim();
  if (!eventName) {
    return;
  }

  const sessionId = payload.sessionId ?? getSessionId();
  if (!sessionId) {
    return;
  }

  const supabase = createClient();
  let accessToken: string | undefined;
  let actorKey: string | null = sessionId ? `session:${sessionId}` : null;
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    accessToken = session?.access_token;
    const userId = trimmedString(session?.user?.id);
    if (userId) {
      actorKey = `user:${userId}`;
    }
  } catch {
    // Ignore auth lookup failures for non-blocking analytics.
  }

  try {
    await fetch(`${API_URL}/analytics/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Session-ID": sessionId,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify({
        event_name: eventName,
        session_id: sessionId,
        route: payload.route,
        app_area: payload.appArea,
        properties: normalizeAnalyticsProperties(payload.properties),
        dedupe_key: scopedDedupeKey(payload.dedupeKey, payload.dedupeScope ?? "raw", actorKey),
      }),
      keepalive: true,
    });
  } catch {
    // Fire-and-forget: analytics must never break UX.
  }
}
