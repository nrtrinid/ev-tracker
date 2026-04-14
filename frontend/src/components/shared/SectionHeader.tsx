import * as React from "react";

import { cn } from "@/lib/utils";

interface SectionHeaderProps {
  label: string;
  action?: React.ReactNode;
  className?: string;
}

export function SectionHeader({ label, action, className }: SectionHeaderProps) {
  return (
    <div className={cn("border-b border-border/70 pb-2", className)}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-muted-foreground">
          {label}
        </p>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </div>
  );
}
