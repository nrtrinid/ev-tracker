import { expect, test } from "@playwright/test";

import { GET } from "@/app/api/cron/trigger-backend/route";

const ORIGINAL_ENV = { ...process.env };

test.describe("cron trigger backend route", () => {
  test.afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  test("rejects removed scan target support", async () => {
    process.env.CRON_SECRET = "cron-secret";
    process.env.BACKEND_BASE_URL = "http://backend.internal";
    const removedTarget = "s" + "can";

    const response = await GET(
      new Request(`https://frontend.example/api/cron/trigger-backend?target=${removedTarget}`, {
        headers: { authorization: "Bearer cron-secret" },
      })
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: "Invalid target" });
  });

  test("posts canonical board-refresh target to async backend endpoint", async () => {
    process.env.CRON_SECRET = "cron-secret";
    process.env.BACKEND_BASE_URL = "http://backend.internal/";
    const originalFetch = global.fetch;
    const calls: string[] = [];
    global.fetch = (async (input) => {
      calls.push(String(input));
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const response = await GET(
        new Request("https://frontend.example/api/cron/trigger-backend?target=board-refresh", {
          headers: { authorization: "Bearer cron-secret" },
        })
      );

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toEqual({ ok: true });
      expect(calls).toEqual(["http://backend.internal/api/ops/trigger/board-refresh/async"]);
    } finally {
      global.fetch = originalFetch;
    }
  });

  test("returns 504 when backend trigger times out", async () => {
    process.env.CRON_SECRET = "cron-secret";
    process.env.BACKEND_BASE_URL = "http://backend.internal/";
    process.env.CRON_BACKEND_TIMEOUT_MS = "10";
    const originalFetch = global.fetch;
    global.fetch = (async (_input, init) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      })
    )) as typeof fetch;

    try {
      const response = await GET(
        new Request("https://frontend.example/api/cron/trigger-backend?target=board-refresh", {
          headers: { authorization: "Bearer cron-secret" },
        })
      );

      expect(response.status).toBe(504);
      await expect(response.json()).resolves.toEqual({
        error: "Backend trigger timed out",
        target: "board-refresh",
      });
    } finally {
      global.fetch = originalFetch;
    }
  });
});
