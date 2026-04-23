import { useEffect, useRef } from "react";
import { Clock, Loader2, Radar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { sendAnalyticsEvent } from "@/lib/analytics";

interface ScannerStatusBarProps {
  hasScanData: boolean;
  isRunningScan: boolean;
  cooldown: number;
  onScan: () => void;
  scanError: string | null;
  scanAgeMinutes: number | null;
  scanCapturedAt?: string | null;
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
  scanCapturedAt,
  eventsFetched,
  tutorialMode = false,
  showBackendHint,
  backendHint,
}: ScannerStatusBarProps) {
  const isStale = (scanAgeMinutes ?? 0) > 5;
  const staleEventKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!hasScanData || tutorialMode || !isStale) {
      return;
    }

    const dedupeKey = scanCapturedAt
      ? `stale-banner:${scanCapturedAt}`
      : `stale-banner:${scanAgeMinutes ?? "unknown"}`;

    if (staleEventKeyRef.current === dedupeKey) {
      return;
    }
    staleEventKeyRef.current = dedupeKey;

    void sendAnalyticsEvent({
      eventName: "stale_data_banner_seen",
      route: "/scanner",
      appArea: "scanner",
      properties: {
        surface: "straight_bets",
        scan_age_minutes: scanAgeMinutes,
      },
      dedupeKey,
      dedupeScope: "user_or_session",
    });
  }, [hasScanData, tutorialMode, isStale, scanCapturedAt, scanAgeMinutes]);

  return (
    <div className="space-y-1.5">
      <Button
        className="h-9 w-full text-sm font-semibold active:scale-[0.98] transition-transform"
        onClick={onScan}
        disabled={isRunningScan || cooldown > 0}
      >
        {isRunningScan ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Finding the best plays…
          </>
        ) : cooldown > 0 ? (
          <>
            <Clock className="mr-2 h-4 w-4" />
            {tutorialMode ? `Tutorial scan ready in ${cooldown}s` : `Refresh in ${cooldown}s`}
          </>
        ) : (
          <>
            <Radar className="mr-2 h-4 w-4" />
            {tutorialMode
              ? hasScanData ? "Reload Tutorial Lines" : "Run Tutorial Scan"
              : hasScanData ? "Refresh Plays" : "Find Plays"}
          </>
        )}
      </Button>

      {scanError && (
        <p className="text-center text-sm text-loss">{scanError}</p>
      )}

      {hasScanData && (
        <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
          {tutorialMode ? (
            <>
              <span className="inline-flex items-center rounded border border-primary/25 bg-primary/8 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">
                Tutorial
              </span>
              <span className="h-3 w-px bg-border" />
              <span>Practice scanner</span>
              <span className="h-3 w-px bg-border" />
              <span>{eventsFetched} sample events</span>
            </>
          ) : (
            <>
              <span
                className={
                  isStale
                    ? "inline-flex items-center rounded border border-loss/30 bg-loss/8 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-loss"
                    : "inline-flex items-center rounded border border-profit/25 bg-profit/8 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-profit"
                }
              >
                {isStale ? "Stale" : "Fresh"}
              </span>
              {scanAgeMinutes !== null && (
                <>
                  <span className="h-3 w-px bg-border" />
                  <span>{scanAgeMinutes}m ago</span>
                </>
              )}
              <span className="h-3 w-px bg-border" />
              <span>{eventsFetched} events</span>
            </>
          )}
        </div>
      )}

      {showBackendHint && (
        <div className="rounded border border-loss/30 bg-loss/8 px-2.5 py-1.5 text-[11px] text-loss">
          {backendHint}
        </div>
      )}
    </div>
  );
}
