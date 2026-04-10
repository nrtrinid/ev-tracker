import { expect, test } from "@playwright/test";

import { expandTeamAliasSearchQuery, matchesTeamAliasSearch } from "@/lib/team-search-aliases";

test.describe("team search aliases", () => {
  test("matches abbreviations to full team names", async () => {
    expect(
      matchesTeamAliasSearch("okc", ["Los Angeles Lakers @ Oklahoma City Thunder"]),
    ).toBeTruthy();
  });

  test("matches full team names to abbreviations", async () => {
    expect(
      matchesTeamAliasSearch("oklahoma city", ["LAL @ OKC"]),
    ).toBeTruthy();
  });

  test("expands unique aliases for backend search", async () => {
    expect(expandTeamAliasSearchQuery("okc")).toBe("Oklahoma City Thunder");
  });

  test("does not rewrite ambiguous aliases", async () => {
    expect(expandTeamAliasSearchQuery("atl")).toBe("atl");
  });
});
