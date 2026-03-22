import type { ScannerSurface } from "@/lib/types";

export interface ScannerSurfaceConfig {
  id: ScannerSurface;
  label: string;
  tagline: string;
  teaser: string;
  path: string;
  searchPlaceholder: string;
  resultLabel: string;
  emptyLabel: string;
  supportsLensSelector: boolean;
  supportsProfitBoost: boolean;
  isPublic: boolean;
}

export const STRAIGHT_BETS_SURFACE: ScannerSurfaceConfig = {
  id: "straight_bets",
  label: "Straight Bets",
  tagline: "Best +EV straight bets across your selected books",
  teaser: "Moneyline scanning, bonus-bet lensing, and price-aware logging.",
  path: "/scanner/straight_bets",
  searchPlaceholder: "Search team",
  resultLabel: "+EV Lines",
  emptyLabel: "No +EV lines right now. Check back when lines move.",
  supportsLensSelector: true,
  supportsProfitBoost: true,
  isPublic: true,
};

export const PLAYER_PROPS_SURFACE: ScannerSurfaceConfig = {
  id: "player_props",
  label: "Player Props",
  tagline: "Player markets with fair odds, line matching, and log-ready selections",
  teaser: "Points, rebounds, assists, and threes from sharp-vs-book comparisons.",
  path: "/scanner/player_props",
  searchPlaceholder: "Search player or market",
  resultLabel: "Player Props",
  emptyLabel: "No player props match your current books and filters yet.",
  supportsLensSelector: false,
  supportsProfitBoost: false,
  isPublic: false,
};

export const SCANNER_SURFACES: ScannerSurfaceConfig[] = [
  STRAIGHT_BETS_SURFACE,
  PLAYER_PROPS_SURFACE,
];

export const PUBLIC_SCANNER_SURFACES = SCANNER_SURFACES.filter((surface) => surface.isPublic);

export function getScannerSurface(surface: string): ScannerSurfaceConfig {
  return SCANNER_SURFACES.find((entry) => entry.id === surface) ?? STRAIGHT_BETS_SURFACE;
}
