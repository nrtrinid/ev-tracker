import { NextResponse } from "next/server";

import { assertAdminAccess } from "@/lib/server/admin-access";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: Request) {
  const access = await assertAdminAccess();
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

  const backendBaseUrl = process.env.BACKEND_BASE_URL;
  const cronToken = process.env.CRON_TOKEN ?? process.env.CRON_SECRET;

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
    const endpoint = `${backendBaseUrl.replace(/\/$/, "")}/api/ops/alt-pitcher-k-lookup${qs ? `?${qs}` : ""}`;
    const resp = await fetch(endpoint, {
      method: "GET",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "x-ops-token": cronToken,
      },
    });

    const raw = await resp.text();
    let data: unknown;
    try {
      data = raw ? JSON.parse(raw) : { error: "Empty backend response" };
    } catch {
      data = { error: raw || "Invalid backend response" };
    }
    return NextResponse.json(data, {
      status: resp.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error("Alt Pitcher K lookup bridge error:", error);
    return NextResponse.json(
      { error: "Failed to fetch Alt Pitcher K lookup" },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}
