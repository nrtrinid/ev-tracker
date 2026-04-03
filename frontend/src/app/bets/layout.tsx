"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useBets } from "@/lib/hooks";
import {
  buildTrackerViewQuery,
  DEFAULT_TRACKER_VIEW_STATE,
  parseTrackerSourceFilter,
  parseTrackerTab,
} from "@/lib/tracker-view";
import { cn } from "@/lib/utils";

export default function BetsLayout({ children }: { children: React.ReactNode }) {
  const { data: bets } = useBets();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [filterOpen, setFilterOpen] = useState(false);

  const isStats = pathname === "/bets/stats";
  const activeTab = parseTrackerTab(searchParams.get("tab"));
  const sourceFilter = parseTrackerSourceFilter(searchParams.get("source"));
  const selectedBook = searchParams.get("sportsbook") ?? DEFAULT_TRACKER_VIEW_STATE.sportsbook;
  const search = searchParams.get("search") ?? DEFAULT_TRACKER_VIEW_STATE.search;

  const activeFilterCount = [
    sourceFilter !== "all",
    selectedBook !== "all",
  ].filter(Boolean).length;

  const uniqueBooks = useMemo(() => {
    if (!bets) return [];
    return Array.from(new Set(bets.map((bet) => bet.sportsbook))).sort();
  }, [bets]);

  const queryString = searchParams.toString();
  const betsHref = queryString ? `/bets?${queryString}` : "/bets";
  const statsHref = queryString ? `/bets/stats?${queryString}` : "/bets/stats";

  const updateSharedFilters = (updates: Partial<{ source: "all" | "core" | "promos"; sportsbook: string }>) => {
    const query = buildTrackerViewQuery({
      tab: activeTab,
      source: updates.source ?? sourceFilter,
      sportsbook: updates.sportsbook ?? selectedBook,
      search,
    });
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const clearFilters = () => {
    updateSharedFilters({ source: "all", sportsbook: "all" });
  };

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-border/80 bg-background/95 backdrop-blur-sm">
        <div className="container mx-auto max-w-3xl px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex w-fit gap-1 rounded-lg bg-muted p-1">
            <Link
              href={betsHref}
              className={cn(
                "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
                !isStats
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              Bets
            </Link>
            <Link
              href={statsHref}
              className={cn(
                "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
                isStats
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              Stats
            </Link>
            </div>

            <button
              onClick={() => setFilterOpen(true)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                activeFilterCount > 0
                  ? "bg-foreground text-background"
                  : "bg-muted text-muted-foreground hover:bg-secondary"
              )}
            >
              <SlidersHorizontal className="h-4 w-4" />
              <span className="hidden sm:inline">Filter</span>
              {activeFilterCount > 0 && (
                <span className="ml-0.5 px-1.5 py-0.5 text-xs rounded-full bg-background text-foreground">
                  {activeFilterCount}
                </span>
              )}
            </button>
          </div>
        </div>
      </div>

      <Sheet open={filterOpen} onOpenChange={setFilterOpen}>
        <SheetContent side="bottom" className="px-6 pb-8">
          <SheetHeader className="pb-4">
            <div className="flex items-center justify-between">
              <SheetTitle>Refine Bets + Stats</SheetTitle>
              {activeFilterCount > 0 && (
                <button
                  onClick={clearFilters}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Clear all
                </button>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              These filters apply to both Tracker and Stats.
            </p>
          </SheetHeader>

          <div className="space-y-4">
            <div>
              <span className="text-xs text-muted-foreground font-medium block mb-2">Sportsbook</span>
              <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
                <button
                  onClick={() => updateSharedFilters({ sportsbook: "all" })}
                  className={cn(
                    "px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0",
                    selectedBook === "all"
                      ? "bg-foreground text-background shadow-sm"
                      : "bg-muted text-muted-foreground hover:bg-secondary"
                  )}
                >
                  All Books
                </button>
                {uniqueBooks.map((book) => (
                  <button
                    key={book}
                    onClick={() => updateSharedFilters({ sportsbook: book })}
                    className={cn(
                      "px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0",
                      selectedBook === book
                        ? "bg-foreground text-background shadow-sm"
                        : "bg-muted text-muted-foreground hover:bg-secondary"
                    )}
                  >
                    {book}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className="text-xs text-muted-foreground font-medium block mb-2">Source</span>
              <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
                {([
                  { key: "all", label: "All Bets" },
                  { key: "core", label: "Core Bets" },
                  { key: "promos", label: "Promos" },
                ] as const).map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => updateSharedFilters({ source: key })}
                    className={cn(
                      "px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap shrink-0",
                      sourceFilter === key
                        ? "bg-foreground text-background shadow-sm"
                        : "bg-muted text-muted-foreground hover:bg-secondary"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="pt-6">
            <SheetClose asChild>
              <Button className="w-full" size="lg">
                Apply Filters
              </Button>
            </SheetClose>
          </div>
        </SheetContent>
      </Sheet>

      {children}
    </div>
  );
}
