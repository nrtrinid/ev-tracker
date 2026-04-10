const EXACT_ALLOWED_BACKEND_PROXY_PATHS = new Set<string>([
  "/summary",
  "/settings",
  "/calculate-ev",
  "/balances",
  "/ready",
  "/health",
  "/api/scan-markets",
  "/api/scan-latest",
]);

const PREFIX_ALLOWED_BACKEND_PROXY_PATHS = [
  "/bets",
  "/transactions",
  "/parlay-slips",
  "/api/board",
  "/beta/access",
] as const;

export function normalizeBackendProxyPath(pathSegments: string[]): string | null {
  if (pathSegments.length === 0) return null;

  const cleanedSegments: string[] = [];
  for (const segment of pathSegments) {
    if (!segment) continue;
    if (segment === "." || segment === "..") return null;
    cleanedSegments.push(segment);
  }

  if (cleanedSegments.length === 0) return null;
  return `/${cleanedSegments.join("/")}`;
}

export function isAllowedBackendProxyPath(pathname: string): boolean {
  if (EXACT_ALLOWED_BACKEND_PROXY_PATHS.has(pathname)) return true;
  return PREFIX_ALLOWED_BACKEND_PROXY_PATHS.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function buildBackendProxyTarget(
  backendBaseUrl: string,
  pathname: string,
  search: string,
): string {
  const trimmedBaseUrl = backendBaseUrl.replace(/\/$/, "");
  return `${trimmedBaseUrl}${pathname}${search}`;
}
