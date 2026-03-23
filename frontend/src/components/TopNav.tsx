"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Calculator, BarChart3, Settings, Home, LogOut, Radar, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { useBackendReadiness } from "@/lib/hooks";
import { useBettingPlatformStore } from "@/lib/betting-platform-store";

const navItems = [
  { href: "/", label: "Home", icon: Home },
  { href: "/scanner", label: "Scan", icon: Radar },
  { href: "/parlay", label: "Parlay", icon: Radar },
  { href: "/tools", label: "Tools", icon: Calculator },
  { href: "/analytics", label: "Stats", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuth();
  const { data: readiness } = useBackendReadiness();
  const { cart, scannerReviewCandidate } = useBettingPlatformStore();

  if (pathname === "/login") return null;

  const hasCrossSurfaceImpact = !!readiness && (
    readiness.status === "unreachable"
    || !readiness.checks.db_connectivity
    || !readiness.checks.supabase_env
  );

  const scheduledScanAgeSeconds = readiness?.scheduler_freshness?.jobs?.scheduled_scan?.age_seconds;
  const hasSustainedScannerDelay = typeof scheduledScanAgeSeconds === "number" && scheduledScanAgeSeconds >= 20 * 60;
  const showStatus = hasCrossSurfaceImpact || hasSustainedScannerDelay;

  const statusLabel = hasCrossSurfaceImpact
    ? "Sync issue"
    : "Updates delayed";

  const handleSignOut = async () => {
    await signOut();
    router.push("/login");
    router.refresh();
  };

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-card/90 backdrop-blur-sm">
      <div className="container mx-auto px-4 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="w-9 h-9 rounded-lg bg-[#2C2416] flex items-center justify-center shadow-sm">
            <span className="text-[#FAF8F5] font-bold text-sm tracking-tight">EV</span>
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground group-hover:text-foreground transition-colors">Expected Value</span>
            <span className="text-base font-semibold text-foreground">Tracker</span>
          </div>
        </Link>

        <nav className="flex items-center gap-1">
          {showStatus && (
            <span
              className="hidden md:inline-flex items-center gap-1.5 rounded-md border border-[#B85C38]/30 bg-[#B85C38]/10 px-2.5 py-1 text-[11px] font-medium text-[#8B3D20]"
              title="Some data may take longer than usual to refresh"
            >
              <Activity className="h-3.5 w-3.5" />
              {statusLabel}
            </span>
          )}
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-all tactile-btn",
                  "text-muted-foreground hover:text-foreground hover:bg-background",
                  isActive && "text-foreground bg-background border border-border shadow-sm"
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden sm:inline">{item.label}</span>
                {item.href === "/" && scannerReviewCandidate && (
                  <span
                    className="inline-flex min-w-5 items-center justify-center rounded-full bg-[#C4A35A] px-1.5 py-0.5 text-[10px] font-semibold text-[#2C2416]"
                    title="Saved scanner pick ready to review"
                  >
                    1
                  </span>
                )}
                {item.href === "/parlay" && cart.length > 0 && (
                  <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[#C4A35A] px-1.5 py-0.5 text-[10px] font-semibold text-[#2C2416]">
                    {cart.length}
                  </span>
                )}
                {isActive && (
                  <span className="absolute -bottom-[5px] left-1/2 h-0.5 w-8 -translate-x-1/2 rounded-full bg-[#C4A35A]" />
                )}
              </Link>
            );
          })}

          <button
            onClick={handleSignOut}
            className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:text-destructive hover:bg-background transition-all tactile-btn ml-1"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </nav>
      </div>
    </header>
  );
}
