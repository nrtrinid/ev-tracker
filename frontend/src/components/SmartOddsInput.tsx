"use client";

import { useState, useEffect, useRef, useImperativeHandle, forwardRef } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface SmartOddsInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  defaultSign?: "+" | "-";
  americanOddsSeed?: number | null;
  inputRef?: React.RefObject<HTMLInputElement>;
  className?: string;
  label?: string;
}

export interface SmartOddsInputRef {
  getSignedValue: () => number;
  isPositive: boolean;
  focus: () => void;
}

export const SmartOddsInput = forwardRef<SmartOddsInputRef, SmartOddsInputProps>(
  function SmartOddsInput(
    {
      value,
      onChange,
      placeholder = "150",
      defaultSign = "+",
      americanOddsSeed = null,
      inputRef,
      className,
      label,
    },
    ref
  ) {
    const [isPositive, setIsPositive] = useState(defaultSign === "+");
    const internalRef = useRef<HTMLInputElement>(null);
    const inputElementRef = inputRef || internalRef;

    // Expose signed value getter via ref
    useImperativeHandle(ref, () => ({
      getSignedValue: () => {
        const num = parseFloat(value) || 0;
        return isPositive ? Math.abs(num) : -Math.abs(num);
      },
      isPositive,
      focus: () => {
        inputElementRef.current?.focus();
      },
    }));

    // Only infer sign when the parent gives us an explicitly signed value or when the field resets.
    useEffect(() => {
      const trimmedValue = value.trim();
      if (trimmedValue.startsWith("-") || trimmedValue.startsWith("+")) {
        setIsPositive(!trimmedValue.startsWith("-"));
        onChange(trimmedValue.replace(/^[+-]/, ""));
      } else {
        if (typeof americanOddsSeed === "number" && americanOddsSeed !== 0) {
          setIsPositive(americanOddsSeed >= 0);
        } else {
          setIsPositive(defaultSign === "+");
        }
      }
    }, [americanOddsSeed, defaultSign, onChange, value]);

    const handleToggleSign = () => {
      setIsPositive(!isPositive);
    };

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      let inputValue = e.target.value;

      // Smart paste: detect "-" and auto-flip sign
      if (inputValue.includes("-")) {
        setIsPositive(false);
        inputValue = inputValue.replace(/-/g, "").replace(/\+/g, "");
      } else if (inputValue.includes("+")) {
        setIsPositive(true);
        inputValue = inputValue.replace(/\+/g, "");
      }

      // Only allow numbers and decimal point
      inputValue = inputValue.replace(/[^\d.]/g, "");

      // Prevent multiple decimal points
      const parts = inputValue.split(".");
      if (parts.length > 2) {
        inputValue = parts[0] + "." + parts.slice(1).join("");
      }

      // Store only absolute value
      onChange(inputValue);
    };

    return (
      <div className={cn("min-w-0 space-y-1.5", className)}>
        {label && (
          <label className="text-xs font-medium text-muted-foreground block">
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {/* Sign Toggle Button */}
          <button
            type="button"
            onClick={handleToggleSign}
            className={cn(
              "h-12 w-10 flex items-center justify-center rounded-l-md border-r border-input bg-background font-mono text-base font-medium transition-all shrink-0",
              isPositive
                ? "text-[#4A7C59] hover:bg-[#4A7C59]/5 hover:border-[#4A7C59]/20"
                : "text-[#B85C38] hover:bg-[#B85C38]/5 hover:border-[#B85C38]/20"
            )}
            tabIndex={-1}
          >
            {isPositive ? "+" : "-"}
          </button>

          {/* Input Field */}
          <Input
            ref={inputElementRef}
            type="text"
            inputMode="decimal"
            placeholder={placeholder}
            value={value}
            onChange={handleInputChange}
            className={cn(
              "min-w-0 h-12 text-lg font-mono text-center rounded-l-none border-l-0",
              className
            )}
          />
        </div>
      </div>
    );
  }
);

