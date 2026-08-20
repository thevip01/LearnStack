"use client";

import type { ReactNode } from "react";
import { useMemo } from "react";
import { Split } from "@/components/ui/Split";
import { slotKey, useWorkspaceStore } from "@/lib/store";
import { type LearningMode, type ModeLayout, type Panel, type Slot, type SubjectRuntimeOut } from "@/lib/types";
import { CollapsedRail, SlotView, slotCollapsible, slotDefaultCollapsed } from "./SlotView";

/**
 * Baselines for a slot's initial size. `min_width`/`min_height` raise the floor;
 * `flex` scales it. The schema calls `flex` "share of the slot when several
 * panels stack in it" — panels in one slot are tabbed rather than stacked, so
 * there is no share to divide and the declared share becomes the slot's own
 * weight against its siblings. A package asking for `flex: 3` on the main panel
 * therefore still gets a wide main area.
 */
const SIDEBAR_BASE = 220;
const DOCK_BASE = 160;
const SIDEBAR_MAX = 640;
const DOCK_MAX = 620;

function slotSize(panels: Panel[], axis: "width" | "height"): { initial: number; min: number; max: number } {
  const declared = panels
    .map((panel) => (axis === "width" ? panel.min_width : panel.min_height))
    .filter((value): value is number => typeof value === "number" && value > 0);
  const floor = declared.length > 0 ? Math.max(...declared) : axis === "width" ? 200 : 120;
  const weight = Math.max(...panels.map((panel) => panel.flex), 0.1);
  const base = axis === "width" ? SIDEBAR_BASE : DOCK_BASE;
  const max = axis === "width" ? SIDEBAR_MAX : DOCK_MAX;
  return { initial: Math.min(Math.max(Math.round(base * weight), floor), max), min: floor, max };
}

function groupBySlot(panels: Panel[]): Record<Slot, Panel[]> {
  const grouped: Record<Slot, Panel[]> = { left: [], main: [], right: [], bottom: [] };
  for (const panel of panels) {
    // An unknown slot cannot happen through the schema, but a hand-edited
    // package should degrade into the centre rather than vanish.
    (grouped[panel.slot] ?? grouped.main).push(panel);
  }
  return grouped;
}

/**
 * Arranges `mode_layouts[mode].panels` into the four slots: collapsible left and
 * right sidebars, a centre, and a bottom dock. It reads nothing from a panel
 * except the fields ui.py defines, which is what keeps the runtime generic.
 */
export function LayoutRenderer({
  runtime,
  mode,
  layout,
  nodeId,
}: {
  runtime: SubjectRuntimeOut;
  mode: LearningMode;
  layout: ModeLayout;
  nodeId: string | null;
}) {
  const grouped = useMemo(() => groupBySlot(layout.panels), [layout.panels]);
  const collapsedMap = useWorkspaceStore((state) => state.collapsed);
  const sizes = useWorkspaceStore((state) => state.sizes);
  const setSize = useWorkspaceStore((state) => state.setSize);

  function slotState(slot: Slot) {
    const panels = grouped[slot];
    const key = slotKey(runtime.id, mode, slot);
    const stored = collapsedMap[key];
    return {
      panels,
      key,
      collapsed: (stored ?? slotDefaultCollapsed(panels)) && slotCollapsible(panels),
      view: <SlotView slot={slot} panels={panels} runtime={runtime} mode={mode} nodeId={nodeId} />,
    };
  }

  const left = slotState("left");
  const right = slotState("right");
  const bottom = slotState("bottom");
  const main = slotState("main");

  /** Wraps `children` in a resizable pane for one slot, or a rail when collapsed. */
  function wrap(
    slot: Slot,
    state: ReturnType<typeof slotState>,
    axis: "width" | "height",
    invert: boolean,
    children: ReactNode,
  ): ReactNode {
    if (state.panels.length === 0) return children;
    if (state.collapsed) {
      const rail = <CollapsedRail slot={slot} panels={state.panels} storeKey={state.key} />;
      return (
        <div className={axis === "width" ? "flex min-h-0 min-w-0 flex-1 flex-row" : "flex min-h-0 min-w-0 flex-1 flex-col"}>
          {invert ? null : rail}
          <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">{children}</div>
          {invert ? rail : null}
        </div>
      );
    }
    const { initial, min, max } = slotSize(state.panels, axis);
    return (
      <Split
        orientation={axis === "width" ? "vertical" : "horizontal"}
        size={sizes[state.key] ?? initial}
        min={min}
        max={max}
        invert={invert}
        onResize={(px) => setSize(state.key, px)}
        label={`Resize ${slot} panel`}
        pane={state.view}
      >
        {children}
      </Split>
    );
  }

  const centre =
    main.panels.length > 0 ? (
      main.view
    ) : (
      <div className="flex flex-1 items-center justify-center p-6 text-xs text-faint">
        This mode declares no panel in the centre slot.
      </div>
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {wrap("left", left, "width", false, wrap("right", right, "width", true, wrap("bottom", bottom, "height", true, centre)))}
    </div>
  );
}
