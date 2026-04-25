"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, Grid2X2, History, MoreHorizontal, Activity, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { useBackendReadiness } from "@/lib/hooks";
import { hasUserFacingSyncIssue } from "@/lib/readiness-ui";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { ONBOARDING_HIGHLIGHT_TARGETS } from "@/lib/onboarding-guidance";
import { BankrollPill } from "@/components/bankroll/BankrollPill";

const tabs = [
  { href: "/",        label: "Markets", icon: Grid2X2  },
  { href: "/builder", label: "Builder", icon: BarChart3 },
  { href: "/bets",    label: "Bets",    icon: History   },
  { href: "/more",    label: "More",    icon: MoreHorizontal },
];

export function BottomNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuth();
  const { data: readiness } = useBackendReadiness();
  const { cart } = useBettingPlatformStore();

  if (pathname === "/login") return null;

  const showStatus = hasUserFacingSyncIssue(readiness);

  const handleSignOut = async () => {
    await signOut();
    router.push("/login");
    router.refresh();
  };

  const isTabActive = (href: string) => {
    if (href === "/") return pathname === "/" || pathname.startsWith("/markets");
    if (href === "/builder") return pathname.startsWith("/builder") || pathname.startsWith("/parlay");
    if (href === "/bets") return pathname.startsWith("/bets") || pathname.startsWith("/analytics");
    if (href === "/more") return pathname.startsWith("/more") || pathname.startsWith("/tools") || pathname.startsWith("/settings");
    return pathname.startsWith(href);
  };

  return (
    <>
      {/* Top header — slim logo + status strip */}
      <header className="safe-area-pt sticky top-0 z-20 border-b border-border bg-card/98 backdrop-blur-md">
        <div className="container mx-auto px-4 py-2.5 flex items-center justify-between max-w-2xl">
          <Link href="/" className="flex items-center gap-2 group">
            {/* Logo mark — foreground on background creates clear contrast in both modes */}
            <div className="w-7 h-7 rounded-md bg-foreground flex items-center justify-center">
              <span className="text-background font-bold text-xs tracking-tight">EV</span>
            </div>
            <span className="text-sm font-semibold text-foreground tracking-tight">Tracker</span>
          </Link>

          <div className="flex items-center gap-2">
            <BankrollPill />
            {/* Sync issue badge — semantic tokens, not hardcoded colors */}
            {showStatus && (
              <span
                className="flex items-center gap-1 rounded-md border border-color-loss/30 bg-color-loss-subtle px-2 py-0.5 text-[10px] font-medium text-color-loss-fg"
                title="Core services are temporarily unavailable"
              >
                <Activity className="h-3 w-3" />
                Sync issue
              </span>
            )}
            {/* Sign out — subordinate but readable, destructive on hover */}
            <button
              onClick={handleSignOut}
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:text-destructive hover:bg-muted transition-colors"
              title="Sign out"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </header>

      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 z-30 border-t border-border bg-card/98 backdrop-blur-md safe-area-pb">
        <div className="container mx-auto max-w-2xl">
          <div className="flex items-stretch">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const active = isTabActive(tab.href);
              const showBadge = tab.href === "/builder" && cart.length > 0;

              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  data-onboarding-target={
                    tab.href === "/"
                      ? ONBOARDING_HIGHLIGHT_TARGETS.NAV_MARKETS_TAB
                      : tab.href === "/bets"
                        ? ONBOARDING_HIGHLIGHT_TARGETS.NAV_BETS_TAB
                        : undefined
                  }
                  className={cn(
                    "relative flex flex-1 flex-col items-center justify-center gap-1 py-3 text-[11px] font-medium transition-colors",
                    // Active: full foreground. Inactive: muted — clear 2-level hierarchy
                    active
                      ? "text-foreground"
                      : "text-muted-foreground hover:text-foreground/80"
                  )}
                >
                  <div className="relative">
                    <Icon
                      className="h-5 w-5"
                      strokeWidth={active ? 2.25 : 1.75}
                    />
                    {showBadge && (
                      <span className="absolute -top-1.5 -right-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-0.5 text-[9px] font-bold text-primary-foreground">
                        {cart.length}
                      </span>
                    )}
                  </div>
                  <span>{tab.label}</span>
                  {/* Active indicator — top edge, primary color */}
                  {active && (
                    <span className="absolute top-0 left-1/2 h-0.5 w-8 -translate-x-1/2 rounded-full bg-primary" />
                  )}
                </Link>
              );
            })}
          </div>
        </div>
      </nav>
    </>
  );
}
