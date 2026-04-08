import * as React from "react";
import { cn } from "@/lib/utils";


type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          // Logbook underline style - like fill-in-the-blank
          "flex h-10 w-full bg-transparent px-1 py-2 text-sm",
          "border-0 border-b-2 border-input rounded-none",
          "placeholder:text-muted-foreground/60",
          "focus:outline-none focus:border-primary focus:bg-muted/40",
          "caret-primary selection:bg-primary/40 selection:text-foreground",
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
