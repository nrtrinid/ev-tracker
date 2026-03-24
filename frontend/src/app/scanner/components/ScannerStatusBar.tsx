import { Clock, Loader2, Radar } from "lucide-react";

import { Button } from "@/components/ui/button";

interface ScannerStatusBarProps {
  hasScanData: boolean;
  isRunningScan: boolean;
  cooldown: number;
  onScan: () => void;
  scanError: string | null;
  scanAgeMinutes: number | null;
  eventsFetched: number;
  tutorialMode?: boolean;
  showBackendHint: boolean;
  backendHint: string;
}

export function ScannerStatusBar({
  hasScanData,
  isRunningScan,
  cooldown,
  onScan,
  scanError,
  scanAgeMinutes,
  eventsFetched,
  tutorialMode = false,
  showBackendHint,
  backendHint,
}: ScannerStatusBarProps) {
  const isStale = (scanAgeMinutes ?? 0) > 5;

  return (
    <div className="space-y-1.5">
      <Button
        className="h-9 w-full text-sm font-semibold"
        onClick={onScan}
        disabled={isRunningScan || cooldown > 0}
      >
        {isRunningScan ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Finding the best plays...
          </>
        ) : cooldown > 0 ? (
          <>
            <Clock className="mr-2 h-4 w-4" />
            {tutorialMode ? `Tutorial scan ready in ${cooldown}s` : `Refresh in ${cooldown}s`}
          </>
        ) : (
          <>
            <Radar className="mr-2 h-4 w-4" />
            {tutorialMode ? (hasScanData ? "Reload Tutorial Lines" : "Run Tutorial Scan") : hasScanData ? "Refresh Plays" : "Find Plays"}
          </>
        )}
      </Button>

      {scanError && <p className="text-center text-sm text-[#B85C38]">{scanError}</p>}

      {hasScanData && (
        <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
          {tutorialMode ? (
            <>
              <div className="inline-flex items-center rounded-full border border-primary/25 bg-primary/8 px-2 py-0.5 text-[10px] text-primary">
                Tutorial Sample
              </div>
              <span className="h-3 w-px bg-border" />
              <span>Practice scanner</span>
              <span className="h-3 w-px bg-border" />
              <span>{eventsFetched} sample events</span>
            </>
          ) : (
            <>
              <div
                className={
                  isStale
                    ? "inline-flex items-center rounded-full border border-[#B85C38]/30 bg-[#B85C38]/10 px-2 py-0.5 text-[10px] text-[#8B3D20]"
                    : "inline-flex items-center rounded-full border border-[#4A7C59]/25 bg-[#4A7C59]/8 px-2 py-0.5 text-[10px] text-[#2E5D39]"
                }
              >
                {isStale ? "Stale" : "Fresh"}
              </div>
              {scanAgeMinutes !== null && (
                <>
                  <span className="h-3 w-px bg-border" />
                  <span>Last scan {scanAgeMinutes} min ago</span>
                </>
              )}
              <span className="h-3 w-px bg-border" />
              <span>{eventsFetched} events</span>
            </>
          )}
        </div>
      )}

      {showBackendHint && (
        <div className="rounded-md border border-[#B85C38]/30 bg-[#B85C38]/10 px-2.5 py-1.5 text-[11px] text-[#8B3D20]">
          {backendHint}
        </div>
      )}
    </div>
  );
}
