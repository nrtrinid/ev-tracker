import type { BackendReadiness } from "@/lib/types";

export function hasUserFacingSyncIssue(readiness: BackendReadiness | null | undefined): boolean {
  if (!readiness) return false;
  if (readiness.status === "unreachable") return true;

  const checks = readiness.checks;
  if (!checks) return false;

  return checks.db_connectivity === false || checks.supabase_env === false;
}
