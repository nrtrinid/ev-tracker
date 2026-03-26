import * as React from "react";
import { cn } from "@/lib/utils";


type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          // Logbook underline style — colors from CSS variables (light + dark)
          "flex h-10 w-full bg-transparent px-1 py-2 text-sm text-foreground",
          "border-0 border-b-2 border-border rounded-none",
          "placeholder:text-muted-foreground/60",
          "focus:outline-none focus:border-primary focus:bg-muted/50",
          "transition-colors duration-150",
          "disabled:cursor-not-allowed disabled:opacity-50",
          // Larger touch target on mobile
          "md:h-10 h-12",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
