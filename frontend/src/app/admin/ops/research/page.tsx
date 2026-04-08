import { notFound } from "next/navigation";

import { assertAdminAccess } from "@/lib/server/admin-access";
import { ResearchDiagnosticsDashboard } from "./ResearchDiagnosticsDashboard";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function AdminOpsResearchPage() {
  const access = await assertAdminAccess();
  if (!access.ok) {
    notFound();
  }

  return <ResearchDiagnosticsDashboard />;
}
