import * as React from "react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: React.ReactNode;
  value: React.ReactNode;
  secondary?: React.ReactNode;
  valueClassName?: string;
  className?: string;
  contentClassName?: string;
  onClick?: () => void;
  affordance?: React.ReactNode;
  ariaLabel?: string;
  dataTestId?: string;
  triggerTestId?: string;
}

function MetricCardInner({
  label,
  value,
  secondary,
  valueClassName,
  affordance,
  contentClassName,
}: Omit<MetricCardProps, "className" | "onClick" | "ariaLabel" | "dataTestId" | "triggerTestId">) {
  return (
    <CardContent className={cn("px-3 py-3", contentClassName)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        {affordance}
      </div>
      <p className={cn("mt-1.5 font-mono text-lg font-semibold tabular-nums leading-none", valueClassName)}>
        {value}
      </p>
      {secondary ? (
        <p className="mt-1.5 font-mono text-[11px] tabular-nums text-muted-foreground/70">
          {secondary}
        </p>
      ) : null}
    </CardContent>
  );
}

export function MetricCard({
  label,
  value,
  secondary,
  valueClassName,
  className,
  contentClassName,
  onClick,
  affordance,
  ariaLabel,
  dataTestId,
  triggerTestId,
}: MetricCardProps) {
  const inner = (
    <MetricCardInner
      label={label}
      value={value}
      secondary={secondary}
      valueClassName={valueClassName}
      affordance={affordance}
      contentClassName={contentClassName}
    />
  );

  if (!onClick) {
    return (
      <Card data-testid={dataTestId} className={cn("border-border/50", className)}>
        {inner}
      </Card>
    );
  }

  return (
    <button
      type="button"
      data-testid={triggerTestId}
      aria-label={ariaLabel ?? "Open details"}
      onClick={onClick}
      className="w-full rounded-lg text-left transition-transform duration-100 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
    >
      <Card data-testid={dataTestId} className={cn("border-border/50 transition-colors hover:border-border hover:bg-muted/20 active:bg-muted/30", className)}>
        {inner}
      </Card>
    </button>
  );
}

interface MetricTileProps {
  label: React.ReactNode;
  value: React.ReactNode;
  valueClassName?: string;
  className?: string;
}

export function MetricTile({ label, value, valueClassName, className }: MetricTileProps) {
  return (
    <div className={cn("rounded border border-border/40 bg-background/30 px-3 py-2.5", className)}>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={cn("mt-1.5 font-mono text-xl font-semibold tabular-nums leading-none", valueClassName)}>
        {value}
      </p>
    </div>
  );
}
