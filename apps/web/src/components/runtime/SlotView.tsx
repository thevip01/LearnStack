"use client";

import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";
import { useMemo } from "react";
import { Tabs, tabPanelId } from "@/components/ui/Tabs";
import { slotKey, useWorkspaceStore } from "@/lib/store";
import type { Panel, Slot, SubjectRuntimeOut, LearningMode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PanelHost } from "./PanelHost";
import { panelLabel } from "./PanelRegistry";

const COLLAPSE_ICON: Record<Slot, { collapse: typeof ChevronLeft; expand: typeof ChevronLeft }> = {
  left: { collapse: ChevronLeft, expand: ChevronRight },
  right: { collapse: ChevronRight, expand: ChevronLeft },
  bottom: { collapse: ChevronDown, expand: ChevronUp },
  main: { collapse: ChevronDown, expand: ChevronUp },
};

/** A slot is only collapsible when every panel in it agreed to be. */
export function slotCollapsible(panels: Panel[]): boolean {
  return panels.length > 0 && panels.every((panel) => panel.collapsible);
}

export function slotDefaultCollapsed(panels: Panel[]): boolean {
  return slotCollapsible(panels) && panels.every((panel) => panel.default_collapsed);
}

/** The tab a slot opens on: first panel that did not ask to start collapsed. */
export function defaultPanelId(panels: Panel[]): string {
  return (panels.find((panel) => !panel.default_collapsed) ?? panels[0])?.id ?? "";
}

/**
 * One slot of the workspace.
 *
 * Several panels in one slot become tabs keyed by `panel.id`. Inactive tabs stay
 * mounted and hidden rather than unmounted: the exam layout puts a quiz and an
 * editor in the same slot, and glancing at one must not discard work in progress
 * in the other.
 */
export function SlotView({
  slot,
  panels,
  runtime,
  mode,
  nodeId,
}: {
  slot: Slot;
  panels: Panel[];
  runtime: SubjectRuntimeOut;
  mode: LearningMode;
  nodeId: string | null;
}) {
  const key = slotKey(runtime.id, mode, slot);
  const tabKey = `${key}:tab`;
  const storedTab = useWorkspaceStore((state) => state.activeTab[tabKey]);
  const setActiveTab = useWorkspaceStore((state) => state.setActiveTab);
  const toggleCollapsed = useWorkspaceStore((state) => state.toggleCollapsed);

  const fallback = useMemo(() => defaultPanelId(panels), [panels]);
  const active = panels.some((panel) => panel.id === storedTab) ? (storedTab as string) : fallback;
  const collapsible = slotCollapsible(panels);
  const Icon = COLLAPSE_ICON[slot].collapse;

  const items = useMemo(
    () => panels.map((panel) => ({ id: panel.id, label: panelLabel(panel) })),
    [panels],
  );

  const single = panels.length === 1 ? panels[0] : null;

  return (
    <section className="panel-chrome flex-1 border-line" aria-label={`${slot} panels`}>
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-line bg-raised/40 pr-1">
        {single ? (
          <h2 className="truncate px-pad py-1.5 text-2xs font-semibold uppercase tracking-wide text-muted">
            {panelLabel(single)}
          </h2>
        ) : (
          <Tabs
            items={items}
            active={active}
            onChange={(id) => setActiveTab(tabKey, id)}
            label={`${slot} slot panels`}
            idPrefix={key}
            size="xs"
            className="px-1"
          />
        )}
        {collapsible ? (
          <button
            type="button"
            onClick={() => toggleCollapsed(key)}
            aria-label={`Collapse ${slot} panel`}
            className="shrink-0 rounded p-1 text-faint hover:bg-raised hover:text-ink"
          >
            <Icon className="size-3.5" aria-hidden />
          </button>
        ) : null}
      </header>

      {panels.map((panel) => {
        const isActive = panel.id === active;
        return (
          <div
            key={panel.id}
            id={tabPanelId(key, panel.id)}
            role={single ? undefined : "tabpanel"}
            aria-label={single ? undefined : panelLabel(panel)}
            // `panel.config` is never read here; it goes straight to the component.
            className={isActive ? "flex min-h-0 flex-1 flex-col" : "hidden"}
            style={{ minWidth: panel.min_width ?? undefined, minHeight: panel.min_height ?? undefined }}
          >
            <PanelHost panel={panel} runtime={runtime} mode={mode} nodeId={nodeId} />
          </div>
        );
      })}
    </section>
  );
}

/** Collapsed slots keep their affordance: the labels stay readable and clickable. */
export function CollapsedRail({
  slot,
  panels,
  storeKey,
}: {
  slot: Slot;
  panels: Panel[];
  storeKey: string;
}) {
  const setCollapsed = useWorkspaceStore((state) => state.setCollapsed);
  const setActiveTab = useWorkspaceStore((state) => state.setActiveTab);
  const Icon = COLLAPSE_ICON[slot].expand;
  const vertical = slot === "left" || slot === "right";

  function expand(panelId?: string) {
    if (panelId) setActiveTab(`${storeKey}:tab`, panelId);
    setCollapsed(storeKey, false);
  }

  return (
    <div
      className={cn(
        "flex shrink-0 items-center gap-2 border-line bg-surface",
        vertical ? "w-8 flex-col border-x py-2" : "h-8 flex-row border-y px-2",
      )}
    >
      <button
        type="button"
        onClick={() => expand()}
        aria-label={`Expand ${slot} panel`}
        className="rounded p-1 text-faint hover:bg-raised hover:text-ink"
      >
        <Icon className="size-3.5" aria-hidden />
      </button>
      {panels.map((panel) => (
        <button
          key={panel.id}
          type="button"
          onClick={() => expand(panel.id)}
          className={cn(
            "whitespace-nowrap text-2xs uppercase tracking-wide text-faint hover:text-ink",
            vertical && "[writing-mode:vertical-rl]",
          )}
        >
          {panelLabel(panel)}
        </button>
      ))}
    </div>
  );
}
