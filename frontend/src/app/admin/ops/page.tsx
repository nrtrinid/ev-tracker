import { notFound } from "next/navigation";

import { assertAdminAccess } from "@/lib/server/admin-access";
import { OpsDashboard } from "./OpsDashboard";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function AdminOpsPage() {
  const access = await assertAdminAccess();
  if (!access.ok) {
    notFound();
  }

  return <OpsDashboard />;
}
