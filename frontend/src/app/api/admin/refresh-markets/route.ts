import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

/** Proxies to FastAPI `POST /admin/refresh-markets` with the caller's JWT (backend enforces admin allowlist). */
export async function POST(request: Request) {
  const authHeader = request.headers.get("authorization");
  if (!authHeader?.startsWith("Bearer ")) {
    return NextResponse.json(
      { detail: "Unauthorized" },
      { status: 401, headers: { "Cache-Control": "no-store" } }
    );
  }

  const backendBaseUrl = process.env.BACKEND_BASE_URL?.replace(/\/$/, "");
  if (!backendBaseUrl) {
    return NextResponse.json(
      { detail: "BACKEND_BASE_URL not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }

  const url = new URL(request.url);
  const qs = url.searchParams.toString();

  try {
    const endpoint = `${backendBaseUrl}/api/admin/refresh-markets${qs ? `?${qs}` : ""}`;
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: {
        Authorization: authHeader,
        "Content-Type": "application/json",
      },
    });

    const data = await resp.json().catch(() => ({ detail: "Invalid backend response" }));
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
