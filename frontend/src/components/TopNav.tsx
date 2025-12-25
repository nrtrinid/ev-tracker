"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calculator, BarChart3, Settings, Home } from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Home", icon: Home },
  { href: "/tools", label: "Tools", icon: Calculator },
  { href: "/analytics", label: "Stats", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function TopNav() {
  const pathname = usePathname();

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
                {isActive && (
                  <span className="absolute -bottom-[5px] left-1/2 h-0.5 w-8 -translate-x-1/2 rounded-full bg-[#C4A35A]" />
                )}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
