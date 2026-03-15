import * as React from "react";
import { cn } from "@/lib/utils";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          // Logbook underline style - like fill-in-the-blank
          "flex h-10 w-full bg-transparent px-1 py-2 text-sm",
          "border-0 border-b-2 border-[#DDD5C7] rounded-none",
          "placeholder:text-muted-foreground/60",
          "focus:outline-none focus:border-[#C4A35A] focus:bg-[#FAF8F5]",
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
