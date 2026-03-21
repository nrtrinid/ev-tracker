"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import type { ParlayCartLeg, ScannerSurface } from "@/lib/types";

type SurfaceFilters = Record<string, unknown>;

interface BettingPlatformState {
  cart: ParlayCartLeg[];
  surfaceFilters: Partial<Record<ScannerSurface, SurfaceFilters>>;
  onboardingCompleted: string[];
  onboardingDismissed: string[];
}

interface BettingPlatformContextValue extends BettingPlatformState {
  addCartLeg: (leg: ParlayCartLeg) => { added: boolean; reason?: string };
  removeCartLeg: (legId: string) => void;
  clearCart: () => void;
  setSurfaceFilters: (surface: ScannerSurface, filters: SurfaceFilters) => void;
  markOnboardingCompleted: (step: string) => void;
  dismissOnboardingStep: (step: string) => void;
  hydrateOnboarding: (payload: { completed?: string[]; dismissed?: string[] } | null | undefined) => void;
}

const STORAGE_KEY = "ev-tracker-betting-platform";

const defaultState: BettingPlatformState = {
  cart: [],
  surfaceFilters: {},
  onboardingCompleted: [],
  onboardingDismissed: [],
};

function arraysEqual(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  return left.every((value, index) => value === right[index]);
}

const BettingPlatformContext = createContext<BettingPlatformContextValue | null>(null);

export function BettingPlatformProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<BettingPlatformState>(defaultState);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as BettingPlatformState;
      setState({
        cart: Array.isArray(parsed.cart) ? parsed.cart : [],
        surfaceFilters: parsed.surfaceFilters ?? {},
        onboardingCompleted: Array.isArray(parsed.onboardingCompleted) ? parsed.onboardingCompleted : [],
        onboardingDismissed: Array.isArray(parsed.onboardingDismissed) ? parsed.onboardingDismissed : [],
      });
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const addCartLeg = useCallback((leg: ParlayCartLeg) => {
    let result: { added: boolean; reason?: string } = { added: true };
    setState((current) => {
      if (current.cart.some((item) => item.id === leg.id)) {
        result = { added: false, reason: "duplicate" };
        return current;
      }
      const sameEventConflict = current.cart.some(
        (item) =>
          item.eventId &&
          leg.eventId &&
          item.eventId === leg.eventId &&
          item.selectionKey !== leg.selectionKey
      );
      if (sameEventConflict) {
        result = { added: false, reason: "same_event_conflict" };
        return current;
      }
      return { ...current, cart: [...current.cart, leg] };
    });
    return result;
  }, []);

  const removeCartLeg = useCallback((legId: string) => {
    setState((current) => ({ ...current, cart: current.cart.filter((item) => item.id !== legId) }));
  }, []);

  const clearCart = useCallback(() => {
    setState((current) => (current.cart.length === 0 ? current : { ...current, cart: [] }));
  }, []);

  const setSurfaceFilters = useCallback((surface: ScannerSurface, filters: SurfaceFilters) => {
    setState((current) => {
      if (current.surfaceFilters[surface] === filters) {
        return current;
      }
      return {
        ...current,
        surfaceFilters: {
          ...current.surfaceFilters,
          [surface]: filters,
        },
      };
    });
  }, []);

  const markOnboardingCompleted = useCallback((step: string) => {
    setState((current) => {
      if (current.onboardingCompleted.includes(step)) {
        return current;
      }
      return {
        ...current,
        onboardingCompleted: [...current.onboardingCompleted, step],
      };
    });
  }, []);

  const dismissOnboardingStep = useCallback((step: string) => {
    setState((current) => {
      if (current.onboardingDismissed.includes(step)) {
        return current;
      }
      return {
        ...current,
        onboardingDismissed: [...current.onboardingDismissed, step],
      };
    });
  }, []);

  const hydrateOnboarding = useCallback((payload: { completed?: string[]; dismissed?: string[] } | null | undefined) => {
    setState((current) => {
      const nextCompleted = Array.isArray(payload?.completed) ? payload.completed : current.onboardingCompleted;
      const nextDismissed = Array.isArray(payload?.dismissed) ? payload.dismissed : current.onboardingDismissed;

      if (
        arraysEqual(current.onboardingCompleted, nextCompleted) &&
        arraysEqual(current.onboardingDismissed, nextDismissed)
      ) {
        return current;
      }

      return {
        ...current,
        onboardingCompleted: nextCompleted,
        onboardingDismissed: nextDismissed,
      };
    });
  }, []);

  const value = useMemo<BettingPlatformContextValue>(
    () => ({
      ...state,
      addCartLeg,
      removeCartLeg,
      clearCart,
      setSurfaceFilters,
      markOnboardingCompleted,
      dismissOnboardingStep,
      hydrateOnboarding,
    }),
    [
      addCartLeg,
      clearCart,
      dismissOnboardingStep,
      hydrateOnboarding,
      markOnboardingCompleted,
      removeCartLeg,
      setSurfaceFilters,
      state,
    ]
  );

  return <BettingPlatformContext.Provider value={value}>{children}</BettingPlatformContext.Provider>;
}

export function useBettingPlatformStore() {
  const context = useContext(BettingPlatformContext);
  if (!context) {
    throw new Error("useBettingPlatformStore must be used within BettingPlatformProvider");
  }
  return context;
}
