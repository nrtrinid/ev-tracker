import type {
  Bet,
  BetCreate,
  BetUpdate,
  BetResult,
  Settings,
  Summary,
  EVCalculation,
  PromoType,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `API error: ${res.status}`);
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
