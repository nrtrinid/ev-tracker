import { createClient } from "./supabase";

const SESSION_STORAGE_KEY = "ev-tracker-analytics-session-id";
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type AnalyticsEventPayload = {
  eventName: string;
  route?: string;
  appArea?: string;
  properties?: Record<string, unknown>;
  dedupeKey?: string;
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
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    accessToken = session?.access_token;
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
        properties: payload.properties ?? {},
        dedupe_key: payload.dedupeKey,
      }),
      keepalive: true,
    });
  } catch {
    // Fire-and-forget: analytics must never break UX.
  }
}
