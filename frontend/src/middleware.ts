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
  const supabase = (deps.createClient ?? defaultCreateClient)(request);

  // Use getUser() instead of getSession() for security in middleware
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // Redirect unauthenticated users to /login
  if (!user && !isLoginPath && !isBetaAccessPath) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
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
      const { data } = await supabase
        .from("settings")
        .select("beta_access_granted")
        .eq("user_id", user.id)
        .maybeSingle();
      hasBetaAccess = !!data?.beta_access_granted;
    }

    if (!hasBetaAccess && !isBetaAccessPath) {
      const url = request.nextUrl.clone();
      url.pathname = "/beta-access";
      return NextResponse.redirect(url);
    }

    if (!hasBetaAccess) {
      return supabaseResponse;
    }
  }

  // Redirect authenticated beta-approved users away from public auth pages
  if (user && (isLoginPath || isBetaAccessPath)) {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
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
