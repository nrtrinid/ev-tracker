import { NextResponse } from "next/server";

import { assertAdminAccess } from "@/lib/server/admin-access";

export const dynamic = "force-dynamic";
export const revalidate = 0;

/** Proxies to FastAPI `POST /api/ops/trigger/scan` so the ops UI can run the full daily-board refresh manually. */
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
    const endpoint = `${backendBaseUrl}/api/ops/trigger/scan`;
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "x-ops-token": cronToken,
      },
      body: JSON.stringify({}),
    });
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
    console.error("Admin refresh-markets proxy error:", error);
    return NextResponse.json(
      { detail: "Failed to reach backend" },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}
