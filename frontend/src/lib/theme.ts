import type { ThemePreference } from "@/lib/types";

export type { ThemePreference } from "@/lib/types";

export const THEME_STORAGE_KEY = "ev-tracker-theme";

export const DEFAULT_THEME_PREFERENCE: ThemePreference = "light";
export function normalizeThemePreference(value: string | null | undefined): ThemePreference {
  return value === "dark" || value === "light" ? value : DEFAULT_THEME_PREFERENCE;
}

export function applyThemePreference(theme: ThemePreference): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const isDark = theme === "dark";
  root.classList.toggle("dark", isDark);
  root.style.colorScheme = isDark ? "dark" : "light";
}

export function buildThemeInitScript(): string {
  return `(() => {
    try {
      const saved = window.localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
      const theme = saved === "dark" || saved === "light" ? saved : ${JSON.stringify(DEFAULT_THEME_PREFERENCE)};
      const root = document.documentElement;
      const isDark = theme === "dark";
      root.classList.toggle("dark", isDark);
      root.style.colorScheme = isDark ? "dark" : "light";
    } catch {
      const root = document.documentElement;
      root.classList.toggle("dark", ${JSON.stringify(DEFAULT_THEME_PREFERENCE)} === "dark");
      root.style.colorScheme = ${JSON.stringify(DEFAULT_THEME_PREFERENCE)};
    }
  })();`;
}
