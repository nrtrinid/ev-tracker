import { expect, test } from "@playwright/test";

import {
  PLAYER_PROP_MARKET_OPTIONS,
  formatPlayerPropMarketBadge,
  formatPlayerPropMarketLabel,
  isSupportedPlayerPropMarketForSport,
} from "@/lib/player-prop-markets";

test.describe("player prop markets", () => {
  test("exposes the six standard front-facing MLB prop markets", async () => {
    expect(PLAYER_PROP_MARKET_OPTIONS).toEqual(
      expect.arrayContaining([
        "pitcher_strikeouts",
        "batter_total_bases",
        "batter_hits",
        "batter_hits_runs_rbis",
        "batter_home_runs",
        "batter_strikeouts",
      ]),
    );
    expect(PLAYER_PROP_MARKET_OPTIONS).not.toEqual(
      expect.arrayContaining([
        "pitcher_strikeouts_alternate",
        "batter_total_bases_alternate",
        "batter_hits_alternate",
        "batter_strikeouts_alternate",
      ]),
    );
  });

  test("formats MLB badges and labels with readable baseball-specific text", async () => {
    expect(formatPlayerPropMarketBadge("pitcher_strikeouts")).toBe("Pitcher Ks");
    expect(formatPlayerPropMarketBadge("batter_total_bases")).toBe("TB");
    expect(formatPlayerPropMarketBadge("batter_hits")).toBe("Hits");
    expect(formatPlayerPropMarketBadge("batter_hits_runs_rbis")).toBe("H+R+RBI");
    expect(formatPlayerPropMarketBadge("batter_home_runs")).toBe("HR");
    expect(formatPlayerPropMarketBadge("batter_strikeouts")).toBe("Batter Ks");

    expect(formatPlayerPropMarketLabel("pitcher_strikeouts")).toBe("Pitcher Strikeouts");
    expect(formatPlayerPropMarketLabel("batter_total_bases")).toBe("Total Bases");
    expect(formatPlayerPropMarketLabel("batter_hits")).toBe("Hits");
    expect(formatPlayerPropMarketLabel("batter_hits_runs_rbis")).toBe("Hits + Runs + RBIs");
    expect(formatPlayerPropMarketLabel("batter_home_runs")).toBe("Home Runs");
    expect(formatPlayerPropMarketLabel("batter_strikeouts")).toBe("Batter Strikeouts");
  });

  test("treats MLB home runs as a supported baseball prop market", async () => {
    expect(isSupportedPlayerPropMarketForSport("baseball_mlb", "batter_home_runs")).toBeTruthy();
    expect(isSupportedPlayerPropMarketForSport("basketball_nba", "batter_home_runs")).toBeFalsy();
  });
});
