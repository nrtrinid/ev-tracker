import { Radar, Sparkles } from "lucide-react";

export function ScannerPreScanEmptyState({
  tutorialMode = false,
}: {
  tutorialMode?: boolean;
}) {
  return (
    <div className="py-12 text-center">
      {tutorialMode ? (
        <>
          <Sparkles className="mx-auto mb-3 h-12 w-12 text-primary/40" />
          <p className="text-sm font-semibold text-foreground">Run the tutorial scan to load practice lines</p>
          <p className="mt-1 text-xs text-muted-foreground">
            The scanner stays visible from the start. Use the scan button above to populate sample straight bets and try the workflow without touching your real account.
          </p>
        </>
      ) : (
        <>
          <Radar className="mx-auto mb-3 h-12 w-12 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">Choose your books, then tap Find Plays</p>
          <p className="mt-1 text-xs text-muted-foreground">
            We will surface the cleanest opportunities first so you can place and log them quickly.
          </p>
        </>
      )}
    </div>
  );
}
