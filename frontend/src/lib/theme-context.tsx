"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { useSettings, useUpdateSettings } from "@/lib/hooks";

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
  const { user, loading } = useAuth();
  const { data: settings } = useSettings({ enabled: !loading && !!user });
  const updateSettings = useUpdateSettings();
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
    if (!user || !settings) return;
    const remoteTheme = normalizeThemePreference(settings.theme_preference);
    setThemeState((current) => (current === remoteTheme ? current : remoteTheme));
  }, [settings, user]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY) return;
      setThemeState(normalizeThemePreference(event.newValue));
    };

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  const setTheme = useCallback((nextTheme: ThemePreference) => {
    const normalizedTheme = normalizeThemePreference(nextTheme);
    setThemeState((current) => (current === normalizedTheme ? current : normalizedTheme));

    if (!user || loading) return;
    if (settings?.theme_preference === normalizedTheme) return;

    updateSettings.mutate({ theme_preference: normalizedTheme });
  }, [loading, settings?.theme_preference, updateSettings, user]);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [setTheme, theme]);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      toggleTheme,
    }),
    [setTheme, theme, toggleTheme],
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
