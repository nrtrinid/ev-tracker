import { postAdminRefreshMarketsRouteImpl } from "@/lib/server/bridge-route-impl";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function POST() {
  return postAdminRefreshMarketsRouteImpl();
}
