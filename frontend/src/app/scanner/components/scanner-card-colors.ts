export function getStandardEdgeColorClass(evPercentage: number): string {
  if (evPercentage < 1.5) {
    return "text-muted-foreground";
  }
  if (evPercentage < 3.5) {
    return "text-[#4A7C59]";
  }
  if (evPercentage < 5.5) {
    return "text-[#3B6C8E]";
  }
  return "text-[#9A3F86]";
}
