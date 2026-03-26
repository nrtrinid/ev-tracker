"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export default function BetsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isStats = pathname === "/bets/stats";

  return (
    <div>
      {/* Segment tabs — non-sticky, scrolls with page content */}
      <div className="container mx-auto px-4 pt-4 pb-0 max-w-2xl">
        <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
          <Link
            href="/bets"
            className={cn(
              "px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
              !isStats
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Bets
          </Link>
          <Link
            href="/bets/stats"
            className={cn(
              "px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
              isStats
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Stats
          </Link>
        </div>
      </div>
      {children}
    </div>
  );
}
