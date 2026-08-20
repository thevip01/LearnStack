import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The honest empty state. Used both for "nothing here yet" and for the panels
 * whose backend does not exist in this phase: it names what is missing instead
 * of implying the workspace is broken.
 */
export function EmptyState({
  title,
  description,
  icon,
  actions,
  tone = "neutral",
  className,
  children,
}: {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  tone?: "neutral" | "pending" | "error";
  className?: string;
  children?: ReactNode;
}) {
  const border =
    tone === "error" ? "border-danger/40" : tone === "pending" ? "border-line-strong border-dashed" : "border-line";
  return (
    <div className={cn("flex h-full min-h-0 flex-col items-center justify-center gap-3 p-6 text-center", className)}>
      <div className={cn("w-full max-w-md rounded-panel border bg-surface/60 p-5", border)}>
        {icon ? <div className="mb-2 flex justify-center text-faint">{icon}</div> : null}
        <div className={cn("text-sm font-semibold", tone === "error" ? "text-danger" : "text-ink")}>{title}</div>
        {description ? <div className="mt-1.5 text-xs leading-relaxed text-muted">{description}</div> : null}
        {children ? <div className="mt-3 text-left">{children}</div> : null}
        {actions ? <div className="mt-4 flex justify-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

/** Shows the shape a panel will take once its endpoint exists. */
export function PlannedShape({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item} className="flex items-start gap-2 text-2xs text-faint">
          <span aria-hidden className="mt-1 size-1.5 shrink-0 rounded-full border border-line-strong" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}
