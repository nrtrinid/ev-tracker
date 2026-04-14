import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11px] font-medium",
  {
    variants: {
      family: {
        status: "border border-border/70 bg-muted/30 text-muted-foreground",
        source: "border border-border/70 bg-card text-muted-foreground",
        state: "border border-border/70 bg-muted/20 text-foreground",
        count: "border border-border/70 bg-background px-1 tabular-nums text-muted-foreground",
      },
      outcome: {
        none: "",
        win: "",
        loss: "",
        pending: "",
        push: "",
        void: "",
      },
    },
    compoundVariants: [
      {
        family: "status",
        outcome: "win",
        className: "border-color-profit/35 bg-color-profit-subtle text-color-profit-fg",
      },
      {
        family: "status",
        outcome: "loss",
        className: "border-color-loss/35 bg-color-loss-subtle text-color-loss-fg",
      },
      {
        family: "status",
        outcome: "pending",
        className: "border-color-pending/35 bg-color-pending-subtle text-color-pending-fg",
      },
      {
        family: "status",
        outcome: "push",
        className: "border-border/70 bg-muted/20 text-muted-foreground",
      },
      {
        family: "status",
        outcome: "void",
        className: "border-border/70 bg-muted/20 text-muted-foreground opacity-70",
      },
    ],
    defaultVariants: {
      family: "status",
      outcome: "none",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, family, outcome, ...props }: BadgeProps) {
  return (
    <span
      className={cn(badgeVariants({ family, outcome }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
