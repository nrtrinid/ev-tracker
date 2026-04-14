import * as React from "react";

import { cn } from "@/lib/utils";

export interface FilterOption<T extends string = string> {
  value: T;
  label: React.ReactNode;
  className?: string;
}

interface FilterChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  children: React.ReactNode;
}

export function FilterChip({ className, children, ...props }: FilterChipProps) {
  return (
    <span
      className={cn(
        "rounded border border-border/60 bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground",
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

export interface FilterChipItem {
  key: string;
  label: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

interface FilterChipListProps {
  chips: FilterChipItem[];
  maxVisible?: number;
  className?: string;
  chipClassName?: string;
  overflowClassName?: string;
  overflowLabel?: (hiddenCount: number) => React.ReactNode;
}

export function FilterChipList({
  chips,
  maxVisible,
  className,
  chipClassName,
  overflowClassName,
  overflowLabel,
}: FilterChipListProps) {
  if (!chips.length) return null;

  const limit = typeof maxVisible === "number" ? Math.max(0, maxVisible) : chips.length;
  const visible = chips.slice(0, limit);
  const hiddenCount = Math.max(chips.length - visible.length, 0);

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {visible.map((chip) => (
        <FilterChip key={chip.key} className={cn(chipClassName, chip.className)} style={chip.style}>
          {chip.label}
        </FilterChip>
      ))}
      {hiddenCount > 0 && (
        <FilterChip
          className={cn(
            "border-border bg-background text-[10px] text-muted-foreground",
            overflowClassName,
          )}
        >
          {overflowLabel ? overflowLabel(hiddenCount) : `+${hiddenCount} more`}
        </FilterChip>
      )}
    </div>
  );
}

interface SingleSelectFilterPillsProps<T extends string> {
  value: T;
  options: Array<FilterOption<T>>;
  onValueChange: (value: T) => void;
  className?: string;
  baseButtonClassName?: string;
  activeClassName?: string;
  inactiveClassName?: string;
  getButtonClassName?: (option: FilterOption<T>, active: boolean) => string | undefined;
}

export function SingleSelectFilterPills<T extends string>({
  value,
  options,
  onValueChange,
  className,
  baseButtonClassName = "rounded-md border px-2.5 py-1 text-xs font-medium transition-all duration-200 active:scale-95",
  activeClassName = "border-primary/40 bg-primary/10 text-foreground",
  inactiveClassName = "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
  getButtonClassName,
}: SingleSelectFilterPillsProps<T>) {
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onValueChange(option.value)}
            className={cn(
              baseButtonClassName,
              active ? activeClassName : inactiveClassName,
              option.className,
              getButtonClassName?.(option, active),
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

interface MultiSelectFilterPillsProps<T extends string> {
  selectedValues: readonly T[];
  options: Array<FilterOption<T>>;
  onToggleValue: (value: T) => void;
  className?: string;
  baseButtonClassName?: string;
  activeClassName?: string;
  inactiveClassName?: string;
  getButtonClassName?: (option: FilterOption<T>, active: boolean) => string | undefined;
}

export function MultiSelectFilterPills<T extends string>({
  selectedValues,
  options,
  onToggleValue,
  className,
  baseButtonClassName = "rounded-md border px-2.5 py-1 text-xs font-medium transition-all duration-200 active:scale-95",
  activeClassName = "border-primary/40 bg-primary/10 text-foreground",
  inactiveClassName = "border-border text-muted-foreground hover:text-foreground hover:bg-muted",
  getButtonClassName,
}: MultiSelectFilterPillsProps<T>) {
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {options.map((option) => {
        const active = selectedValues.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onToggleValue(option.value)}
            className={cn(
              baseButtonClassName,
              active ? activeClassName : inactiveClassName,
              option.className,
              getButtonClassName?.(option, active),
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}