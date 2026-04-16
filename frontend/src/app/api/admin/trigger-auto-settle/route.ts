import { NextResponse } from "next/server";

import { assertAdminAccess } from "@/lib/server/admin-access";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const DEFAULT_ADMIN_BRIDGE_TIMEOUT_MS = 20000;

function adminBridgeTimeoutMs(): number {
  const raw = Number(process.env.ADMIN_BRIDGE_TIMEOUT_MS ?? DEFAULT_ADMIN_BRIDGE_TIMEOUT_MS);
  if (!Number.isFinite(raw) || raw <= 0) {
    return DEFAULT_ADMIN_BRIDGE_TIMEOUT_MS;
  }
  return Math.trunc(raw);
}

/** Proxies to FastAPI `POST /api/ops/trigger/auto-settle` using the ops token (admin-only). */
export async function POST() {
  const access = await assertAdminAccess();
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

  const backendBaseUrl = process.env.BACKEND_BASE_URL?.replace(/\/$/, "");
  const cronToken = process.env.CRON_TOKEN ?? process.env.CRON_SECRET;

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
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), adminBridgeTimeoutMs());
    const resp = await fetch(endpoint, {
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
    if (error instanceof Error && error.name == "AbortError") {
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
