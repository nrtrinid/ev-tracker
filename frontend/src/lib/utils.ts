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

// Format relative time (e.g., "2h ago", "3d ago")
export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  
  // For older dates, show short date
  return formatShortDate(dateString);
}

// Format short date (e.g., "Dec 24")
export function formatShortDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Format full date/time for details view
export function formatFullDateTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
