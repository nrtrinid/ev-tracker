export const SPORTSBOOK_BADGE_COLORS: Record<string, string> = {
  DraftKings: "bg-draftkings",
  FanDuel: "bg-fanduel",
  BetMGM: "bg-betmgm",
  Caesars: "bg-caesars",
  "ESPN Bet": "bg-espnbet",
  Fanatics: "bg-fanatics",
  "Hard Rock": "bg-hardrock",
  bet365: "bg-bet365",
};

export const SPORTSBOOK_TEXT_COLORS: Record<string, string> = {
  DraftKings: "text-draftkings",
  FanDuel: "text-fanduel",
  BetMGM: "text-betmgm",
  Caesars: "text-caesars",
  "ESPN Bet": "text-espnbet",
  Fanatics: "text-fanatics",
  "Hard Rock": "text-hardrock",
  bet365: "text-bet365",
};

export const SPORTSBOOK_ABBREVIATIONS: Record<string, string> = {
  DraftKings: "DK",
  FanDuel: "FD",
  BetMGM: "MGM",
  Caesars: "CZR",
  "ESPN Bet": "ESPN",
  Fanatics: "FAN",
  "Hard Rock": "HR",
  bet365: "B365",
};

export const SPORTSBOOK_CHART_COLORS: Record<string, string> = {
  DraftKings: "#4CBB17",
  FanDuel: "#0E7ACA",
  BetMGM: "#C5A562",
  Caesars: "#C49A6C",
  "ESPN Bet": "#ED174C",
  Fanatics: "#0047BB",
  "Hard Rock": "#FDB913",
  bet365: "#00843D",
};

export const MARKET_VIG_DEFAULTS: Record<string, number> = {
  ML: 0.045,
  Spread: 0.045,
  Total: 0.045,
  Parlay: 0.15,
  Prop: 0.09,
  Futures: 0.2,
  SGP: 0.2,
};

export function sportsbookAbbrev(name: string): string {
  return SPORTSBOOK_ABBREVIATIONS[name] || name.slice(0, 3).toUpperCase();
}
