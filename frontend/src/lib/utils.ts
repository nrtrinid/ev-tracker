import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Format currency
export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

// Format percentage
export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

// Format American odds with sign
export function formatOdds(odds: number): string {
  return odds >= 0 ? `+${odds}` : `${odds}`;
}

// Convert American to Decimal odds (client-side version)
export function americanToDecimal(american: number): number {
  if (american >= 100) {
    return 1 + american / 100;
  }
  return 1 + 100 / Math.abs(american);
}

// Detect if input is American or Decimal odds
export function detectOddsFormat(value: number): "american" | "decimal" {
  // American odds are typically >= 100 or <= -100
  // Decimal odds are typically between 1.01 and ~100
  if (value >= 100 || value <= -100) {
    return "american";
  }
  if (value > 1 && value < 100) {
    return "decimal";
  }
  // Edge case: small positive numbers could be either
  // Default to decimal for values like 1.5, 2.0, etc.
  return "decimal";
}
