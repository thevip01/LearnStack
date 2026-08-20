"use client";

import type { ReactNode } from "react";
import { EmptyState, PlannedShape } from "@/components/ui/EmptyState";
import { SkeletonText } from "@/components/ui/Skeleton";
import { describeError } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Scrolling body. Panels are height-constrained by the layout, never by content. */
export function PanelBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("panel-scroll", className)}>{children}</div>;
}

/** Action row that stays put while the body scrolls. */
export function PanelToolbar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex shrink-0 flex-wrap items-center gap-1.5 border-b border-line bg-surface px-pad py-1",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-1.5 flex items-center justify-between gap-2">
      <h3 className="text-2xs font-semibold uppercase tracking-wide text-faint">{children}</h3>
      {actions}
    </div>
  );
}

export function PanelLoading({ label = "Loading", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <PanelBody className="p-pad">
      <span className="sr-only">{label}</span>
      <SkeletonText rows={rows} />
    </PanelBody>
  );
}

export function PanelError({ error, title }: { error: unknown; title?: string }) {
  const described = describeError(error);
  return <EmptyState tone="error" title={title ?? described.title} description={described.message} />;
}

/**
 * Honest state for a panel whose backend is not part of this phase.
 *
 * It shows the shape the panel will take rather than pretending to work, because
 * a learner meeting an empty rectangle cannot tell "nothing here yet" from
 * "this product is broken".
 */
export function NotWired({
  title,
  description,
  shape,
  icon,
  children,
}: {
  title: string;
  description: ReactNode;
  shape: string[];
  icon?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <PanelBody className="p-pad">
      <EmptyState tone="pending" title={title} description={description} icon={icon} className="p-0">
        <div className="space-y-2">
          <div className="text-2xs font-semibold uppercase tracking-wide text-faint">Intended shape</div>
          <PlannedShape items={shape} />
          {children}
        </div>
      </EmptyState>
    </PanelBody>
  );
}

/** Nothing to render yet, but not an error: no node selected, no task chosen. */
export function PanelHint({ title, description }: { title: string; description?: ReactNode }) {
  return <EmptyState title={title} description={description} />;
}
