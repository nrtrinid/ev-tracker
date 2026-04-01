import { expect, test } from "@playwright/test";

import {
  buildBackendProxyTarget,
  isAllowedBackendProxyPath,
  normalizeBackendProxyPath,
} from "@/lib/server/backend-proxy";

test.describe("backend proxy utils", () => {
  test("normalizes safe catch-all segments into a backend path", async () => {
    expect(normalizeBackendProxyPath(["bets", "123"])).toBe("/bets/123");
    expect(normalizeBackendProxyPath(["api", "board", "latest", "surface"])).toBe(
      "/api/board/latest/surface",
    );
  });

  test("rejects invalid traversal-style proxy paths", async () => {
    expect(normalizeBackendProxyPath([])).toBeNull();
    expect(normalizeBackendProxyPath(["..", "bets"])).toBeNull();
    expect(normalizeBackendProxyPath([".", "ready"])).toBeNull();
  });

  test("allows only the normal app backend path families", async () => {
    expect(isAllowedBackendProxyPath("/bets")).toBeTruthy();
    expect(isAllowedBackendProxyPath("/bets/abc-123/result")).toBeTruthy();
    expect(isAllowedBackendProxyPath("/parlay-slips/slip-1/log")).toBeTruthy();
    expect(isAllowedBackendProxyPath("/api/board/latest/surface")).toBeTruthy();
    expect(isAllowedBackendProxyPath("/api/scan-markets")).toBeTruthy();

    expect(isAllowedBackendProxyPath("/api/ops/status")).toBeFalsy();
    expect(isAllowedBackendProxyPath("/api/cron/trigger-backend")).toBeFalsy();
    expect(isAllowedBackendProxyPath("/api/boardish")).toBeFalsy();
    expect(isAllowedBackendProxyPath("/admin/ops")).toBeFalsy();
  });

  test("builds a stable upstream target with query params intact", async () => {
    expect(
      buildBackendProxyTarget(
        "http://5.78.192.196/",
        "/api/board/latest/surface",
        "?surface=player_props",
      ),
    ).toBe("http://5.78.192.196/api/board/latest/surface?surface=player_props");
  });
});
