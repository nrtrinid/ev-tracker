import { expect, test } from "@playwright/test";
import { NextRequest } from "next/server";

import { middlewareWithDeps } from "@/middleware";

type TestUser = {
  id: string;
  email?: string | null;
} | null;

type TestSettingsRow = {
  beta_access_granted?: boolean | null;
} | null;

function buildRequest(pathname: string): NextRequest {
  return new NextRequest(`https://example.test${pathname}`);
}

function buildDeps(options?: {
  user?: TestUser;
  settingsRow?: TestSettingsRow;
  betaInviteCode?: string | undefined;
  opsAdminEmails?: string | undefined;
  authTimeoutMs?: number;
  getUser?: () => Promise<{ data: { user: TestUser } }>;
  getSettings?: () => Promise<{ data: TestSettingsRow }>;
  assumeAuthCookie?: boolean;
}) {
  return {
    betaInviteCode: options?.betaInviteCode,
    opsAdminEmails: options?.opsAdminEmails,
    authTimeoutMs: options?.authTimeoutMs,
    assumeAuthCookie: options?.assumeAuthCookie,
    createClient: () => ({
      auth: {
        getUser: options?.getUser ?? (async () => ({
          data: {
            user: options?.user ?? null,
          },
        })),
      },
      from: (_table: string) => ({
        select: (_columns: string) => ({
          eq: (_column: string, _value: string) => ({
            maybeSingle: options?.getSettings ?? (async () => ({
              data: options?.settingsRow ?? null,
            })),
          }),
        }),
      }),
    }),
  };
}

async function runMiddleware(
  pathname: string,
  options?: {
    user?: TestUser;
    settingsRow?: TestSettingsRow;
    betaInviteCode?: string | undefined;
    opsAdminEmails?: string | undefined;
    authTimeoutMs?: number;
    getUser?: () => Promise<{ data: { user: TestUser } }>;
    getSettings?: () => Promise<{ data: TestSettingsRow }>;
    assumeAuthCookie?: boolean;
  }
) {
  return middlewareWithDeps(buildRequest(pathname), buildDeps(options));
}

function expectPassThrough(response: Response) {
  expect(response.headers.get("location")).toBeNull();
  expect(response.headers.get("x-middleware-next")).toBe("1");
}

function expectRedirect(response: Response, pathname: string) {
  expect(response.headers.get("location")).toBe(`https://example.test${pathname}`);
}

test.describe("middleware regression coverage", () => {
  test("redirects unauthenticated protected requests to /login", async () => {
    const response = await runMiddleware("/scanner");

    expectRedirect(response, "/login");
  });

  test("allows unauthenticated requests to /login", async () => {
    const response = await runMiddleware("/login");

    expectPassThrough(response);
  });

  test("allows unauthenticated requests to /beta-access", async () => {
    const response = await runMiddleware("/beta-access");

    expectPassThrough(response);
  });

  test("does not call Supabase for anonymous public auth pages", async () => {
    const response = await middlewareWithDeps(buildRequest("/login"), {
      assumeAuthCookie: false,
      createClient: () => {
        throw new Error("Supabase client should not be created without an auth cookie");
      },
    });

    expectPassThrough(response);
  });

  test("redirects anonymous protected requests without waiting on Supabase", async () => {
    const response = await middlewareWithDeps(buildRequest("/scanner"), {
      assumeAuthCookie: false,
      createClient: () => {
        throw new Error("Supabase client should not be created without an auth cookie");
      },
    });

    expectRedirect(response, "/login");
  });

  test("bypasses auth redirects for cron, backend proxy, and beta-access API routes", async () => {
    await Promise.all([
      runMiddleware("/api/cron/wakeup").then(expectPassThrough),
      runMiddleware("/api/backend/health").then(expectPassThrough),
      runMiddleware("/api/beta-access").then(expectPassThrough),
    ]);
  });

  test("allows authenticated beta-approved users to reach protected pages", async () => {
    const response = await runMiddleware("/scanner", {
      user: { id: "user-1", email: "user@example.com" },
      settingsRow: { beta_access_granted: true },
      betaInviteCode: "Daily Drop",
    });

    expectPassThrough(response);
  });

  test("fails protected requests closed when Supabase auth times out", async () => {
    const response = await runMiddleware("/scanner", {
      authTimeoutMs: 1,
      getUser: () => new Promise(() => {}),
    });

    expectRedirect(response, "/login");
  });

  test("allows public auth pages when Supabase auth times out", async () => {
    const response = await runMiddleware("/login", {
      authTimeoutMs: 1,
      getUser: () => new Promise(() => {}),
    });

    expectPassThrough(response);
  });

  test("redirects authenticated non-approved users to /beta-access when invite gating is enabled", async () => {
    const response = await runMiddleware("/scanner", {
      user: { id: "user-1", email: "user@example.com" },
      settingsRow: { beta_access_granted: false },
      betaInviteCode: "Daily Drop",
    });

    expectRedirect(response, "/beta-access");
  });

  test("fails closed when authenticated user has no beta-access row and invite gating is enabled", async () => {
    const response = await runMiddleware("/scanner", {
      user: { id: "user-1", email: "user@example.com" },
      settingsRow: null,
      betaInviteCode: "Daily Drop",
    });

    expectRedirect(response, "/beta-access");
  });

  test("fails closed when beta access lookup times out", async () => {
    const response = await runMiddleware("/scanner", {
      user: { id: "user-1", email: "user@example.com" },
      betaInviteCode: "Daily Drop",
      authTimeoutMs: 1,
      getSettings: () => new Promise(() => {}),
    });

    expectRedirect(response, "/beta-access");
  });

  test("allows allowlisted admins through when invite gating is enabled", async () => {
    const response = await runMiddleware("/scanner", {
      user: { id: "admin-1", email: "Ops@Example.com" },
      betaInviteCode: "Daily Drop",
      opsAdminEmails: "ops@example.com,other@example.com",
    });

    expectPassThrough(response);
  });

  test("allows authenticated non-admin users through when invite gating is disabled", async () => {
    const response = await runMiddleware("/scanner", {
      user: { id: "user-1", email: "user@example.com" },
      betaInviteCode: undefined,
      settingsRow: { beta_access_granted: false },
    });

    expectPassThrough(response);
  });

  test("redirects authenticated approved users away from /login", async () => {
    const response = await runMiddleware("/login", {
      user: { id: "user-1", email: "user@example.com" },
      settingsRow: { beta_access_granted: true },
      betaInviteCode: "Daily Drop",
    });

    expectRedirect(response, "/");
  });

  test("redirects authenticated approved users away from /beta-access", async () => {
    const response = await runMiddleware("/beta-access", {
      user: { id: "user-1", email: "user@example.com" },
      settingsRow: { beta_access_granted: true },
      betaInviteCode: "Daily Drop",
    });

    expectRedirect(response, "/");
  });
});
