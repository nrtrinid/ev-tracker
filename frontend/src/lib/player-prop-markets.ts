export const PLAYER_PROP_MARKET_OPTIONS = [
  "player_points",
  "player_rebounds",
  "player_assists",
  "player_points_rebounds_assists",
  "player_threes",
  "pitcher_strikeouts",
  "pitcher_strikeouts_alternate",
  "batter_total_bases",
  "batter_total_bases_alternate",
  "batter_hits",
  "batter_hits_alternate",
  "batter_hits_runs_rbis",
  "batter_strikeouts",
  "batter_strikeouts_alternate",
] as const;

export const PLAYER_PROP_SPORT_OPTIONS = [
  "baseball_mlb",
  "basketball_nba",
] as const;

const PLAYER_PROP_MARKET_SPORTS: Record<string, string[]> = {
  player_points: ["basketball_nba"],
  player_rebounds: ["basketball_nba"],
  player_assists: ["basketball_nba"],
  player_points_rebounds_assists: ["basketball_nba"],
  player_threes: ["basketball_nba"],
  pitcher_strikeouts: ["baseball_mlb"],
  pitcher_strikeouts_alternate: ["baseball_mlb"],
  batter_total_bases: ["baseball_mlb"],
  batter_total_bases_alternate: ["baseball_mlb"],
  batter_hits: ["baseball_mlb"],
  batter_hits_alternate: ["baseball_mlb"],
  batter_hits_runs_rbis: ["baseball_mlb"],
  batter_strikeouts: ["baseball_mlb"],
  batter_strikeouts_alternate: ["baseball_mlb"],
};

const PLAYER_PROP_MARKET_BADGES: Record<string, string> = {
  player_points: "PTS",
  player_rebounds: "REB",
  player_assists: "AST",
  player_points_rebounds_assists: "PRA",
  player_threes: "3PM",
  pitcher_strikeouts: "P K",
  pitcher_strikeouts_alternate: "P K ALT",
  batter_total_bases: "TB",
  batter_total_bases_alternate: "TB ALT",
  batter_hits: "H",
  batter_hits_alternate: "H ALT",
  batter_hits_runs_rbis: "H+R+RBI",
  batter_strikeouts: "B K",
  batter_strikeouts_alternate: "B K ALT",
};

const PLAYER_PROP_MARKET_LABELS: Record<string, string> = {
  player_points: "Points",
  player_rebounds: "Rebounds",
  player_assists: "Assists",
  player_points_rebounds_assists: "PRA",
  player_threes: "Threes",
  pitcher_strikeouts: "Pitcher Strikeouts",
  pitcher_strikeouts_alternate: "Pitcher Strikeouts Alt",
  batter_total_bases: "Total Bases",
  batter_total_bases_alternate: "Total Bases Alt",
  batter_hits: "Hits",
  batter_hits_alternate: "Hits Alt",
  batter_hits_runs_rbis: "Hits + Runs + RBIs",
  batter_strikeouts: "Batter Strikeouts",
  batter_strikeouts_alternate: "Batter Strikeouts Alt",
};

const PLAYER_PROP_SPORT_LABELS: Record<string, string> = {
  baseball_mlb: "MLB",
  basketball_nba: "NBA",
};

export function formatPlayerPropMarketBadge(marketKey: string | undefined | null): string {
  const key = (marketKey ?? "").trim();
  if (PLAYER_PROP_MARKET_BADGES[key]) return PLAYER_PROP_MARKET_BADGES[key];
  if (!key) return "PROP";
  return key.replace(/^player_/, "").replaceAll("_", " ").toUpperCase();
}

export function isSupportedPlayerPropMarketForSport(
  sportKey: string | undefined | null,
  marketKey: string | undefined | null,
): boolean {
  const normalizedSport = String(sportKey ?? "").trim().toLowerCase();
  const normalizedMarket = String(marketKey ?? "").trim();
  if (!normalizedSport || !normalizedMarket) {
    return false;
  }
  return Boolean(PLAYER_PROP_MARKET_SPORTS[normalizedMarket]?.includes(normalizedSport));
}

export function formatPlayerPropSportLabel(sportKey: string | undefined | null): string {
  const key = String(sportKey ?? "").trim().toLowerCase();
  if (PLAYER_PROP_SPORT_LABELS[key]) return PLAYER_PROP_SPORT_LABELS[key];
  if (!key) return "All Sports";
  return key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatPlayerPropMarketLabel(marketKey: string | undefined | null): string {
  const key = (marketKey ?? "").trim();
  if (PLAYER_PROP_MARKET_LABELS[key]) return PLAYER_PROP_MARKET_LABELS[key];
  if (!key) return "Prop";
  const normalized = key.startsWith("player_") ? key.slice("player_".length) : key;
  return normalized.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
