import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  // Base: tactile press, clear focus ring, no glow
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-40 active:translate-y-px select-none",
  {
    variants: {
      variant: {
        // Primary: warm gold — reserved for key actions, not universal chrome
        default:
          "bg-primary text-primary-foreground hover:bg-primary/85 shadow-sm active:shadow-none",
        destructive:
          "bg-destructive/15 text-destructive border border-destructive/30 hover:bg-destructive/25",
        // Outline: must look interactive — clear border, not dissolved
        outline:
          "border border-border bg-transparent text-foreground hover:bg-muted hover:border-border/80",
        secondary:
          "bg-secondary text-secondary-foreground border border-border/60 hover:bg-muted",
        // Ghost: no border at rest, but clear hover — for icon buttons and nav
        ghost:
          "text-muted-foreground hover:bg-muted hover:text-foreground",
        link: "text-primary underline-offset-4 hover:underline p-0 h-auto",
        // Sportsbook variants — identity colors, restrained opacity
        draftkings: "bg-draftkings/90 text-white hover:bg-draftkings shadow-sm",
        fanduel:    "bg-fanduel/90 text-white hover:bg-fanduel shadow-sm",
        betmgm:     "bg-betmgm/90 text-[#2C2416] hover:bg-betmgm shadow-sm",
        caesars:    "bg-caesars/90 text-white hover:bg-caesars shadow-sm",
        espnbet:    "bg-espnbet/90 text-white hover:bg-espnbet shadow-sm",
        fanatics:   "bg-fanatics/90 text-white hover:bg-fanatics shadow-sm",
        hardrock:   "bg-hardrock/90 text-white hover:bg-hardrock shadow-sm",
        bet365:     "bg-bet365/90 text-white hover:bg-bet365 shadow-sm",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm:      "h-8 rounded-md px-3 text-xs",
        lg:      "h-11 rounded-md px-8",
        icon:    "h-9 w-9",
        touch:   "h-12 px-6 py-3 text-base", // mobile touch target
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size }), className)}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
