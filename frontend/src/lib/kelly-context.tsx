"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

import { useSettings, useUpdateSettings } from "@/lib/hooks";

type KellySettings = {
  useComputedBankroll: boolean;
  bankrollOverride: number;
  kellyMultiplier: number;
  setUseComputedBankroll: (value: boolean) => void;
  setBankrollOverride: (value: number) => void;
  setKellyMultiplier: (value: number) => void;
};

type KellySnapshot = {
  useComputedBankroll: boolean;
  bankrollOverride: number;
  kellyMultiplier: number;
};

const KellyContext = createContext<KellySettings | null>(null);

const STORAGE_KEY = "ev-tracker-kelly-settings";
const DEFAULT_KELLY_SETTINGS: KellySnapshot = {
  useComputedBankroll: true,
  bankrollOverride: 1000,
  kellyMultiplier: 0.25,
};

function normalizeKellySnapshot(value: Partial<KellySnapshot> | null | undefined): KellySnapshot {
  return {
    useComputedBankroll:
      typeof value?.useComputedBankroll === "boolean"
        ? value.useComputedBankroll
        : DEFAULT_KELLY_SETTINGS.useComputedBankroll,
    bankrollOverride:
      typeof value?.bankrollOverride === "number" && Number.isFinite(value.bankrollOverride)
        ? value.bankrollOverride
        : DEFAULT_KELLY_SETTINGS.bankrollOverride,
    kellyMultiplier:
      typeof value?.kellyMultiplier === "number" && Number.isFinite(value.kellyMultiplier) && value.kellyMultiplier > 0
        ? value.kellyMultiplier
        : DEFAULT_KELLY_SETTINGS.kellyMultiplier,
  };
}

function snapshotsEqual(left: KellySnapshot, right: KellySnapshot): boolean {
  return left.useComputedBankroll === right.useComputedBankroll &&
    Math.abs(left.bankrollOverride - right.bankrollOverride) < 0.000001 &&
    Math.abs(left.kellyMultiplier - right.kellyMultiplier) < 0.000001;
}

export function KellyProvider({ children }: { children: React.ReactNode }) {
  const { data: settings } = useSettings();
  const updateSettings = useUpdateSettings();

  const [useComputedBankroll, setUseComputedBankrollState] = useState<boolean>(DEFAULT_KELLY_SETTINGS.useComputedBankroll);
  const [bankrollOverride, setBankrollOverrideState] = useState<number>(DEFAULT_KELLY_SETTINGS.bankrollOverride);
  const [kellyMultiplier, setKellyMultiplierState] = useState<number>(DEFAULT_KELLY_SETTINGS.kellyMultiplier);

  const remoteHydratedRef = useRef(false);
  const lastPersistedRef = useRef<KellySnapshot>(DEFAULT_KELLY_SETTINGS);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<KellySnapshot>;
      const snapshot = normalizeKellySnapshot(parsed);
      setUseComputedBankrollState(snapshot.useComputedBankroll);
      setBankrollOverrideState(snapshot.bankrollOverride);
      setKellyMultiplierState(snapshot.kellyMultiplier);
    } catch {
      // ignore malformed local storage
    }
  }, []);

  useEffect(() => {
    if (!settings) {
      return;
    }

    const remoteSnapshot = normalizeKellySnapshot({
      useComputedBankroll: settings.use_computed_bankroll,
      bankrollOverride: settings.bankroll_override,
      kellyMultiplier: settings.kelly_multiplier,
    });

    remoteHydratedRef.current = true;
    lastPersistedRef.current = remoteSnapshot;
    setUseComputedBankrollState(remoteSnapshot.useComputedBankroll);
    setBankrollOverrideState(remoteSnapshot.bankrollOverride);
    setKellyMultiplierState(remoteSnapshot.kellyMultiplier);
  }, [
    settings?.bankroll_override,
    settings?.kelly_multiplier,
    settings?.use_computed_bankroll,
  ]);

  const snapshot = useMemo(
    () =>
      normalizeKellySnapshot({
        useComputedBankroll,
        bankrollOverride,
        kellyMultiplier,
      }),
    [bankrollOverride, kellyMultiplier, useComputedBankroll],
  );

  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(snapshot),
      );
    } catch {
      // ignore storage failures
    }
  }, [snapshot]);

  useEffect(() => {
    if (!remoteHydratedRef.current) {
      return;
    }
    if (snapshotsEqual(snapshot, lastPersistedRef.current)) {
      return;
    }

    const handle = window.setTimeout(async () => {
      try {
        await updateSettings.mutateAsync({
          use_computed_bankroll: snapshot.useComputedBankroll,
          bankroll_override: snapshot.bankrollOverride,
          kelly_multiplier: snapshot.kellyMultiplier,
        });
        lastPersistedRef.current = snapshot;
      } catch {
        // Keep local state even if the network update fails.
      }
    }, 250);

    return () => window.clearTimeout(handle);
  }, [snapshot, updateSettings]);

  const value = useMemo(
    () => ({
      useComputedBankroll,
      bankrollOverride,
      kellyMultiplier,
      setUseComputedBankroll: setUseComputedBankrollState,
      setBankrollOverride: setBankrollOverrideState,
      setKellyMultiplier: setKellyMultiplierState,
    }),
    [bankrollOverride, kellyMultiplier, useComputedBankroll],
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
