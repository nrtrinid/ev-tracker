import type {
  Bet,
  BetCreate,
  BetUpdate,
  BetResult,
  Settings,
  Summary,
  EVCalculation,
  PromoType,
  Transaction,
  TransactionCreate,
  Balance,
  ScanResult,
  BoardResponse,
  ScopedRefreshResponse,
  BackendReadiness,
  OperatorStatusResponse,
  ParlaySlip,
  ParlaySlipCreate,
  ParlaySlipLogRequest,
  ParlaySlipUpdate,
  ResearchOpportunitySummary,
  ModelCalibrationSummary,
  AdminMarketRefreshResponse,
  OpsTriggerAutoSettleResponse,
  ScannerSurface,
} from "./types";
import { createClient } from "./supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const res = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token && {
        Authorization: `Bearer ${session.access_token}`,
      }),
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }

  return res.json();
}

async function fetchInternalAPI<T>(endpoint: string): Promise<T> {
  const res = await fetch(endpoint, {
    method: "GET",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: "Unknown error" }));
    throw new Error(error.error || `API error: ${res.status}`);
  }

  return res.json();
}

// ============ Bets API ============

export async function getBets(filters?: {
  sport?: string;
  sportsbook?: string;
  result?: BetResult;
}): Promise<Bet[]> {
  const params = new URLSearchParams();
  if (filters?.sport) params.set("sport", filters.sport);
  if (filters?.sportsbook) params.set("sportsbook", filters.sportsbook);
  if (filters?.result) params.set("result", filters.result);

  const query = params.toString() ? `?${params.toString()}` : "";
  return fetchAPI<Bet[]>(`/bets${query}`);
}

export async function getBet(id: string): Promise<Bet> {
  return fetchAPI<Bet>(`/bets/${id}`);
}

export async function createBet(bet: BetCreate): Promise<Bet> {
  return fetchAPI<Bet>("/bets", {
    method: "POST",
    body: JSON.stringify(bet),
  });
}

export async function updateBet(id: string, bet: BetUpdate): Promise<Bet> {
  return fetchAPI<Bet>(`/bets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(bet),
  });
}

export async function updateBetResult(
  id: string,
  result: BetResult
): Promise<Bet> {
  return fetchAPI<Bet>(`/bets/${id}/result?result=${result}`, {
    method: "PATCH",
  });
}

export async function deleteBet(id: string): Promise<{ deleted: boolean }> {
  return fetchAPI(`/bets/${id}`, { method: "DELETE" });
}

// ============ Summary API ============

export async function getSummary(): Promise<Summary> {
  return fetchAPI<Summary>("/summary");
}

// ============ Settings API ============

export async function getSettings(): Promise<Settings> {
  return fetchAPI<Settings>("/settings");
}

export async function updateSettings(
  settings: Partial<Settings>
): Promise<Settings> {
  return fetchAPI<Settings>("/settings", {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}

// ============ EV Calculator API ============

export async function calculateEV(params: {
  odds_american: number;
  stake: number;
  promo_type: PromoType;
  boost_percent?: number;
  winnings_cap?: number;
}): Promise<EVCalculation> {
  const searchParams = new URLSearchParams({
    odds_american: params.odds_american.toString(),
    stake: params.stake.toString(),
    promo_type: params.promo_type,
  });

  if (params.boost_percent !== undefined) {
    searchParams.set("boost_percent", params.boost_percent.toString());
  }
  if (params.winnings_cap !== undefined) {
    searchParams.set("winnings_cap", params.winnings_cap.toString());
  }

  return fetchAPI<EVCalculation>(`/calculate-ev?${searchParams.toString()}`);
}

// ============ Transactions API ============

export async function getTransactions(sportsbook?: string): Promise<Transaction[]> {
  const params = sportsbook ? `?sportsbook=${encodeURIComponent(sportsbook)}` : "";
  return fetchAPI<Transaction[]>(`/transactions${params}`);
}

export async function createTransaction(transaction: TransactionCreate): Promise<Transaction> {
  return fetchAPI<Transaction>("/transactions", {
    method: "POST",
    body: JSON.stringify(transaction),
  });
}

export async function deleteTransaction(id: string): Promise<void> {
  await fetchAPI<{ deleted: boolean }>(`/transactions/${id}`, {
    method: "DELETE",
  });
}

// ============ Balances API ============

export async function getBalances(): Promise<Balance[]> {
  return fetchAPI<Balance[]>("/balances");
}

// ============ Scanner API ============

/** Full scan across all sports. Backend uses 20-min TTL cache per sport. */
export async function scanMarkets(surface: ScannerSurface = "straight_bets"): Promise<ScanResult> {
  return fetchAPI<ScanResult>(`/api/scan-markets?surface=${encodeURIComponent(surface)}`);
}

export async function getLatestScan(surface: ScannerSurface = "straight_bets"): Promise<ScanResult | null> {
  try {
    return await fetchAPI<ScanResult>(`/api/scan-latest?surface=${encodeURIComponent(surface)}`);
  } catch (e) {
    // Backend returns 404 with detail "No scans yet" when nothing has been persisted.
    if (e instanceof Error && e.message === "No scans yet") return null;
    throw e;
  }
}

// ============ Board API ============

/** Load the canonical board snapshot. Pure DB read — no outbound API calls. */
export async function getBoard(): Promise<BoardResponse> {
  return fetchAPI<BoardResponse>("/api/board/latest");
}

/** Load the per-surface latest payload for lazy board loading. */
export async function getBoardSurface(surface: ScannerSurface): Promise<ScanResult | null> {
  try {
    return await fetchAPI<ScanResult>(`/api/board/latest/surface?surface=${encodeURIComponent(surface)}`);
  } catch (e) {
    // If the backend returns a controlled error or the cache is missing, treat as null and let UI degrade.
    if (e instanceof Error && /not found|missing/i.test(e.message)) return null;
    throw e;
  }
}

/** Trigger a scoped manual refresh for a surface. Rate-limited. Does NOT overwrite board:latest. */
export async function refreshBoard(
  scope: ScannerSurface = "player_props",
): Promise<ScopedRefreshResponse> {
  return fetchAPI<ScopedRefreshResponse>(
    `/api/board/refresh?scope=${encodeURIComponent(scope)}`,
    { method: "POST" },
  );
}

// ============ System Status API ============

const DEFAULT_READINESS_CHECKS: BackendReadiness["checks"] = {
  supabase_env: false,
  db_connectivity: false,
  scheduler_state: false,
  scheduler_freshness: false,
};

export async function getBackendReadiness(): Promise<BackendReadiness> {
  try {
    const res = await fetch(`${API_URL}/ready`, {
      method: "GET",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
      },
    });

    const payload = await res.json().catch(() => null);

    if (res.ok) {
      return {
        status: "ready",
        timestamp: payload?.timestamp ?? null,
        checks: payload?.checks ?? DEFAULT_READINESS_CHECKS,
        scheduler_freshness: payload?.scheduler_freshness,
      };
    }

    if (res.status === 503 && payload?.detail) {
      const detail = payload.detail;
      return {
        status: "not_ready",
        timestamp: detail?.timestamp ?? payload?.timestamp ?? null,
        checks: detail?.checks ?? DEFAULT_READINESS_CHECKS,
        scheduler_freshness: detail?.scheduler_freshness,
        detail: "Backend is in a degraded state",
      };
    }

    return {
      status: "unreachable",
      timestamp: null,
      checks: DEFAULT_READINESS_CHECKS,
      detail: `Unexpected readiness response (${res.status})`,
    };
  } catch {
    return {
      status: "unreachable",
      timestamp: null,
      checks: DEFAULT_READINESS_CHECKS,
      detail: "Backend is currently unreachable",
    };
  }
}

export async function getOperatorStatus(): Promise<OperatorStatusResponse> {
  return fetchInternalAPI<OperatorStatusResponse>("/api/ops/status");
}

function formatFetchErrorDetail(error: { detail?: unknown }, status: number): string {
  const d = error.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((item: { msg?: string }) => item?.msg)
      .filter(Boolean)
      .join(", ");
  }
  return `API error: ${status}`;
}

/** Admin-only: full manual scan for straight bets and player props (no per-user scan rate limit). */
export async function adminRefreshMarkets(): Promise<AdminMarketRefreshResponse> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const res = await fetch("/api/admin/refresh-markets", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token && {
        Authorization: `Bearer ${session.access_token}`,
      }),
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(formatFetchErrorDetail(error, res.status));
  }

  return res.json();
}

/** Admin-only: run the same auto-settle job as the ops/cron trigger (grades pending bets). */
export async function adminTriggerAutoSettle(): Promise<OpsTriggerAutoSettleResponse> {
  const res = await fetch("/api/admin/trigger-auto-settle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(formatFetchErrorDetail(error, res.status));
  }

  return res.json();
}

export async function getResearchOpportunitySummary(params?: {
  model_version?: string;
  capture_class?: string;
  cohort_mode?: string;
}): Promise<ResearchOpportunitySummary> {
  const qs = new URLSearchParams();
  if (params?.model_version) qs.set("model_version", params.model_version);
  if (params?.capture_class) qs.set("capture_class", params.capture_class);
  if (params?.cohort_mode) qs.set("cohort_mode", params.cohort_mode);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return fetchInternalAPI<ResearchOpportunitySummary>(`/api/ops/research-opportunities/summary${suffix}`);
}

export async function getModelCalibrationSummary(): Promise<ModelCalibrationSummary> {
  return fetchInternalAPI<ModelCalibrationSummary>("/api/ops/model-calibration/summary");
}

// ============ Parlay Slips API ============

export async function getParlaySlips(): Promise<ParlaySlip[]> {
  return fetchAPI<ParlaySlip[]>("/parlay-slips");
}

export async function createParlaySlip(payload: ParlaySlipCreate): Promise<ParlaySlip> {
  return fetchAPI<ParlaySlip>("/parlay-slips", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateParlaySlip(id: string, payload: ParlaySlipUpdate): Promise<ParlaySlip> {
  return fetchAPI<ParlaySlip>(`/parlay-slips/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteParlaySlip(id: string): Promise<{ deleted: boolean; id: string }> {
  return fetchAPI<{ deleted: boolean; id: string }>(`/parlay-slips/${id}`, {
    method: "DELETE",
  });
}

export async function logParlaySlip(id: string, payload: ParlaySlipLogRequest): Promise<Bet> {
  return fetchAPI<Bet>(`/parlay-slips/${id}/log`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
