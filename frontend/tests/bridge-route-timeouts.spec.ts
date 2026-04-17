import { expect, test } from "@playwright/test";

import {
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

  test("admin refresh bridge returns 504 on timeout", async () => {
    const response = await postAdminRefreshMarketsRouteImpl({
      assertAccess: allowAccess,
      backendBaseUrl: "http://backend.internal",
      cronToken: "ops-token",
      fetchFn: timeoutFetch,
      timeoutMs: 10,
    });

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({ detail: "Backend scan trigger timed out" });
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

    expect(calls).toEqual(["http://backend.internal/api/ops/trigger/scan/async"]);
    expect(response.status).toBe(202);
    await expect(response.json()).resolves.toMatchObject({ accepted: true, pending: true, run_id: "run-123" });
  });

  test("admin refresh bridge falls back to sync trigger when async route is unavailable", async () => {
    const calls: string[] = [];
    const fetchFn: typeof fetch = async (input) => {
      calls.push(String(input));
      if (calls.length === 1) {
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
      "http://backend.internal/api/ops/trigger/scan/async",
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
