"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { describeError } from "@/lib/api";
import {
  AXIS_TICK,
  CHART,
  percentTick,
  SERIES_COLORS,
  shortDate,
  TOOLTIP_LABEL_STYLE,
  TOOLTIP_STYLE,
} from "@/lib/chartTheme";
import { DIMENSION_LABELS } from "@/lib/format";
import { useHistory } from "@/lib/queries";
import { MASTERY_DIMENSIONS, type HistoryOut, type MasteryDimension } from "@/lib/types";
import { cfgStringArray } from "@/lib/utils";

/** Everything a layout may name in `config.series`, with how to label and scale it. */
const SERIES_META: Record<string, { label: string; percent: boolean }> = {
  overall: { label: "Overall mastery", percent: true },
  skills_mastered: { label: "Skills mastered", percent: false },
  ...Object.fromEntries(
    MASTERY_DIMENSIONS.map((dimension) => [dimension, { label: DIMENSION_LABELS[dimension], percent: true }]),
  ),
};

type Row = Record<string, string | number | null>;

/**
 * Flattens a history point so a dimension can be plotted by name.
 *
 * `{ dimensions: { retention: { score, measured } } }` becomes `{ retention: score }`,
 * with an unmeasured axis landing as `null` rather than `0`. That is what makes a
 * layout asking for `["overall", "retention"]` work, which this repo's python
 * package has asked for since it was written.
 */
function toRow(point: HistoryOut["points"][number]): Row {
  const row: Row = {
    date: point.date,
    overall: point.overall,
    skills_mastered: point.skills_mastered,
  };
  for (const dimension of MASTERY_DIMENSIONS) {
    const entry = point.dimensions?.[dimension as MasteryDimension];
    row[dimension] = entry?.measured ? entry.score : null;
  }
  return row;
}

function readWindowDays(config: Record<string, unknown>): number {
  const value = config.window_days;
  return typeof value === "number" && value > 0 ? value : 90;
}

/**
 * A time series over mastery history: decay and recovery in `review`, progress
 * elsewhere. It is entirely data-driven: the layout names the series it wants in
 * `config.series` and the panel plots the ones the payload can support. No series,
 * colour or axis is hard-coded to a subject.
 *
 * Two things here are deliberate and were both bugs before. A series counts as
 * available when *any* day carries a number for it, not when the first day does: an
 * axis first measured last Tuesday used to be dropped because day one of the window
 * was empty. And a series the layout asked for that has no data is named in the
 * toolbar instead of vanishing, because a chart quietly missing a line is
 * indistinguishable from a chart whose line is flat at zero.
 *
 * Percentages and counts also get separate axes. Plotting "0.42 overall" and "3
 * skills mastered" against one scale flattens the interesting one into the floor.
 */
export function ChartPanel({ runtime, panel }: PanelProps) {
  const windowDays = readWindowDays(panel.config);
  const { data, isLoading, error } = useHistory(runtime.id, windowDays);

  const requested = useMemo(() => {
    const configured = cfgStringArray(panel.config, "series");
    return configured.length > 0 ? configured : ["overall", "skills_mastered"];
  }, [panel.config]);

  const rows = useMemo(() => (data?.points ?? []).slice(-windowDays).map(toRow), [data, windowDays]);

  const resolved = useMemo(() => {
    const plotted: Array<{ key: string; label: string; percent: boolean; color: string }> = [];
    const empty: string[] = [];
    const unknown: string[] = [];

    for (const key of requested) {
      const meta = SERIES_META[key];
      if (!meta) {
        unknown.push(key);
        continue;
      }
      if (!rows.some((row) => typeof row[key] === "number")) {
        empty.push(meta.label);
        continue;
      }
      plotted.push({
        key,
        label: meta.label,
        percent: meta.percent,
        color: SERIES_COLORS[plotted.length % SERIES_COLORS.length] ?? SERIES_COLORS[0],
      });
    }
    return { plotted, empty, unknown };
  }, [requested, rows]);

  if (isLoading) return <PanelLoading label="Loading history" rows={5} />;
  if (error) {
    // History is the one progress read that needs a session, so a visitor gets an
    // explanation rather than a red box.
    if (describeError(error).code === "unauthorized") {
      return (
        <PanelHint
          title="Sign in to see your history"
          description="The curve is replayed from your own evidence, so there is nothing to draw for a visitor."
        />
      );
    }
    return <PanelError error={error} />;
  }
  if (rows.length === 0) {
    return <PanelHint title="No history yet" description="Practice over a few days and the trend will show here." />;
  }
  if (resolved.plotted.length === 0) {
    return (
      <PanelHint
        title="Nothing to plot yet"
        description={
          resolved.empty.length > 0
            ? `No evidence recorded yet for ${resolved.empty.join(", ").toLowerCase()}.`
            : "None of the requested series exist in the history payload."
        }
      />
    );
  }

  const hasPercent = resolved.plotted.some((series) => series.percent);
  const hasCount = resolved.plotted.some((series) => !series.percent);

  return (
    <>
      <PanelToolbar>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {resolved.plotted.map(({ key, label, color }) => (
            <span key={key} className="inline-flex items-center gap-1.5 text-2xs text-muted">
              <span className="size-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
              {label}
            </span>
          ))}
          {resolved.empty.length > 0 ? (
            <span className="text-2xs text-faint" title="Asked for by this layout, with no evidence recorded yet">
              no evidence yet: {resolved.empty.join(", ").toLowerCase()}
            </span>
          ) : null}
          {resolved.unknown.length > 0 ? (
            <span className="text-2xs text-warn" title="This layout named a series the API does not emit">
              unknown series: {resolved.unknown.join(", ")}
            </span>
          ) : null}
        </div>
        <span className="ml-auto text-2xs text-faint">last {windowDays}d</span>
      </PanelToolbar>

      <PanelBody className="p-pad">
        <div className="h-full min-h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            {/* No negative left margin: it clips the y tick labels to their second
                half, which reads as a broken font rather than as a layout bug. */}
            <LineChart data={rows} margin={{ top: 8, right: 10, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={shortDate}
                tick={AXIS_TICK}
                stroke={CHART.grid}
                minTickGap={24}
                tickLine={false}
              />
              {hasPercent ? (
                <YAxis
                  yAxisId="percent"
                  domain={[0, 1]}
                  tickFormatter={percentTick}
                  tick={AXIS_TICK}
                  stroke={CHART.grid}
                  width={30}
                  tickLine={false}
                />
              ) : null}
              {hasCount ? (
                <YAxis
                  yAxisId="count"
                  orientation="right"
                  allowDecimals={false}
                  tick={AXIS_TICK}
                  stroke={CHART.grid}
                  width={30}
                  tickLine={false}
                />
              ) : null}
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={TOOLTIP_LABEL_STYLE}
                labelFormatter={(value) => shortDate(String(value))}
              />
              {resolved.plotted.map(({ key, label, color, percent }) => (
                <Line
                  key={key}
                  yAxisId={percent ? "percent" : "count"}
                  type="monotone"
                  dataKey={key}
                  name={label}
                  stroke={color}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </PanelBody>
    </>
  );
}
