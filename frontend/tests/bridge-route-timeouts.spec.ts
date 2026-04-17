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
