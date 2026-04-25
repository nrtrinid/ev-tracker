export function getInitialOddsInputSign(value: string, defaultSign: "+" | "-"): boolean {
  const trimmed = value.trim();
  if (trimmed.startsWith("-")) return false;
  if (trimmed.startsWith("+")) return true;
  return defaultSign === "+";
}

export function getSignedOddsInputValue(value: string, isPositive: boolean): number {
  const trimmed = value.trim();
  const parsed = parseFloat(trimmed);
  if (!Number.isFinite(parsed) || parsed === 0) return 0;

  if (trimmed.startsWith("-")) return -Math.abs(parsed);
  if (trimmed.startsWith("+")) return Math.abs(parsed);
  return isPositive ? Math.abs(parsed) : -Math.abs(parsed);
}

export function stripOddsInputSign(value: string): string {
  return value.replace(/[+-]/g, "");
}
