import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import {
  betaInviteCodeEnabled,
} from "@/lib/server/beta-access-utils";
import {
  normalizeEmail,
  parseAdminAllowlist,
} from "@/lib/server/admin-access-utils";

type MiddlewareUser = {
  id: string;
  email?: string | null;
} | null;

type MiddlewareSettingsRow = {
  beta_access_granted?: boolean | null;
} | null;

type MiddlewareSupabaseClient = {
  auth: {
    getUser: () => Promise<{
      data: {
        user: MiddlewareUser;
      };
    }>;
  };
  from: (_table: string) => {
    select: (_columns: string) => {
      eq: (_column: string, _value: string) => {
        maybeSingle: () => PromiseLike<{
          data: MiddlewareSettingsRow;
        }>;
      };
    };
  };
};

export interface MiddlewareDeps {
  createClient?: (request: NextRequest) => MiddlewareSupabaseClient;
  betaInviteCode?: string | undefined;
  opsAdminEmails?: string | undefined;
  authTimeoutMs?: number;
  assumeAuthCookie?: boolean;
}

class MiddlewareTimeoutError extends Error {
  constructor(label: string, timeoutMs: number) {
    super(`${label} timed out after ${timeoutMs}ms`);
    this.name = "MiddlewareTimeoutError";
  }
}

function middlewareAuthTimeoutMs(deps: MiddlewareDeps): number {
  const raw = process.env.MIDDLEWARE_AUTH_TIMEOUT_MS;
  const parsed = raw ? Number(raw) : NaN;
  if (deps.authTimeoutMs != null) return deps.authTimeoutMs;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1500;
}

function hasSupabaseAuthCookie(request: NextRequest): boolean {
  return request.cookies
    .getAll()
    .some((cookie) => cookie.name.startsWith("sb-") && cookie.name.includes("auth-token"));
}

async function withMiddlewareTimeout<T>(
  operation: PromiseLike<T>,
  label: string,
  timeoutMs: number
): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      Promise.resolve(operation),
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(() => reject(new MiddlewareTimeoutError(label, timeoutMs)), timeoutMs);
      }),
    ]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

function redirectTo(request: NextRequest, pathname: string) {
  const url = request.nextUrl.clone();
  url.pathname = pathname;
  return NextResponse.redirect(url);
}

function defaultCreateClient(request: NextRequest): MiddlewareSupabaseClient {
  let supabaseResponse = NextResponse.next({ request });

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  ) as unknown as MiddlewareSupabaseClient;
}

export async function middlewareWithDeps(
  request: NextRequest,
  deps: MiddlewareDeps = {}
) {
  const pathname = request.nextUrl.pathname;
  const isLoginPath = pathname.startsWith("/login");
  const isBetaAccessPath = pathname.startsWith("/beta-access");
  const isBetaAccessApiPath = pathname.startsWith("/api/beta-access");

  // Allow Vercel cron endpoints to run without Supabase auth redirects.
  // These endpoints are protected separately via CRON_SECRET checks inside the route handlers.
  if (
    pathname.startsWith("/api/cron/") ||
    pathname.startsWith("/api/backend/") ||
    isBetaAccessApiPath
  ) {
    return NextResponse.next();
  }

  const supabaseResponse = NextResponse.next({ request });
  const hasAuthCookie = deps.assumeAuthCookie ?? (deps.createClient ? true : hasSupabaseAuthCookie(request));

  if (!hasAuthCookie) {
    if (isLoginPath || isBetaAccessPath) {
      return supabaseResponse;
    }
    return redirectTo(request, "/login");
  }

  const supabase = (deps.createClient ?? defaultCreateClient)(request);
  const timeoutMs = middlewareAuthTimeoutMs(deps);

  // Use getUser() instead of getSession() for security in middleware
  let user: MiddlewareUser = null;
  try {
    const result = await withMiddlewareTimeout(
      supabase.auth.getUser(),
      "supabase.auth.getUser",
      timeoutMs
    );
    user = result.data.user;
  } catch {
    if (isLoginPath || isBetaAccessPath) {
      return supabaseResponse;
    }
    return redirectTo(request, "/login");
  }

  // Redirect unauthenticated users to /login
  if (!user && !isLoginPath && !isBetaAccessPath) {
    return redirectTo(request, "/login");
  }

  if (user) {
    const inviteCodeEnabled = betaInviteCodeEnabled(
      deps.betaInviteCode ?? process.env.BETA_INVITE_CODE
    );
    const adminAllowlist = parseAdminAllowlist(
      deps.opsAdminEmails ?? process.env.OPS_ADMIN_EMAILS
    );
    const userEmail = user.email ? normalizeEmail(user.email) : "";
    const isAdmin = !!userEmail && adminAllowlist.includes(userEmail);

    let hasBetaAccess = !inviteCodeEnabled || isAdmin;
    if (!hasBetaAccess) {
      let data: MiddlewareSettingsRow = null;
      try {
        const result = await withMiddlewareTimeout(
          supabase
            .from("settings")
            .select("beta_access_granted")
            .eq("user_id", user.id)
            .maybeSingle(),
          "supabase.settings.beta_access",
          timeoutMs
        );
        data = result.data;
      } catch {
        if (isLoginPath || isBetaAccessPath) {
          return supabaseResponse;
        }
        return redirectTo(request, "/beta-access");
      }
      hasBetaAccess = !!data?.beta_access_granted;
    }

    if (!hasBetaAccess && !isBetaAccessPath) {
      return redirectTo(request, "/beta-access");
    }

    if (!hasBetaAccess) {
      return supabaseResponse;
    }
  }

  // Redirect authenticated beta-approved users away from public auth pages
  if (user && (isLoginPath || isBetaAccessPath)) {
    return redirectTo(request, "/");
  }

  return supabaseResponse;
}

export async function middleware(request: NextRequest) {
  return middlewareWithDeps(request);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
