import { expect, test } from "@playwright/test";

import {
  PLAYER_PROP_MARKET_OPTIONS,
  formatPlayerPropMarketBadge,
  formatPlayerPropMarketLabel,
  isSupportedPlayerPropMarketForSport,
} from "@/lib/player-prop-markets";

test.describe("player prop markets", () => {
  test("exposes the five standard front-facing MLB prop markets", async () => {
    expect(PLAYER_PROP_MARKET_OPTIONS).toEqual(
      expect.arrayContaining([
        "pitcher_strikeouts",
        "batter_total_bases",
        "batter_total_bases_alternate",
        "batter_hits",
        "batter_hits_runs_rbis",
      ]),
    );
    expect(PLAYER_PROP_MARKET_OPTIONS).not.toEqual(
      expect.arrayContaining([
        "batter_home_runs",
        "batter_strikeouts",
        "pitcher_strikeouts_alternate",
        "batter_hits_alternate",
        "batter_strikeouts_alternate",
      ]),
    );
  });

  test("formats MLB badges and labels with readable baseball-specific text", async () => {
    expect(formatPlayerPropMarketBadge("pitcher_strikeouts")).toBe("Pitcher Ks");
    expect(formatPlayerPropMarketBadge("batter_total_bases")).toBe("TB");
    expect(formatPlayerPropMarketBadge("batter_total_bases_alternate")).toBe("TB ALT");
    expect(formatPlayerPropMarketBadge("batter_hits")).toBe("Hits");
    expect(formatPlayerPropMarketBadge("batter_hits_runs_rbis")).toBe("H+R+RBI");
    expect(formatPlayerPropMarketBadge("batter_home_runs")).toBe("HR");
    expect(formatPlayerPropMarketBadge("batter_strikeouts")).toBe("Batter Ks");

    expect(formatPlayerPropMarketLabel("pitcher_strikeouts")).toBe("Pitcher Strikeouts");
    expect(formatPlayerPropMarketLabel("batter_total_bases")).toBe("Total Bases");
    expect(formatPlayerPropMarketLabel("batter_total_bases_alternate")).toBe("Total Bases Alt");
    expect(formatPlayerPropMarketLabel("batter_hits")).toBe("Hits");
    expect(formatPlayerPropMarketLabel("batter_hits_runs_rbis")).toBe("Hits + Runs + RBIs");
    expect(formatPlayerPropMarketLabel("batter_home_runs")).toBe("Home Runs");
    expect(formatPlayerPropMarketLabel("batter_strikeouts")).toBe("Batter Strikeouts");
  });

  test("keeps total-bases alternate support while home run props stay removed", async () => {
    expect(isSupportedPlayerPropMarketForSport("baseball_mlb", "batter_total_bases_alternate")).toBeTruthy();
    expect(isSupportedPlayerPropMarketForSport("basketball_nba", "batter_total_bases_alternate")).toBeFalsy();
    expect(isSupportedPlayerPropMarketForSport("baseball_mlb", "batter_home_runs")).toBeFalsy();
    expect(isSupportedPlayerPropMarketForSport("basketball_nba", "batter_home_runs")).toBeFalsy();
  });
});
