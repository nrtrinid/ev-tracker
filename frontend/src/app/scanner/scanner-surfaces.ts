export type ScannerSurfaceId = "straight_bets";

export interface ScannerSurfaceConfig {
  id: ScannerSurfaceId;
  label: string;
  tagline: string;
  teaser: string;
}

export const STRAIGHT_BETS_SURFACE: ScannerSurfaceConfig = {
  id: "straight_bets",
  label: "Straight Bets",
  tagline: "Best +EV lines across your selected books",
  teaser: "Props + Parlay Helper coming soon",
};
