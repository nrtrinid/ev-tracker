import { NextResponse } from "next/server";

import { assertAdminAccess } from "@/lib/server/admin-access";

export const dynamic = "force-dynamic";
export const revalidate = 0;

/** Lets client components detect admin status using the same allowlist as server routes (OPS_ADMIN_EMAILS). */
export async function GET() {
  const access = await assertAdminAccess();
  return NextResponse.json(
    { ok: access.ok, error: access.ok ? undefined : access.error },
    { headers: { "Cache-Control": "no-store" } }
  );
}
