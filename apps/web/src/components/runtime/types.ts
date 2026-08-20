import type { ComponentType } from "react";
import type { LearningMode, Panel, SubjectRuntimeOut } from "@/lib/types";

/**
 * The contract between the layout and every panel.
 *
 * It is deliberately tiny and identical for all thirty panel types: the layout
 * knows nothing about what a panel does, and a panel receives the subject
 * runtime plus its own declaration. `panel.config` is handed over untouched —
 * the layout never reads a key out of it.
 */
export type PanelProps = {
  panel: Panel;
  runtime: SubjectRuntimeOut;
  mode: LearningMode;
  /** The selected navigation item (`?node=`), or null when nothing is selected. */
  nodeId: string | null;
};

export type PanelComponent = ComponentType<PanelProps>;
