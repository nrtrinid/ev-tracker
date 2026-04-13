import { cn } from "@/lib/utils";

// Uses skeleton-shimmer from globals.css — warm gradient sweep, theme-aware
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-md skeleton-shimmer", className)}
      {...props}
    />
  );
}

export { Skeleton };
