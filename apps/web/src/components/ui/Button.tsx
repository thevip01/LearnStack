"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type Size = "xs" | "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-canvas hover:bg-accent/90 border-accent",
  secondary: "bg-raised text-ink hover:bg-line border-line",
  ghost: "bg-transparent text-muted hover:text-ink hover:bg-raised border-transparent",
  danger: "bg-danger/15 text-danger hover:bg-danger/25 border-danger/40",
  outline: "bg-transparent text-ink hover:bg-raised border-line-strong",
};

const SIZES: Record<Size, string> = {
  xs: "h-6 px-2 text-2xs gap-1",
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /** Renders the disabled affordance while keeping the label readable. */
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "sm", loading = false, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={rest.type ?? "button"}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md border font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <span className="size-3 animate-spin rounded-full border border-current border-t-transparent" /> : null}
      {children}
    </button>
  );
});
