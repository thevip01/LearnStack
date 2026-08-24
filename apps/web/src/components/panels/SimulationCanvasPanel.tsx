"use client";

import { Boxes } from "lucide-react";
import { NotWired } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { cfgString, cfgStringArray } from "@/lib/utils";

/**
 * An interactive simulation canvas. It needs a physics/agent engine that is not
 * part of this phase, so rather than show a dead canvas it renders an honest
 * "not connected" state describing the controls and behavior it will expose, with the
 * scenario and its parameters all read from this panel's own configuration.
 */
export function SimulationCanvasPanel({ panel }: PanelProps) {
  const scenario = cfgString(panel.config, "scenario") ?? cfgString(panel.config, "sim");
  const parameters = cfgStringArray(panel.config, "parameters");

  const shape = [
    scenario ? `Runs the ${scenario} simulation with play, step and reset controls` : "Runs the simulation with play, step and reset controls",
    parameters.length > 0 ? `Exposes ${parameters.join(", ")} as live controls` : null,
    "Redraws the canvas on every simulation tick",
  ].filter((line): line is string => Boolean(line));

  return (
    <NotWired
      title="Simulation isn't connected in this build"
      description="An interactive simulation needs a physics or agent engine, which lands in a later phase. Its scenario and controls are already pinned by this panel's configuration."
      shape={shape}
      icon={<Boxes className="size-5" aria-hidden />}
    />
  );
}
