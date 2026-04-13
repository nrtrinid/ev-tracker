"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import {
  applyThemePreference,
  DEFAULT_THEME_PREFERENCE,
  normalizeThemePreference,
  THEME_STORAGE_KEY,
  type ThemePreference,
} from "@/lib/theme";

type ThemeContextValue = {
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemePreference>(DEFAULT_THEME_PREFERENCE);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      const nextTheme = normalizeThemePreference(stored);
      setThemeState(nextTheme);
      applyThemePreference(nextTheme);
    } catch {
      applyThemePreference(DEFAULT_THEME_PREFERENCE);
    }
  }, []);

  useEffect(() => {
    applyThemePreference(theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // ignore storage failures
    }
  }, [theme]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY) return;
      setThemeState(normalizeThemePreference(event.newValue));
    };

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  const value = useMemo(
    () => ({
      theme,
      setTheme: setThemeState,
      toggleTheme: () => setThemeState((current) => (current === "dark" ? "light" : "dark")),
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useThemePreference() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useThemePreference must be used within ThemeProvider");
  }
  return context;
}
