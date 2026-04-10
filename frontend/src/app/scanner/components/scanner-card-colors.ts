export function getStandardEdgeColorClass(evPercentage: number): string {
  if (evPercentage < 2.0) {
    return "text-muted-foreground";
  }
  if (evPercentage < 4.0) {
    // semantic profit token — adapts between light (#4A7C59) and dark (#52A66B)
    return "text-profit";
  }
  if (evPercentage < 5.5) {
    // steel blue — dark-aware
    return "text-[#3B6C8E] dark:text-[#6BAED6]";
  }
  // premium purple — dark-aware
  return "text-[#9A3F86] dark:text-[#C47DD8]";
}
