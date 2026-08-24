"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { useHistory } from "@/lib/queries";
import { cfgStringArray } from "@/lib/utils";

/** The numeric series a history point can offer, with a label and a line colour. */
const SERIES_META: Record<string, { label: string; color: string; domain?: [number, number] }> = {
  overall: { label: "Overall mastery", color: "#6ea8fe", domain: [0, 1] },
  skills_mastered: { label: "Skills mastered", color: "#f0b429" },
};

function readWindowDays(config: Record<string, unknown>): number {
  const value = config.window_days;
  return typeof value === "number" && value > 0 ? value : 90;
}

function shortDate(iso: string): string {
  const parts = iso.split("-");
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : iso;
}

/**
 * A time series over mastery history: decay and recovery in `review`, progress
 * elsewhere. It is entirely data-driven: the layout names the series it wants in
 * `config.series`, and the panel plots exactly those that exist in the history
 * payload, silently skipping any the API does not (yet) emit. No series, colour or
 * axis is hard-coded to a subject.
 */
export function ChartPanel({ runtime, panel }: PanelProps) {
  const windowDays = readWindowDays(panel.config);
  const { data, isLoading, error } = useHistory(runtime.id, windowDays);

  const requested = useMemo(() => {
    const configured = cfgStringArray(panel.config, "series");
    return configured.length > 0 ? configured : ["overall", "skills_mastered"];
  }, [panel.config]);

  const points = useMemo(() => (data?.points ?? []).slice(-windowDays), [data, windowDays]);

  // Only plot series that both the layout asked for and the payload actually has.
  // Resolving the metadata here rather than re-indexing SERIES_META at each use
  // means the "is this a series we know about" question is answered exactly once.
  const series = useMemo(() => {
    if (points.length === 0) return [];
    const sample = points[0] as Record<string, unknown>;
    return requested.flatMap((key) => {
      const meta = SERIES_META[key];
      return meta && typeof sample[key] === "number" ? [{ key, ...meta }] : [];
    });
  }, [requested, points]);

  if (isLoading) return <PanelLoading label="Loading history" rows={5} />;
  if (error) return <PanelError error={error} />;
  if (points.length === 0) {
    return <PanelHint title="No history yet" description="Practice over a few days and the trend will show here." />;
  }
  if (series.length === 0) {
    return <PanelHint title="Nothing to plot" description="None of the requested series are present in the history." />;
  }

  return (
    <>
      <PanelToolbar>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {series.map(({ key, label, color }) => (
            <span key={key} className="inline-flex items-center gap-1.5 text-2xs text-muted">
              <span className="size-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
              {label}
            </span>
          ))}
        </div>
        <span className="ml-auto text-2xs text-faint">last {windowDays}d</span>
      </PanelToolbar>

      <PanelBody className="p-pad">
        <div className="h-full min-h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--os-line, #2a2f3a)" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={shortDate}
                tick={{ fontSize: 10, fill: "var(--os-faint, #8b93a1)" }}
                stroke="var(--os-line, #2a2f3a)"
                minTickGap={24}
              />
              <YAxis tick={{ fontSize: 10, fill: "var(--os-faint, #8b93a1)" }} stroke="var(--os-line, #2a2f3a)" width={44} />
              <Tooltip
                contentStyle={{
                  background: "var(--os-surface, #12151c)",
                  border: "1px solid var(--os-line, #2a2f3a)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelFormatter={(value) => shortDate(String(value))}
              />
              {series.map(({ key, label, color }) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={label}
                  stroke={color}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </PanelBody>
    </>
  );
}
