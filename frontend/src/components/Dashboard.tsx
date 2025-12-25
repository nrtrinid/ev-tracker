"use client";

import { Card, CardContent } from "@/components/ui/card";
import { useSummary } from "@/lib/hooks";
import { formatCurrency, cn } from "@/lib/utils";
import { TrendingUp, DollarSign, Target, BarChart3 } from "lucide-react";
import Link from "next/link";

export function Dashboard() {
  const { data: summary, isLoading } = useSummary();

  if (isLoading || !summary) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <div className="h-4 w-16 animate-pulse bg-muted rounded mb-2" />
              <div className="h-8 w-24 animate-pulse bg-muted rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const stats = [
    {
      label: "Total EV",
      value: formatCurrency(summary.total_ev),
      icon: TrendingUp,
      color: summary.total_ev >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]",
    },
    {
      label: "Real Profit",
      value: formatCurrency(summary.total_real_profit),
      icon: DollarSign,
      color: summary.total_real_profit >= 0 ? "text-[#4A7C59]" : "text-[#B85C38]",
    },
    {
      label: "Variance",
      value: formatCurrency(summary.variance),
      icon: BarChart3,
      color: "text-muted-foreground",
      subtitle: "Profit − EV",
    },
    {
      label: "Record",
      value: `${summary.win_count}–${summary.loss_count}`,
      icon: Target,
      color: "text-foreground",
      subtitle: summary.win_rate
        ? `${(summary.win_rate * 100).toFixed(0)}% win rate`
        : undefined,
    },
  ];

  return (
    <Link href="/analytics" className="block">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 group">
        {stats.map((stat) => (
          <Card key={stat.label} className="card-hover">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-1">
                <stat.icon className="h-4 w-4" />
                <span className="text-xs font-medium uppercase tracking-wide">{stat.label}</span>
              </div>
              <p className={cn("text-2xl font-bold font-mono tracking-tight", stat.color)}>{stat.value}</p>
              {stat.subtitle && (
                <p className="text-xs text-muted-foreground">{stat.subtitle}</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </Link>
  );
}
