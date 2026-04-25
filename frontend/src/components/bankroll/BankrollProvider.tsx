"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { BankrollDrawer } from "@/components/bankroll/BankrollDrawer";

type BankrollDrawerOptions = {
  sportsbook?: string;
};

type BankrollDrawerContextValue = {
  openBankrollDrawer: (options?: BankrollDrawerOptions) => void;
  closeBankrollDrawer: () => void;
};

const BankrollDrawerContext = createContext<BankrollDrawerContextValue | null>(null);

export function BankrollProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [initialSportsbook, setInitialSportsbook] = useState<string | null>(null);

  const openBankrollDrawer = useCallback((options?: BankrollDrawerOptions) => {
    setInitialSportsbook(options?.sportsbook ?? null);
    setOpen(true);
  }, []);

  const closeBankrollDrawer = useCallback(() => {
    setOpen(false);
  }, []);

  const value = useMemo(
    () => ({
      openBankrollDrawer,
      closeBankrollDrawer,
    }),
    [closeBankrollDrawer, openBankrollDrawer],
  );

  return (
    <BankrollDrawerContext.Provider value={value}>
      {children}
      <BankrollDrawer
        open={open}
        onOpenChange={setOpen}
        initialSportsbook={initialSportsbook}
      />
    </BankrollDrawerContext.Provider>
  );
}

export function useBankrollDrawer() {
  const context = useContext(BankrollDrawerContext);
  if (!context) {
    throw new Error("useBankrollDrawer must be used inside BankrollProvider");
  }
  return context;
}
