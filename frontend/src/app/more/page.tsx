"use client";

import Link from "next/link";
import { Calculator, Settings, Shield, ScanLine } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

const moreLinks = [
  {
    href: "/tools",
    label: "Tools",
    description: "Hold calculator, odds conversion",
    icon: Calculator,
  },
  {
    href: "/settings",
    label: "Settings",
    description: "Kelly fraction, bankroll, sportsbooks, account",
    icon: Settings,
  },
];

const adminLinks = [
  {
    href: "/admin/ops",
    label: "Admin Ops",
    description: "Ops dashboard — admin only",
    icon: Shield,
  },
  {
    href: "/scanner/straight_bets",
    label: "Advanced Scanner",
    description: "Full scanner with lenses, filters, and boost tools",
    icon: ScanLine,
  },
];

export default function MorePage() {
  const { user } = useAuth();
  const adminEmails = (process.env.NEXT_PUBLIC_OPS_ADMIN_EMAILS || "").split(",").map((e) => e.trim().toLowerCase());
  const isAdmin = !!user?.email && adminEmails.includes(user.email.toLowerCase());

  return (
    <div className="container mx-auto px-4 py-6 max-w-2xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground mb-4">More</h1>
        <ul className="space-y-2">
          {moreLinks.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="flex items-center gap-4 rounded-lg border border-border bg-card px-4 py-3.5 hover:bg-muted transition-colors"
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
                    <Icon className="h-4.5 w-4.5 text-muted-foreground" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{item.label}</p>
                    <p className="text-xs text-muted-foreground truncate">{item.description}</p>
                  </div>
                </Link>
              </li>
            );
          })}
          {isAdmin &&
            adminLinks.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className="flex items-center gap-4 rounded-lg border border-border bg-card px-4 py-3.5 hover:bg-muted transition-colors"
                  >
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
                      <Icon className="h-4.5 w-4.5 text-muted-foreground" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground">{item.label}</p>
                      <p className="text-xs text-muted-foreground truncate">{item.description}</p>
                    </div>
                  </Link>
                </li>
              );
            })}
        </ul>
      </div>
    </div>
  );
}
