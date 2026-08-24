"use client";

import { FileCode } from "lucide-react";
import { NotWired } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { cfgString, cfgStringArray } from "@/lib/utils";

/**
 * An interactive notebook. A real notebook needs a persistent kernel that keeps
 * state between cells. The stateless execution sandbox in this phase cannot honor
 * that without silently re-running everything, which would be a lie about what a
 * notebook is. So rather than fake it, this renders an honest "not connected" state
 * that still describes, from the panel's own config, exactly how it will behave.
 */
export function NotebookPanel({ panel }: PanelProps) {
  const kernel = cfgString(panel.config, "kernel") ?? cfgString(panel.config, "language");
  const packages = cfgStringArray(panel.config, "packages");

  const shape = [
    kernel ? `Runs code cells against a ${kernel} kernel that keeps state between cells` : "Runs code cells against a stateful kernel",
    packages.length > 0 ? `Preloads ${packages.join(", ")}` : null,
    "Renders stdout, tables and figures inline beneath the cell that produced them",
    "Lets you edit, re-run and reorder cells",
  ].filter((line): line is string => Boolean(line));

  return (
    <NotWired
      title="Notebook isn't connected in this build"
      description="An interactive notebook needs a persistent kernel service, which lands in a later phase. Its behavior is already pinned by this panel's configuration."
      shape={shape}
      icon={<FileCode className="size-5" aria-hidden />}
    />
  );
}
