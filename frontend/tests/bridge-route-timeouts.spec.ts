import { expect, test } from "@playwright/test";

import {
  getAnalyticsSummaryRouteImpl,
  getAnalyticsUsersRouteImpl,
  getOpsStatusRouteImpl,
  postAdminRefreshMarketsRouteImpl,
  postAdminTriggerAutoSettleRouteImpl,
  proxyRequestImpl,
} from "@/lib/server/bridge-route-impl";

type AdminAccessResult = {
  ok: boolean;
  email: string | null;
  error?: "unauthenticated" | "allowlist_not_configured" | "forbidden";
};

function abortError(): Error {
  const error = new Error("timeout");
  error.name = "AbortError";
  return error;
}

const timeoutFetch: typeof fetch = async () => {
  throw abortError();
};

const allowAccess = async (): Promise<AdminAccessResult> => ({
  ok: true,
  email: "ops@example.com",
});

const denyAccess = async (): Promise<AdminAccessResult> => ({
  ok: false,
  email: null,
  error: "unauthenticated",
});

test.describe("bridge route timeout handling", () => {
  test("backend proxy route returns 504 on timeout", async () => {
    const response = await proxyRequestImpl(
      new Request("https://frontend.example/api/backend/health", { method: "GET" }),
      { params: { path: ["health"] } },
      {
        backendBaseUrl: "http://backend.internal",
        fetchFn: timeoutFetch,
        timeoutMs: 10,
      }
    );

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({ detail: "Backend request timed out" });
  });

  test("ops status bridge returns 504 on timeout", async () => {
    const response = await getOpsStatusRouteImpl({
      assertAccess: allowAccess,
      backendBaseUrl: "http://backend.internal",
      cronToken: "ops-token",
      fetchFn: timeoutFetch,
      timeoutMs: 10,
    });

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({ error: "Operator status request timed out" });
  });

  test("analytics summary bridge returns 504 on timeout", async () => {
    const response = await getAnalyticsSummaryRouteImpl(
      new Request("https://frontend.example/api/ops/analytics/summary?window_days=7"),
      {
        assertAccess: allowAccess,
        backendBaseUrl: "http://backend.internal",
        cronToken: "ops-token",
        fetchFn: timeoutFetch,
        timeoutMs: 10,
      }
    );

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({ error: "Analytics summary request timed out" });
  });

  test("analytics users bridge returns 504 on timeout", async () => {
    const response = await getAnalyticsUsersRouteImpl(
      new Request("https://frontend.example/api/ops/analytics/users?window_days=7"),
      {
        assertAccess: allowAccess,
        backendBaseUrl: "http://backend.internal",
        cronToken: "ops-token",
        fetchFn: timeoutFetch,
        timeoutMs: 10,
      }
    );

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({ error: "Analytics users request timed out" });
  });

  test("analytics summary bridge rejects unauthenticated access before calling backend", async () => {
    const response = await getAnalyticsSummaryRouteImpl(
      new Request("https://frontend.example/api/ops/analytics/summary?window_days=7"),
      {
        assertAccess: denyAccess,
        backendBaseUrl: "http://backend.internal",
        cronToken: "ops-token",
        fetchFn: async () => {
          throw new Error("backend should not be called");
        },
      }
    );

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({ error: "Forbidden" });
  });

  test("analytics users bridge returns 500 when backend base url is missing", async () => {
    const response = await getAnalyticsUsersRouteImpl(
      new Request("https://frontend.example/api/ops/analytics/users?window_days=7"),
      {
        assertAccess: allowAccess,
        cronToken: "ops-token",
      }
    );

    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toMatchObject({ error: "BACKEND_BASE_URL not configured" });
  });

  test("analytics summary bridge forwards query string and backend error payload", async () => {
    const calls: string[] = [];
    const response = await getAnalyticsSummaryRouteImpl(
      new Request("https://frontend.example/api/ops/analytics/summary?window_days=7&audience=all"),
      {
        assertAccess: allowAccess,
        backendBaseUrl: "http://backend.internal",
        cronToken: "ops-token",
        fetchFn: async (input) => {
          calls.push(String(input));
          return new Response(
            JSON.stringify({ error: "Upstream summary unavailable" }),
            { status: 502, headers: { "content-type": "application/json" } },
          );
        },
        timeoutMs: 10,
      }
    );

    expect(calls).toEqual(["http://backend.internal/api/ops/analytics/summary?window_days=7&audience=all"]);
    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({ error: "Upstream summary unavailable" });
  });

  test("admin refresh bridge returns 504 on timeout", async () => {
    const response = await postAdminRefreshMarketsRouteImpl({
      assertAccess: allowAccess,
      backendBaseUrl: "http://backend.internal",
      cronToken: "ops-token",
      fetchFn: timeoutFetch,
      timeoutMs: 10,
    });

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({ detail: "Backend board refresh trigger timed out" });
  });

  test("admin refresh bridge prefers async trigger endpoint", async () => {
    const calls: string[] = [];
    const fetchFn: typeof fetch = async (input) => {
      calls.push(String(input));
      return new Response(
        JSON.stringify({
          ok: true,
          accepted: true,
          pending: true,
          run_id: "run-123",
          started_at: "2026-04-16T00:00:00Z",
          finished_at: "2026-04-16T00:00:00Z",
          duration_ms: 0,
          board_drop: true,
          errors: [],
          total_sides: null,
          alerts_scheduled: 0,
        }),
        { status: 202, headers: { "content-type": "application/json" } },
      );
    };

    const response = await postAdminRefreshMarketsRouteImpl({
      assertAccess: allowAccess,
      backendBaseUrl: "http://backend.internal",
      cronToken: "ops-token",
      fetchFn,
      timeoutMs: 10,
    });

    expect(calls).toEqual(["http://backend.internal/api/ops/trigger/board-refresh/async"]);
    expect(response.status).toBe(202);
    await expect(response.json()).resolves.toMatchObject({ accepted: true, pending: true, run_id: "run-123" });
  });

  test("admin refresh bridge falls back to sync trigger when async route is unavailable", async () => {
    const calls: string[] = [];
    const fetchFn: typeof fetch = async (input) => {
      calls.push(String(input));
      if (calls.length < 4) {
        return new Response(
          JSON.stringify({ detail: "Not Found" }),
          { status: 404, headers: { "content-type": "application/json" } },
        );
      }
      return new Response(
        JSON.stringify({
          ok: true,
          run_id: "run-sync",
          started_at: "2026-04-16T00:00:00Z",
          finished_at: "2026-04-16T00:01:00Z",
          duration_ms: 60000,
          board_drop: true,
          errors: [],
          total_sides: 42,
          alerts_scheduled: 3,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };

    const response = await postAdminRefreshMarketsRouteImpl({
      assertAccess: allowAccess,
      backendBaseUrl: "http://backend.internal",
      cronToken: "ops-token",
      fetchFn,
      timeoutMs: 10,
    });

    expect(calls).toEqual([
      "http://backend.internal/api/ops/trigger/board-refresh/async",
      "http://backend.internal/api/ops/trigger/scan/async",
      "http://backend.internal/api/ops/trigger/board-refresh",
      "http://backend.internal/api/ops/trigger/scan",
    ]);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ run_id: "run-sync", total_sides: 42 });
  });

  test("admin auto-settle bridge returns 504 on timeout", async () => {
    const response = await postAdminTriggerAutoSettleRouteImpl({
      assertAccess: allowAccess,
      backendBaseUrl: "http://backend.internal",
      cronToken: "ops-token",
      fetchFn: timeoutFetch,
      timeoutMs: 10,
    });

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({ detail: "Backend auto-settle trigger timed out" });
  });
});
