import type { ScannerSurfaceId } from "../scanner-surfaces";

interface ScannerSurfaceShellProps {
  activeSurface: ScannerSurfaceId;
}

export function ScannerSurfaceShell({ activeSurface }: ScannerSurfaceShellProps) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Surface</p>
      <p className="text-sm font-semibold text-foreground">
        {activeSurface === "straight_bets" ? "Straight Bets" : "Straight Bets"}
      </p>
    </div>
  );
}
