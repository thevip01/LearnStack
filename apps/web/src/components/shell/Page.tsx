import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Scrolling container for content routes (catalogue, progress, search, admin…).
 * The workspace route deliberately does not use this: the runtime fills the
 * frame and manages its own internal scrolling.
 */
export function PageShell({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="panel-scroll">
      <div className={cn("mx-auto w-full max-w-6xl px-pad py-6", className)}>{children}</div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  back,
  glyph,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
  /** Identity mark for the thing this page is about, drawn from its package icon. */
  glyph?: ReactNode;
}) {
  return (
    <div className="mb-5">
      {back ? (
        <Link href={back.href} className="mb-2 inline-flex items-center gap-1 text-2xs text-muted hover:text-ink">
          <ChevronLeft className="size-3" aria-hidden />
          {back.label}
        </Link>
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          {glyph}
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-ink">{title}</h1>
            {subtitle ? <div className="mt-0.5 text-xs text-muted">{subtitle}</div> : null}
          </div>
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
