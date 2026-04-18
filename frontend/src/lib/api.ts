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
  BoardPromosResponse,
  PlayerPropBoardDetail,
  PlayerPropBoardItem,
  PlayerPropBoardPageResponse,
  PlayerPropBoardPickEmCard,
  ScopedRefreshResponse,
  BackendReadiness,
  OnboardingEventRequest,
  OnboardingState,
  OperatorStatusResponse,
  ParlaySlip,
  ParlaySlipCreate,
  ParlaySlipLogRequest,
  ParlaySlipUpdate,
  ResearchOpportunitySummary,
  ModelCalibrationSummary,
  PickEmResearchSummary,
  OpsTriggerScanResponse,
  OpsTriggerAutoSettleResponse,
  AnalyticsSummary,
  AnalyticsUserDrilldown,
  AltPitcherKLookupResponse,
  ScannerSurface,
} from "./types";
import { getSessionId as getAnalyticsSessionId } from "./analytics";
import { createClient } from "./supabase";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

let browserBurstCorrelationId: string | null = null;
let browserBurstCorrelationExpiry = 0;

function newCorrelationId(): string {
  try {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
  } catch {
    // Fall through to timestamp-based fallback.
  }
  return `corr_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
}

function getCorrelationId(): string {
  if (typeof window === "undefined") return newCorrelationId();

  const now = Date.now();
  if (browserBurstCorrelationId && now < browserBurstCorrelationExpiry) {
    browserBurstCorrelationExpiry = now + 2500;
    return browserBurstCorrelationId;
  }

  browserBurstCorrelationId = newCorrelationId();
  browserBurstCorrelationExpiry = now + 2500;
  return browserBurstCorrelationId;
}

async function getAccessTokenForApi(): Promise<string | null> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (session?.access_token) {
    return session.access_token;
  }

  // After a hard refresh, session hydration can lag by a tick in development.
  await new Promise((resolve) => setTimeout(resolve, 80));

  const {
    data: { session: hydratedSession },
  } = await supabase.auth.getSession();

  return hydratedSession?.access_token ?? null;
}

function buildApiHeaders(options: RequestInit | undefined, extras: {
  correlationId: string;
  analyticsSessionId: string | null;
  accessToken: string | null;
}): HeadersInit {
  return {
    "Content-Type": "application/json",
    "X-Correlation-ID": extras.correlationId,
    ...(extras.analyticsSessionId && { "X-Session-ID": extras.analyticsSessionId }),
    ...(extras.accessToken && { Authorization: `Bearer ${extras.accessToken}` }),
    ...options?.headers,
  };
}

async function fetchAPI<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const correlationId = getCorrelationId();
  const analyticsSessionId = getAnalyticsSessionId();
  const accessToken = await getAccessTokenForApi();

  if (!accessToken) {
    throw new Error("Not authenticated. Sign in and try again.");
  }

  const requestHeaders = buildApiHeaders(options, {
    correlationId,
    analyticsSessionId,
    accessToken,
  });

  let res = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers: requestHeaders,
  });

  if (res.status === 401) {
    try {
      const {
        data: { session: refreshedSession },
      } = await createClient().auth.refreshSession();
      const refreshedToken = refreshedSession?.access_token ?? null;

      if (refreshedToken && refreshedToken !== accessToken) {
        res = await fetch(`${API_URL}${endpoint}`, {
          ...options,
          headers: buildApiHeaders(options, {
            correlationId,
            analyticsSessionId,
            accessToken: refreshedToken,
          }),
        });
      }
    } catch {
      // Fall through to normal error handling below.
    }
  }

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
    const detail =
      typeof error?.error === "string"
        ? error.error
        : typeof error?.detail === "string"
          ? error.detail
          : typeof error?.message === "string"
            ? error.message
            : `API error: ${res.status}`;
    throw new Error(detail);
  }

  return res.json();
}

// ============ Bets API ============

export async function getBets(filters?: {
  sport?: string;
  sportsbook?: string;
  result?: BetResult;
}, paging?: {
  limit?: number;
  offset?: number;
}): Promise<Bet[]> {
  const params = new URLSearchParams();
  if (filters?.sport) params.set("sport", filters.sport);
  if (filters?.sportsbook) params.set("sportsbook", filters.sportsbook);
  if (filters?.result) params.set("result", filters.result);
  if (typeof paging?.limit === "number") params.set("limit", String(paging.limit));
  if (typeof paging?.offset === "number") params.set("offset", String(paging.offset));

  const query = params.toString() ? `?${params.toString()}` : "";
  return fetchAPI<Bet[]>(`/bets${query}`);
}

export async function getAllBetsForStats(): Promise<Bet[]> {
  const pageSize = 1000;
  const allBets: Bet[] = [];
  let offset = 0;

  while (true) {
    const page = await getBets(undefined, { limit: pageSize, offset });
    allBets.push(...page);

    if (page.length < pageSize) {
      return allBets;
    }

    offset += pageSize;
  }
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

export async function getOnboardingState(): Promise<OnboardingState> {
  return fetchAPI<OnboardingState>("/onboarding/state");
}

export async function applyOnboardingEvent(
  payload: OnboardingEventRequest
): Promise<OnboardingState> {
  return fetchAPI<OnboardingState>("/onboarding/events", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function grantBetaAccess(
  inviteCode: string,
  accessTokenOverride?: string | null,
): Promise<{ ok: boolean; granted: boolean }> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (accessTokenOverride) {
    headers.Authorization = `Bearer ${accessTokenOverride}`;
    const res = await fetch(`${API_URL}/beta/access/grant`, {
      method: "POST",
      headers,
      body: JSON.stringify({ invite_code: inviteCode }),
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || `API error: ${res.status}`);
    }

    return res.json();
  }

  return fetchAPI<{ ok: boolean; granted: boolean }>("/beta/access/grant", {
    method: "POST",
    body: JSON.stringify({ invite_code: inviteCode }),
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

function buildBoardPlayerPropsQuery(params: {
  page: number;
  pageSize: number;
  books?: string[];
  timeFilter?: string;
  sport?: string | null;
  market?: string | null;
  search?: string | null;
  tzOffsetMinutes?: number;
}): string {
  const query = new URLSearchParams();
  query.set("page", String(params.page));
  query.set("page_size", String(params.pageSize));
  if (params.books && params.books.length > 0) {
    query.set("books", params.books.join(","));
  }
  if (params.timeFilter) {
    query.set("time_filter", params.timeFilter);
  }
  if (params.sport && params.sport !== "all") {
    query.set("sport", params.sport);
  }
  if (params.market && params.market !== "all") {
    query.set("market", params.market);
  }
  if (params.search && params.search.trim()) {
    query.set("search", params.search.trim());
  }
  if (typeof params.tzOffsetMinutes === "number" && Number.isFinite(params.tzOffsetMinutes)) {
    query.set("tz_offset_minutes", String(params.tzOffsetMinutes));
  }
  return query.toString();
}

export async function getBoardPlayerPropOpportunities(params: {
  page: number;
  pageSize: number;
  books?: string[];
  timeFilter?: string;
  sport?: string | null;
  market?: string | null;
  search?: string | null;
  tzOffsetMinutes?: number;
}): Promise<PlayerPropBoardPageResponse<PlayerPropBoardItem> | null> {
  const query = buildBoardPlayerPropsQuery(params);
  try {
    return await fetchAPI<PlayerPropBoardPageResponse<PlayerPropBoardItem>>(
      `/api/board/latest/player-props/opportunities?${query}`,
    );
  } catch (e) {
    if (e instanceof Error && /not found|missing/i.test(e.message)) return null;
    throw e;
  }
}

export async function getBoardPlayerPropBrowse(params: {
  page: number;
  pageSize: number;
  books?: string[];
  timeFilter?: string;
  sport?: string | null;
  market?: string | null;
  search?: string | null;
  tzOffsetMinutes?: number;
}): Promise<PlayerPropBoardPageResponse<PlayerPropBoardItem> | null> {
  const query = buildBoardPlayerPropsQuery(params);
  try {
    return await fetchAPI<PlayerPropBoardPageResponse<PlayerPropBoardItem>>(
      `/api/board/latest/player-props/browse?${query}`,
    );
  } catch (e) {
    if (e instanceof Error && /not found|missing/i.test(e.message)) return null;
    throw e;
  }
}

export async function getBoardPlayerPropPickem(params: {
  page: number;
  pageSize: number;
  books?: string[];
  timeFilter?: string;
  sport?: string | null;
  market?: string | null;
  search?: string | null;
  tzOffsetMinutes?: number;
}): Promise<PlayerPropBoardPageResponse<PlayerPropBoardPickEmCard> | null> {
  const query = buildBoardPlayerPropsQuery(params);
  try {
    return await fetchAPI<PlayerPropBoardPageResponse<PlayerPropBoardPickEmCard>>(
      `/api/board/latest/player-props/pickem?${query}`,
    );
  } catch (e) {
    if (e instanceof Error && /not found|missing/i.test(e.message)) return null;
    throw e;
  }
}

export async function getBoardPlayerPropDetail(params: {
  selectionKey: string;
  sportsbook: string;
}): Promise<PlayerPropBoardDetail> {
  const query = new URLSearchParams({
    selection_key: params.selectionKey,
    sportsbook: params.sportsbook,
  });
  return fetchAPI<PlayerPropBoardDetail>(`/api/board/latest/player-props/detail?${query.toString()}`);
}

export async function getBoardPromos(limit: number = 300): Promise<BoardPromosResponse> {
  return fetchAPI<BoardPromosResponse>(`/api/board/latest/promos?limit=${encodeURIComponent(String(limit))}`);
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

export async function getAltPitcherKLookup(
  params: {
    player_name: string;
    team?: string | null;
    opponent?: string | null;
    line_value: number;
    game_date?: string | null;
  }
): Promise<AltPitcherKLookupResponse> {
  const query = new URLSearchParams({
    player_name: params.player_name.trim(),
    line_value: String(params.line_value),
  });
  if (params.team?.trim()) query.set("team", params.team.trim());
  if (params.opponent?.trim()) query.set("opponent", params.opponent.trim());
  if (params.game_date?.trim()) query.set("game_date", params.game_date.trim());
  return fetchInternalAPI<AltPitcherKLookupResponse>(`/api/ops/alt-pitcher-k-lookup?${query.toString()}`);
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

/** Admin-only: run the full daily-board refresh through the ops trigger bridge. */
export async function adminRefreshMarkets(): Promise<OpsTriggerScanResponse> {
  const res = await fetch("/api/admin/refresh-markets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
  scope?: "all" | "board_default";
}): Promise<ResearchOpportunitySummary> {
  const qs = new URLSearchParams();
  if (params?.model_version) qs.set("model_version", params.model_version);
  if (params?.capture_class) qs.set("capture_class", params.capture_class);
  if (params?.cohort_mode) qs.set("cohort_mode", params.cohort_mode);
  if (params?.scope) qs.set("scope", params.scope);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return fetchInternalAPI<ResearchOpportunitySummary>(`/api/ops/research-opportunities/summary${suffix}`);
}

export async function getModelCalibrationSummary(): Promise<ModelCalibrationSummary> {
  return fetchInternalAPI<ModelCalibrationSummary>("/api/ops/model-calibration/summary");
}

export async function getPickEmResearchSummary(): Promise<PickEmResearchSummary> {
  return fetchInternalAPI<PickEmResearchSummary>("/api/ops/pickem-research/summary");
}

export async function getAnalyticsSummary(windowDays: number = 7): Promise<AnalyticsSummary> {
  const safeWindowDays = Math.max(1, Math.min(30, Math.trunc(windowDays || 7)));
  return fetchInternalAPI<AnalyticsSummary>(`/api/ops/analytics/summary?window_days=${safeWindowDays}`);
}

export async function getAnalyticsUserDrilldown(
  windowDays: number = 7,
  maxUsers: number = 25,
  timelineLimit: number = 12,
): Promise<AnalyticsUserDrilldown> {
  const safeWindowDays = Math.max(1, Math.min(30, Math.trunc(windowDays || 7)));
  const safeMaxUsers = Math.max(1, Math.min(100, Math.trunc(maxUsers || 25)));
  const safeTimelineLimit = Math.max(1, Math.min(30, Math.trunc(timelineLimit || 12)));
  return fetchInternalAPI<AnalyticsUserDrilldown>(
    `/api/ops/analytics/users?window_days=${safeWindowDays}&max_users=${safeMaxUsers}&timeline_limit=${safeTimelineLimit}`
  );
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
