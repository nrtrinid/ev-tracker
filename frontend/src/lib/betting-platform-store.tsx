"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth-context";

import type {
  ParlayCartLeg,
  ScannedBetData,
  ScannerSurface,
  TutorialPracticeBet,
  TutorialSession,
} from "@/lib/types";

type SurfaceFilters = Record<string, unknown>;

export interface ScannerReviewCandidate {
  surface: ScannerSurface;
  bet: ScannedBetData;
  createdAt: string;
}

interface BettingPlatformState {
  cart: ParlayCartLeg[];
  cartStakeInput: string;
  activeParlaySlipId: string | null;
  surfaceFilters: Partial<Record<ScannerSurface, SurfaceFilters>>;
  scannerReviewCandidate: ScannerReviewCandidate | null;
  tutorialSession: TutorialSession | null;
  onboardingCompleted: string[];
  onboardingDismissed: string[];
}

interface BettingPlatformContextValue extends BettingPlatformState {
  isHydrated: boolean;
  addCartLeg: (leg: ParlayCartLeg) => { added: boolean; reason?: string };
  removeCartLeg: (legId: string) => void;
  clearCart: () => void;
  replaceCart: (cart: ParlayCartLeg[], options?: { stakeInput?: string; activeParlaySlipId?: string | null }) => void;
  setCartStakeInput: (stakeInput: string) => void;
  setActiveParlaySlipId: (slipId: string | null) => void;
  setSurfaceFilters: (surface: ScannerSurface, filters: SurfaceFilters) => void;
  setScannerReviewCandidate: (candidate: ScannerReviewCandidate | null) => void;
  clearScannerReviewCandidate: () => void;
  startTutorialSession: (surface?: ScannerSurface) => void;
  markTutorialScanSeeded: () => void;
  saveTutorialPracticeBet: (bet: TutorialPracticeBet) => void;
  clearTutorialSession: () => void;
  markOnboardingCompleted: (step: string) => void;
  dismissOnboardingStep: (step: string) => void;
  hydrateOnboarding: (
    payload: { completed?: string[]; dismissed?: string[] } | null | undefined,
    source?: "local" | "remote"
  ) => void;
}

const STORAGE_KEY_PREFIX = "ev-tracker-betting-platform";

const defaultState: BettingPlatformState = {
  cart: [],
  cartStakeInput: "10.00",
  activeParlaySlipId: null,
  surfaceFilters: {},
  scannerReviewCandidate: null,
  tutorialSession: null,
  onboardingCompleted: [],
  onboardingDismissed: [],
};

function arraysEqual(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  return left.every((value, index) => value === right[index]);
}

const BettingPlatformContext = createContext<BettingPlatformContextValue | null>(null);

export function BettingPlatformProvider({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const storageKey = `${STORAGE_KEY_PREFIX}:${user?.id ?? "guest"}`;
  const [state, setState] = useState<BettingPlatformState>(defaultState);
  const [isHydrated, setIsHydrated] = useState(false);

  const persistBettingPlatformState = useCallback((nextState: BettingPlatformState) => {
    if (typeof window === "undefined" || loading || !isHydrated) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(nextState));
    } catch {
      // Ignore storage write failures and fall back to the effect-based persistence path.
    }
  }, [isHydrated, loading, storageKey]);

  useEffect(() => {
    if (loading) return;
    if (typeof window === "undefined") return;
    setIsHydrated(false);
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      setState(defaultState);
      setIsHydrated(true);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as BettingPlatformState;
      setState({
        cart: Array.isArray(parsed.cart) ? parsed.cart : [],
        cartStakeInput: typeof parsed.cartStakeInput === "string" ? parsed.cartStakeInput : "10.00",
        activeParlaySlipId: typeof parsed.activeParlaySlipId === "string" ? parsed.activeParlaySlipId : null,
        surfaceFilters: parsed.surfaceFilters ?? {},
        scannerReviewCandidate: parsed.scannerReviewCandidate ?? null,
        tutorialSession: parsed.tutorialSession ?? null,
        onboardingCompleted: Array.isArray(parsed.onboardingCompleted) ? parsed.onboardingCompleted : [],
        onboardingDismissed: Array.isArray(parsed.onboardingDismissed) ? parsed.onboardingDismissed : [],
      });
    } catch {
      window.localStorage.removeItem(storageKey);
      setState(defaultState);
    }
    setIsHydrated(true);
  }, [loading, storageKey]);

  useEffect(() => {
    if (loading || !isHydrated) return;
    if (typeof window === "undefined") return;
    window.localStorage.setItem(storageKey, JSON.stringify(state));
  }, [isHydrated, loading, state, storageKey]);

  const addCartLeg = useCallback((leg: ParlayCartLeg) => {
    let result: { added: boolean; reason?: string } = { added: true };
    setState((current) => {
      if (current.cart.some((item) => item.id === leg.id)) {
        result = { added: false, reason: "duplicate" };
        return current;
      }
      const lockedSportsbook = current.cart[0]?.sportsbook;
      if (lockedSportsbook && lockedSportsbook !== leg.sportsbook) {
        result = { added: false, reason: "sportsbook_mismatch" };
        return current;
      }
      return { ...current, cart: [...current.cart, leg] };
    });
    return result;
  }, []);

  const removeCartLeg = useCallback((legId: string) => {
    setState((current) => {
      const nextCart = current.cart.filter((item) => item.id !== legId);
      return {
        ...current,
        cart: nextCart,
        activeParlaySlipId: nextCart.length === 0 ? null : current.activeParlaySlipId,
      };
    });
  }, []);

  const clearCart = useCallback(() => {
    setState((current) => (
      current.cart.length === 0 && current.activeParlaySlipId === null
        ? current
        : { ...current, cart: [], activeParlaySlipId: null }
    ));
  }, []);

  const replaceCart = useCallback((
    cart: ParlayCartLeg[],
    options?: { stakeInput?: string; activeParlaySlipId?: string | null }
  ) => {
    setState((current) => ({
      ...current,
      cart,
      cartStakeInput: options?.stakeInput ?? current.cartStakeInput,
      activeParlaySlipId:
        options?.activeParlaySlipId !== undefined ? options.activeParlaySlipId : current.activeParlaySlipId,
    }));
  }, []);

  const setCartStakeInput = useCallback((stakeInput: string) => {
    setState((current) => (
      current.cartStakeInput === stakeInput
        ? current
        : { ...current, cartStakeInput: stakeInput }
    ));
  }, []);

  const setActiveParlaySlipId = useCallback((slipId: string | null) => {
    setState((current) => (
      current.activeParlaySlipId === slipId
        ? current
        : { ...current, activeParlaySlipId: slipId }
    ));
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

  const setScannerReviewCandidate = useCallback((candidate: ScannerReviewCandidate | null) => {
    setState((current) => {
      if (current.scannerReviewCandidate === candidate) {
        return current;
      }
      return {
        ...current,
        scannerReviewCandidate: candidate,
      };
    });
  }, []);

  const clearScannerReviewCandidate = useCallback(() => {
    setState((current) => {
      if (current.scannerReviewCandidate === null) {
        return current;
      }
      const nextState = { ...current, scannerReviewCandidate: null };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const startTutorialSession = useCallback((surface: ScannerSurface = "straight_bets") => {
    setState((current) => {
      const nextState: BettingPlatformState = {
        ...current,
        scannerReviewCandidate: null,
        tutorialSession: {
          surface,
          step: "scanner_empty",
          has_seeded_scan: false,
          practice_bet: null,
          started_at: current.tutorialSession?.started_at ?? new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const markTutorialScanSeeded = useCallback(() => {
    setState((current) => {
      const existing = current.tutorialSession;
      const baseStartedAt = existing?.started_at ?? new Date().toISOString();
      const nextState: BettingPlatformState = {
        ...current,
        tutorialSession: {
          surface: existing?.surface ?? "straight_bets",
          step: "scanner_ready",
          has_seeded_scan: true,
          practice_bet: existing?.practice_bet ?? null,
          started_at: baseStartedAt,
          updated_at: new Date().toISOString(),
        },
      };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const saveTutorialPracticeBet = useCallback((bet: TutorialPracticeBet) => {
    setState((current) => {
      const nextState: BettingPlatformState = {
        ...current,
        scannerReviewCandidate: null,
        tutorialSession: {
          surface: "straight_bets",
          step: "home_review",
          has_seeded_scan: true,
          practice_bet: bet,
          started_at: current.tutorialSession?.started_at ?? new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const clearTutorialSession = useCallback(() => {
    setState((current) => {
      if (current.tutorialSession === null) {
        return current;
      }
      const nextState = { ...current, tutorialSession: null };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const markOnboardingCompleted = useCallback((step: string) => {
    setState((current) => {
      if (current.onboardingCompleted.includes(step)) {
        return current;
      }
      const nextState = {
        ...current,
        onboardingCompleted: [...current.onboardingCompleted, step],
      };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const dismissOnboardingStep = useCallback((step: string) => {
    setState((current) => {
      if (current.onboardingDismissed.includes(step)) {
        return current;
      }
      const nextState = {
        ...current,
        onboardingDismissed: [...current.onboardingDismissed, step],
      };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const hydrateOnboarding = useCallback((
    payload: { completed?: string[]; dismissed?: string[] } | null | undefined,
    source: "local" | "remote" = "local"
  ) => {
    setState((current) => {
      const payloadCompleted = Array.isArray(payload?.completed) ? payload.completed : current.onboardingCompleted;
      const payloadDismissed = Array.isArray(payload?.dismissed) ? payload.dismissed : current.onboardingDismissed;
      const nextCompleted =
        source === "remote" && current.onboardingCompleted.length > 0 && payloadCompleted.length === 0
          ? current.onboardingCompleted
          : payloadCompleted;
      const nextDismissed =
        source === "remote" && current.onboardingDismissed.length > 0 && payloadDismissed.length === 0
          ? current.onboardingDismissed
          : payloadDismissed;

      if (
        arraysEqual(current.onboardingCompleted, nextCompleted) &&
        arraysEqual(current.onboardingDismissed, nextDismissed)
      ) {
        return current;
      }

      const nextState = {
        ...current,
        onboardingCompleted: nextCompleted,
        onboardingDismissed: nextDismissed,
      };
      persistBettingPlatformState(nextState);
      return nextState;
    });
  }, [persistBettingPlatformState]);

  const value = useMemo<BettingPlatformContextValue>(
    () => ({
      ...state,
      isHydrated,
      addCartLeg,
      removeCartLeg,
      clearCart,
      replaceCart,
      setCartStakeInput,
      setActiveParlaySlipId,
      setSurfaceFilters,
      setScannerReviewCandidate,
      clearScannerReviewCandidate,
      startTutorialSession,
      markTutorialScanSeeded,
      saveTutorialPracticeBet,
      clearTutorialSession,
      markOnboardingCompleted,
      dismissOnboardingStep,
      hydrateOnboarding,
    }),
    [
      addCartLeg,
      clearCart,
      clearScannerReviewCandidate,
      clearTutorialSession,
      dismissOnboardingStep,
      hydrateOnboarding,
      markOnboardingCompleted,
      markTutorialScanSeeded,
      replaceCart,
      removeCartLeg,
      saveTutorialPracticeBet,
      setActiveParlaySlipId,
      setCartStakeInput,
      setScannerReviewCandidate,
      setSurfaceFilters,
      startTutorialSession,
      state,
      isHydrated,
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
