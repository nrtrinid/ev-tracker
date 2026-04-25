import { expect, test } from "@playwright/test";

import {
  getInitialOddsInputSign,
  getSignedOddsInputValue,
  stripOddsInputSign,
} from "@/lib/odds-input";

test.describe("odds input helpers", () => {
  test("preserves explicit negative scanner odds before UI sign state syncs", async () => {
    expect(getInitialOddsInputSign("-115", "+")).toBe(false);
    expect(getSignedOddsInputValue("-115", true)).toBe(-115);
  });

  test("uses the toggle sign for unsigned typed odds", async () => {
    expect(getSignedOddsInputValue("115", true)).toBe(115);
    expect(getSignedOddsInputValue("115", false)).toBe(-115);
  });

  test("strips sign characters from displayed odds text", async () => {
    expect(stripOddsInputSign("-113")).toBe("113");
    expect(stripOddsInputSign("+102")).toBe("102");
  });
});
