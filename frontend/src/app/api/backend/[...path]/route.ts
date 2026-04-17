import { proxyRequestImpl, type RouteContext } from "@/lib/server/bridge-route-impl";

export const dynamic = "force-dynamic";
export const revalidate = 0;

async function proxyRequest(request: Request, context: RouteContext) {
  return proxyRequestImpl(request, context);
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
