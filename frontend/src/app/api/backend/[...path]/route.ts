import { NextResponse } from "next/server";

import {
  buildBackendProxyTarget,
  isAllowedBackendProxyPath,
  normalizeBackendProxyPath,
} from "@/lib/server/backend-proxy";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type RouteContext = {
  params: {
    path: string[];
  };
};

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

async function proxyRequest(request: Request, { params }: RouteContext) {
  const backendBaseUrl = process.env.BACKEND_BASE_URL?.replace(/\/$/, "");
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
    const upstreamBody =
      method === "GET" || method === "HEAD"
        ? undefined
        : (() => request.arrayBuffer())();

    const response = await fetch(targetUrl, {
      method,
      cache: "no-store",
      headers: buildUpstreamHeaders(request),
      body: upstreamBody ? await upstreamBody : undefined,
    });

    const responseBody = await response.arrayBuffer();
    return new Response(responseBody, {
      status: response.status,
      headers: buildDownstreamHeaders(response.headers),
    });
  } catch (error) {
    console.error("Backend proxy error:", error);
    return NextResponse.json(
      { detail: "Failed to reach backend" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export async function GET(request: Request, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function POST(request: Request, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function PATCH(request: Request, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function DELETE(request: Request, context: RouteContext) {
  return proxyRequest(request, context);
}
