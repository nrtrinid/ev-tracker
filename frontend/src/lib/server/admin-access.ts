import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import {
  evaluateAdminAccess,
  normalizeEmail,
  parseAdminAllowlist,
  type AdminAccessDecision,
} from "@/lib/server/admin-access-utils";

export type AdminAccessResult = AdminAccessDecision;

export function getAdminAllowlist(): string[] {
  return parseAdminAllowlist(process.env.OPS_ADMIN_EMAILS);
}

async function getServerUserEmail(): Promise<string | null> {
  const cookieStore = cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll() {
          // No-op in server helper; auth writes are handled by middleware.
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user?.email ? normalizeEmail(user.email) : null;
}

export async function assertAdminAccess(): Promise<AdminAccessResult> {
  const email = await getServerUserEmail();
  const allowlist = getAdminAllowlist();
  return evaluateAdminAccess(email, allowlist);
}
