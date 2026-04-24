import { NextResponse } from "next/server";

import {
  buildBackendProxyTarget,
  isAllowedBackendProxyPath,
  normalizeBackendProxyPath,
} from "@/lib/server/backend-proxy";

const DEFAULT_PROXY_TIMEOUT_MS = 15000;
const DEFAULT_OPS_BRIDGE_TIMEOUT_MS = 15000;
const DEFAULT_ADMIN_BRIDGE_TIMEOUT_MS = 20000;
const DEFAULT_ADMIN_SCAN_BRIDGE_TIMEOUT_MS = 180000;

export type RouteContext = {
  params: {
    path: string[];
  };
};

export type BackendProxyRouteDeps = {
  backendBaseUrl?: string;
  fetchFn?: typeof fetch;
  timeoutMs?: number;
};

export type AdminAccessError = "unauthenticated" | "allowlist_not_configured" | "forbidden";

export type AdminAccessResult = {
  ok: boolean;
  email: string | null;
  error?: AdminAccessError;
};

export type OpsStatusRouteDeps = {
  assertAccess?: () => Promise<AdminAccessResult>;
  backendBaseUrl?: string;
  cronToken?: string;
  fetchFn?: typeof fetch;
  timeoutMs?: number;
};

export type RefreshMarketsRouteDeps = {
  assertAccess?: () => Promise<AdminAccessResult>;
  backendBaseUrl?: string;
  cronToken?: string;
  fetchFn?: typeof fetch;
  timeoutMs?: number;
};

export type TriggerAutoSettleRouteDeps = {
  assertAccess?: () => Promise<AdminAccessResult>;
  backendBaseUrl?: string;
  cronToken?: string;
  fetchFn?: typeof fetch;
  timeoutMs?: number;
};

export type AnalyticsBridgeRouteDeps = {
  assertAccess?: () => Promise<AdminAccessResult>;
  backendBaseUrl?: string;
  cronToken?: string;
  fetchFn?: typeof fetch;
  timeoutMs?: number;
};

function resolveTimeoutMs(value: number | undefined, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return Math.trunc(value);
  }
  return fallback;
}

function proxyTimeoutMs(): number {
  const raw = Number(process.env.BACKEND_PROXY_TIMEOUT_MS ?? DEFAULT_PROXY_TIMEOUT_MS);
  return resolveTimeoutMs(raw, DEFAULT_PROXY_TIMEOUT_MS);
}

function opsBridgeTimeoutMs(): number {
  const raw = Number(process.env.OPS_BRIDGE_TIMEOUT_MS ?? DEFAULT_OPS_BRIDGE_TIMEOUT_MS);
  return resolveTimeoutMs(raw, DEFAULT_OPS_BRIDGE_TIMEOUT_MS);
}

function adminBridgeTimeoutMs(): number {
  const raw = Number(process.env.ADMIN_BRIDGE_TIMEOUT_MS ?? DEFAULT_ADMIN_BRIDGE_TIMEOUT_MS);
  return resolveTimeoutMs(raw, DEFAULT_ADMIN_BRIDGE_TIMEOUT_MS);
}

function adminScanBridgeTimeoutMs(): number {
  const raw = Number(
    process.env.ADMIN_SCAN_BRIDGE_TIMEOUT_MS
      ?? process.env.ADMIN_BRIDGE_TIMEOUT_MS
      ?? DEFAULT_ADMIN_SCAN_BRIDGE_TIMEOUT_MS
  );
  return resolveTimeoutMs(raw, DEFAULT_ADMIN_SCAN_BRIDGE_TIMEOUT_MS);
}

async function resolveAdminAccess(assertAccess?: () => Promise<AdminAccessResult>): Promise<AdminAccessResult> {
  if (assertAccess) {
    return assertAccess();
  }

  const { assertAdminAccess } = await import("@/lib/server/admin-access");
  return assertAdminAccess();
}

function buildUpstreamHeaders(request: Request): Headers {
  const headers = new Headers();
  const authorization = request.headers.get("authorization");
  const contentType = request.headers.get("content-type");
  const correlationId = request.headers.get("x-correlation-id");
  const accept = request.headers.get("accept");

  if (authorization) headers.set("authorization", authorization);
  if (contentType) headers.set("content-type", contentType);
  if (correlationId) headers.set("x-correlation-id", correlationId);
  if (accept) headers.set("accept", accept);

  return headers;
}

function buildDownstreamHeaders(responseHeaders: Headers): Headers {
  const headers = new Headers({
    "Cache-Control": responseHeaders.get("cache-control") ?? "no-store",
  });
  const contentType = responseHeaders.get("content-type");
  const correlationId = responseHeaders.get("x-correlation-id");
  const requestId = responseHeaders.get("x-request-id");

  if (contentType) headers.set("content-type", contentType);
  if (correlationId) headers.set("x-correlation-id", correlationId);
  if (requestId) headers.set("x-request-id", requestId);

  return headers;
}

export async function proxyRequestImpl(
  request: Request,
  { params }: RouteContext,
  deps: BackendProxyRouteDeps = {}
): Promise<Response> {
  const backendBaseUrl = (deps.backendBaseUrl ?? process.env.BACKEND_BASE_URL)?.replace(/\/$/, "");
  if (!backendBaseUrl) {
    return NextResponse.json(
      { detail: "BACKEND_BASE_URL not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }

  const pathname = normalizeBackendProxyPath(params.path ?? []);
  if (!pathname) {
    return NextResponse.json(
      { detail: "Invalid backend proxy path" },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (!isAllowedBackendProxyPath(pathname)) {
    return NextResponse.json(
      { detail: "Route not available through backend proxy" },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    );
  }

  const targetUrl = buildBackendProxyTarget(
    backendBaseUrl,
    pathname,
    new URL(request.url).search,
  );

  try {
    const method = request.method.toUpperCase();
    const fetchFn = deps.fetchFn ?? fetch;
    const timeoutMs = resolveTimeoutMs(deps.timeoutMs, proxyTimeoutMs());
    const upstreamBody =
      method === "GET" || method === "HEAD"
        ? undefined
        : (() => request.arrayBuffer())();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    const response = await fetchFn(targetUrl, {
      method,
      cache: "no-store",
      headers: buildUpstreamHeaders(request),
      body: upstreamBody ? await upstreamBody : undefined,
      signal: controller.signal,
    }).finally(() => {
      clearTimeout(timeout);
    });

    const responseBody = await response.arrayBuffer();
    return new Response(responseBody, {
      status: response.status,
      headers: buildDownstreamHeaders(response.headers),
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return NextResponse.json(
        { detail: "Backend request timed out" },
        { status: 504, headers: { "Cache-Control": "no-store" } },
      );
    }
    console.error("Backend proxy error:", error);
    return NextResponse.json(
      { detail: "Failed to reach backend" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export async function getOpsStatusRouteImpl(deps: OpsStatusRouteDeps = {}) {
  const access = await resolveAdminAccess(deps.assertAccess);
  if (!access.ok) {
    if (access.error === "allowlist_not_configured") {
      return NextResponse.json(
        { error: "OPS_ADMIN_EMAILS is not configured" },
        { status: 503, headers: { "Cache-Control": "no-store" } }
      );
    }
    return NextResponse.json(
      { error: "Forbidden" },
      { status: access.error === "unauthenticated" ? 401 : 403, headers: { "Cache-Control": "no-store" } }
    );
  }

  const backendBaseUrl = deps.backendBaseUrl ?? process.env.BACKEND_BASE_URL;
  const cronToken = deps.cronToken ?? process.env.CRON_TOKEN ?? process.env.CRON_SECRET;

  if (!backendBaseUrl) {
    return NextResponse.json(
      { error: "BACKEND_BASE_URL not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }
  if (!cronToken) {
    return NextResponse.json(
      { error: "CRON_TOKEN/CRON_SECRET not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const endpoint = `${backendBaseUrl.replace(/\/$/, "")}/api/ops/status`;
    const fetchFn = deps.fetchFn ?? fetch;
    const timeoutMs = resolveTimeoutMs(deps.timeoutMs, opsBridgeTimeoutMs());
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const resp = await fetchFn(endpoint, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "x-ops-token": cronToken,
      },
      signal: controller.signal,
    }).finally(() => {
      clearTimeout(timeout);
    });

    const data = await resp.json().catch(() => ({ error: "Invalid backend response" }));
    return NextResponse.json(data, {
      status: resp.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return NextResponse.json(
        { error: "Operator status request timed out" },
        { status: 504, headers: { "Cache-Control": "no-store" } }
      );
    }
    console.error("Ops bridge error:", error);
    return NextResponse.json(
      { error: "Failed to fetch operator status" },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}

async function getAnalyticsBridgeRouteImpl(
  request: Request,
  endpointPath: "/api/ops/analytics/summary" | "/api/ops/analytics/users",
  timeoutMessage: string,
  failureMessage: string,
  deps: AnalyticsBridgeRouteDeps = {},
) {
  const access = await resolveAdminAccess(deps.assertAccess);
  if (!access.ok) {
    if (access.error === "allowlist_not_configured") {
      return NextResponse.json(
        { error: "OPS_ADMIN_EMAILS is not configured" },
        { status: 503, headers: { "Cache-Control": "no-store" } }
      );
    }
    return NextResponse.json(
      { error: "Forbidden" },
      { status: access.error === "unauthenticated" ? 401 : 403, headers: { "Cache-Control": "no-store" } }
    );
  }

  const backendBaseUrl = deps.backendBaseUrl ?? process.env.BACKEND_BASE_URL;
  const cronToken = deps.cronToken ?? process.env.CRON_TOKEN ?? process.env.CRON_SECRET;

  if (!backendBaseUrl) {
    return NextResponse.json(
      { error: "BACKEND_BASE_URL not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }
  if (!cronToken) {
    return NextResponse.json(
      { error: "CRON_TOKEN/CRON_SECRET not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const url = new URL(request.url);
    const qs = url.searchParams.toString();
    const endpoint = `${backendBaseUrl.replace(/\/$/, "")}${endpointPath}${qs ? `?${qs}` : ""}`;
    const fetchFn = deps.fetchFn ?? fetch;
    const timeoutMs = resolveTimeoutMs(deps.timeoutMs, opsBridgeTimeoutMs());
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const resp = await fetchFn(endpoint, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "x-ops-token": cronToken,
      },
      signal: controller.signal,
    }).finally(() => {
      clearTimeout(timeout);
    });

    const data = await resp.json().catch(() => ({ error: "Invalid backend response" }));
    return NextResponse.json(data, {
      status: resp.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return NextResponse.json(
        { error: timeoutMessage },
        { status: 504, headers: { "Cache-Control": "no-store" } }
      );
    }
    console.error("Analytics bridge error:", error);
    return NextResponse.json(
      { error: failureMessage },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}

export async function getAnalyticsSummaryRouteImpl(
  request: Request,
  deps: AnalyticsBridgeRouteDeps = {},
) {
  return getAnalyticsBridgeRouteImpl(
    request,
    "/api/ops/analytics/summary",
    "Analytics summary request timed out",
    "Failed to fetch analytics summary",
    deps,
  );
}

export async function getAnalyticsUsersRouteImpl(
  request: Request,
  deps: AnalyticsBridgeRouteDeps = {},
) {
  return getAnalyticsBridgeRouteImpl(
    request,
    "/api/ops/analytics/users",
    "Analytics users request timed out",
    "Failed to fetch analytics users drilldown",
    deps,
  );
}

export async function postAdminRefreshMarketsRouteImpl(deps: RefreshMarketsRouteDeps = {}) {
  const access = await resolveAdminAccess(deps.assertAccess);
  if (!access.ok) {
    if (access.error === "allowlist_not_configured") {
      return NextResponse.json(
        { detail: "OPS_ADMIN_EMAILS is not configured" },
        { status: 503, headers: { "Cache-Control": "no-store" } }
      );
    }
    return NextResponse.json(
      { detail: access.error === "unauthenticated" ? "Unauthorized" : "Forbidden" },
      { status: access.error === "unauthenticated" ? 401 : 403, headers: { "Cache-Control": "no-store" } }
    );
  }

  const backendBaseUrl = (deps.backendBaseUrl ?? process.env.BACKEND_BASE_URL)?.replace(/\/$/, "");
  const cronToken = deps.cronToken ?? process.env.CRON_TOKEN ?? process.env.CRON_SECRET;

  if (!backendBaseUrl) {
    return NextResponse.json(
      { detail: "BACKEND_BASE_URL not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }
  if (!cronToken) {
    return NextResponse.json(
      { detail: "CRON_TOKEN/CRON_SECRET not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const asyncEndpoint = `${backendBaseUrl}/api/ops/trigger/board-refresh/async`;
    const fallbackEndpoint = `${backendBaseUrl}/api/ops/trigger/board-refresh`;
    const legacyAsyncEndpoint = `${backendBaseUrl}/api/ops/trigger/scan/async`;
    const legacyFallbackEndpoint = `${backendBaseUrl}/api/ops/trigger/scan`;
    const fetchFn = deps.fetchFn ?? fetch;
    const timeoutMs = resolveTimeoutMs(deps.timeoutMs, adminScanBridgeTimeoutMs());
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const requestInit: RequestInit = {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "x-ops-token": cronToken,
      },
      body: JSON.stringify({}),
      signal: controller.signal,
    };

    let resp: Response;
    try {
      resp = await fetchFn(asyncEndpoint, requestInit);
      if (resp.status === 404) {
        resp = await fetchFn(legacyAsyncEndpoint, requestInit);
      }
      if (resp.status === 404) {
        // Backward compatibility: older backend deployments only expose the sync endpoint.
        resp = await fetchFn(fallbackEndpoint, requestInit);
      }
      if (resp.status === 404) {
        resp = await fetchFn(legacyFallbackEndpoint, requestInit);
      }
    } finally {
      clearTimeout(timeout);
    }

    const raw = await resp.text();
    let data: unknown;
    try {
      data = raw ? JSON.parse(raw) : { detail: "Empty backend response" };
    } catch {
      data = { detail: raw || "Invalid backend response" };
    }
    return NextResponse.json(data, {
      status: resp.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return NextResponse.json(
        { detail: "Backend board refresh trigger timed out" },
        { status: 504, headers: { "Cache-Control": "no-store" } }
      );
    }
    console.error("Admin refresh-markets proxy error:", error);
    return NextResponse.json(
      { detail: "Failed to reach backend" },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}

export async function postAdminTriggerAutoSettleRouteImpl(
  deps: TriggerAutoSettleRouteDeps = {}
) {
  const access = await resolveAdminAccess(deps.assertAccess);
  if (!access.ok) {
    if (access.error === "allowlist_not_configured") {
      return NextResponse.json(
        { detail: "OPS_ADMIN_EMAILS is not configured" },
        { status: 503, headers: { "Cache-Control": "no-store" } }
      );
    }
    return NextResponse.json(
      { detail: access.error === "unauthenticated" ? "Unauthorized" : "Forbidden" },
      { status: access.error === "unauthenticated" ? 401 : 403, headers: { "Cache-Control": "no-store" } }
    );
  }

  const backendBaseUrl = (deps.backendBaseUrl ?? process.env.BACKEND_BASE_URL)?.replace(/\/$/, "");
  const cronToken = deps.cronToken ?? process.env.CRON_TOKEN ?? process.env.CRON_SECRET;

  if (!backendBaseUrl) {
    return NextResponse.json(
      { detail: "BACKEND_BASE_URL not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }
  if (!cronToken) {
    return NextResponse.json(
      { detail: "CRON_TOKEN/CRON_SECRET not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const endpoint = `${backendBaseUrl}/api/ops/trigger/auto-settle`;
    const fetchFn = deps.fetchFn ?? fetch;
    const timeoutMs = resolveTimeoutMs(deps.timeoutMs, adminBridgeTimeoutMs());
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const resp = await fetchFn(endpoint, {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "x-ops-token": cronToken,
      },
      body: JSON.stringify({}),
      signal: controller.signal,
    }).finally(() => {
      clearTimeout(timeout);
    });

    const data = await resp.json().catch(() => ({ detail: "Invalid backend response" }));
    return NextResponse.json(data, {
      status: resp.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return NextResponse.json(
        { detail: "Backend auto-settle trigger timed out" },
        { status: 504, headers: { "Cache-Control": "no-store" } }
      );
    }
    console.error("Admin trigger-auto-settle proxy error:", error);
    return NextResponse.json(
      { detail: "Failed to reach backend" },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}
