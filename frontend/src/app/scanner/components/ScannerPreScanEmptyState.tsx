import { Radar } from "lucide-react";

export function ScannerPreScanEmptyState() {
  return (
    <div className="py-12 text-center">
      <Radar className="mx-auto mb-3 h-12 w-12 text-muted-foreground/30" />
      <p className="text-sm text-muted-foreground">Select your books and tap Full Scan</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Results are cached 5 minutes - only stale sports hit the API
      </p>
    </div>
  );
}
