export type AdminAccessError = "unauthenticated" | "allowlist_not_configured" | "forbidden";

export interface AdminAccessDecision {
  ok: boolean;
  email: string | null;
  error?: AdminAccessError;
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function parseAdminAllowlist(raw: string | undefined): string[] {
  return (raw || "")
    .split(",")
    .map((entry) => normalizeEmail(entry))
    .filter(Boolean);
}

export function isEmailAllowlisted(email: string, allowlist: string[]): boolean {
  return allowlist.includes(normalizeEmail(email));
}

export function evaluateAdminAccess(email: string | null, allowlist: string[]): AdminAccessDecision {
  if (!email) {
    return { ok: false, email: null, error: "unauthenticated" };
  }
  if (!allowlist.length) {
    return { ok: false, email, error: "allowlist_not_configured" };
  }
  if (!isEmailAllowlisted(email, allowlist)) {
    return { ok: false, email, error: "forbidden" };
  }
  return { ok: true, email };
}
