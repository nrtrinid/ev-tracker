import { notFound, redirect } from "next/navigation";

import { ScannerSurfacePage } from "../ScannerSurfacePage";
import { getScannerSurface } from "../scanner-surfaces";

export default function ScannerSurfaceRoute({
  params,
}: {
  params: { surface: string };
}) {
  const surface = getScannerSurface(params.surface);
  if (surface.id !== params.surface && params.surface !== "straight_bets") {
    notFound();
  }
  if (!surface.isPublic && params.surface !== "straight_bets") {
    redirect("/scanner/straight_bets");
  }
  return <ScannerSurfacePage surface={surface.id} />;
}
