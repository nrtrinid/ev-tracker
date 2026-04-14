export function getStandardEdgeColorClass(evPercentage: number): string {
  if (evPercentage < 2.0) {
    return "text-muted-foreground";
  }
  if (evPercentage < 4.0) {
    // semantic profit token — adapts between light and dark mode
    return "text-profit";
  }
  if (evPercentage < 5.5) {
    // steel blue — dark-aware, matches --color-ev-high
    return "text-[hsl(210_45%_38%)] dark:text-[hsl(210_50%_60%)]";
  }
  // premium purple — dark-aware, matches --color-ev-elite
  return "text-[hsl(290_48%_38%)] dark:text-[hsl(290_44%_60%)]";
}
