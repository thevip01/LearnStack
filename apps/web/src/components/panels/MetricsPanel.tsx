"use client";

import { Gauge } from "lucide-react";
import { NotWired } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { cfgString, cfgStringArray } from "@/lib/utils";

/**
 * A live metrics dashboard. There is no telemetry stream in this phase: the only
 * runtime numbers available are a single run's resource usage, which is not the
 * continuous signal a metrics panel implies. Rather than dress up a one-shot value
 * as a live gauge, this renders an honest "not connected" state describing what the
 * panel will show, drawn from its own configuration.
 */
export function MetricsPanel({ panel }: PanelProps) {
  const metrics = cfgStringArray(panel.config, "metrics");
  const refresh = cfgString(panel.config, "refresh") ?? cfgString(panel.config, "interval");

  const shape = [
    metrics.length > 0 ? `Streams ${metrics.join(", ")} from the running system` : "Streams live metrics from the running system",
    refresh ? `Refreshes every ${refresh}` : "Refreshes on a fixed interval",
    "Shows each metric's current value, recent trend and threshold state",
  ].filter((line): line is string => Boolean(line));

  return (
    <NotWired
      title="Metrics aren't connected in this build"
      description="A live metrics dashboard needs a telemetry stream, which lands in a later phase. What it will display is already pinned by this panel's configuration."
      shape={shape}
      icon={<Gauge className="size-5" aria-hidden />}
    />
  );
}
