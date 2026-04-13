export type ThemePreference = "dark" | "light";

export const THEME_STORAGE_KEY = "ev-tracker-theme";
export const DEFAULT_THEME_PREFERENCE: ThemePreference = "dark";

export function normalizeThemePreference(value: string | null | undefined): ThemePreference {
  return value === "light" ? "light" : DEFAULT_THEME_PREFERENCE;
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
      const theme = saved === "light" ? "light" : "dark";
      const root = document.documentElement;
      const isDark = theme === "dark";
      root.classList.toggle("dark", isDark);
      root.style.colorScheme = isDark ? "dark" : "light";
    } catch {
      const root = document.documentElement;
      root.classList.add("dark");
      root.style.colorScheme = "dark";
    }
  })();`;
}
