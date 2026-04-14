import * as React from "react";

import { cn } from "@/lib/utils";

export interface FolderTabItem<T extends string> {
  value: T;
  content: React.ReactNode;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}

interface FolderTabsProps<T extends string> {
  value: T;
  items: FolderTabItem<T>[];
  onValueChange: (value: T) => void;
  className?: string;
  triggerClassName?: string;
}

export function FolderTabs<T extends string>({
  value,
  items,
  onValueChange,
  className,
  triggerClassName,
}: FolderTabsProps<T>) {
  return (
    <div className={cn("flex gap-1 -mx-0", className)}>
      {items.map((item) => {
        const active = item.value === value;

        return (
          <button
            key={item.value}
            type="button"
            aria-pressed={active}
            aria-label={item.ariaLabel}
            disabled={item.disabled}
            onClick={() => onValueChange(item.value)}
            className={cn(
              "folder-tab flex-1 flex items-center justify-center gap-2 transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60",
              active ? "folder-tab-active" : "folder-tab-inactive",
              triggerClassName,
              item.className,
            )}
          >
            {item.content}
          </button>
        );
      })}
    </div>
  );
}