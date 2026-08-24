"use client";

import { titleCase } from "@/lib/format";
import type { LearningMode, ModeLayout } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The mode segmented control in the runtime toolbar.
 *
 * The list of modes and their labels are entirely data: a subject that ships
 * only `learn` and `practice` shows two segments, one that ships all seven shows
 * seven. A mode the subject declares but has no layout for is shown disabled
 * rather than hidden, so the learner can see it exists but isn't built yet.
 */
export function ModeSwitcher({
  modes,
  layouts,
  active,
  onSelect,
}: {
  modes: LearningMode[];
  layouts: Partial<Record<LearningMode, ModeLayout>>;
  active: LearningMode;
  onSelect: (next: LearningMode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Learning mode"
      className="inline-flex items-center gap-0.5 rounded-md border border-line bg-canvas p-0.5"
    >
      {modes.map((mode) => {
        const layout = layouts[mode];
        const isActive = mode === active;
        return (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={!layout}
            title={layout ? undefined : `This subject has no "${mode}" workspace yet`}
            onClick={() => onSelect(mode)}
            className={cn(
              "rounded px-2 py-0.5 text-2xs font-medium capitalize transition-colors",
              "disabled:cursor-not-allowed disabled:opacity-40",
              isActive ? "bg-accent text-canvas" : "text-muted hover:bg-raised hover:text-ink",
            )}
          >
            {layout?.label ?? titleCase(mode)}
          </button>
        );
      })}
    </div>
  );
}
