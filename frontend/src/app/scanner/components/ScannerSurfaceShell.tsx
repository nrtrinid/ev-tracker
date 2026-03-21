import type { ScannerSurface } from "@/lib/types";
import { getScannerSurface } from "../scanner-surfaces";

interface ScannerSurfaceShellProps {
  activeSurface: ScannerSurface;
}

export function ScannerSurfaceShell({ activeSurface }: ScannerSurfaceShellProps) {
  const surface = getScannerSurface(activeSurface);
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Surface</p>
      <p className="text-sm font-semibold text-foreground">{surface.label}</p>
    </div>
  );
}
