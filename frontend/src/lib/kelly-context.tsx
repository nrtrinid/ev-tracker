"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

type KellySettings = {
  useComputedBankroll: boolean;
  bankrollOverride: number;
  kellyMultiplier: number; // e.g. 0.25 = quarter Kelly
  setUseComputedBankroll: (v: boolean) => void;
  setBankrollOverride: (v: number) => void;
  setKellyMultiplier: (v: number) => void;
};

const KellyContext = createContext<KellySettings | null>(null);

const STORAGE_KEY = "ev-tracker-kelly-settings";

export function KellyProvider({ children }: { children: React.ReactNode }) {
  const [useComputedBankroll, setUseComputedBankroll] = useState<boolean>(true);
  const [bankrollOverride, setBankrollOverride] = useState<number>(1000);
  const [kellyMultiplier, setKellyMultiplier] = useState<number>(0.25);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<{
        useComputedBankroll: boolean;
        bankrollOverride: number;
        kellyMultiplier: number;
      }>;
      if (typeof parsed.useComputedBankroll === "boolean") {
        setUseComputedBankroll(parsed.useComputedBankroll);
      }
      if (typeof parsed.bankrollOverride === "number" && Number.isFinite(parsed.bankrollOverride)) {
        setBankrollOverride(parsed.bankrollOverride);
      }
      if (typeof parsed.kellyMultiplier === "number" && Number.isFinite(parsed.kellyMultiplier)) {
        setKellyMultiplier(parsed.kellyMultiplier);
      }
    } catch {
      // ignore
    }
  }, []);

  // Persist to localStorage when values change
  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ useComputedBankroll, bankrollOverride, kellyMultiplier })
      );
    } catch {
      // ignore
    }
  }, [useComputedBankroll, bankrollOverride, kellyMultiplier]);

  const value = useMemo(
    () => ({
      useComputedBankroll,
      bankrollOverride,
      kellyMultiplier,
      setUseComputedBankroll,
      setBankrollOverride,
      setKellyMultiplier,
    }),
    [useComputedBankroll, bankrollOverride, kellyMultiplier]
  );

  return <KellyContext.Provider value={value}>{children}</KellyContext.Provider>;
}

export function useKellySettings() {
  const ctx = useContext(KellyContext);
  if (!ctx) {
    throw new Error("useKellySettings must be used within KellyProvider");
  }
  return ctx;
}

