"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { PUBLIC_SCANNER_SURFACES } from "./scanner-surfaces";

export default function ScannerLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <>
      <div className="sticky top-[49px] z-10 border-b border-border bg-background/90 backdrop-blur-sm">
        <div className="container mx-auto flex max-w-2xl gap-2 px-4 py-3">
          {PUBLIC_SCANNER_SURFACES.map((surface) => {
            const isActive = pathname === surface.path;
            return (
              <Link
                key={surface.id}
                href={surface.path}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "border-primary/70 bg-primary/18 text-foreground font-semibold"
                    : "border-border text-muted-foreground hover:text-foreground hover:border-border/80"
                )}
              >
                {surface.label}
              </Link>
            );
          })}
        </div>
      </div>
      {children}
    </>
  );
}
