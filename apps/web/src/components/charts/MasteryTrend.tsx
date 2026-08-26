"use client";

import { useMemo } from "react";
import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
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
import { MASTERY_DIMENSIONS, type HistoryOut, type MasteryDimension } from "@/lib/types";

/**
 * Which axis to draw against overall when the caller does not say.
 *
 * Retention wins whenever there is any, because decay against progress is the
 * question the chart exists to answer. Before the learner has been away long
 * enough to forget anything there is no retention evidence at all, and drawing a
 * legend for an absent line is worse than drawing the axis they have actually been
 * measured on. So the fallback is whichever axis carries the most days of evidence.
 */
function pickDimension(points: HistoryOut["points"]): MasteryDimension {
  const days = new Map<MasteryDimension, number>();
  for (const point of points) {
    for (const key of MASTERY_DIMENSIONS) {
      if (point.dimensions?.[key]?.measured) days.set(key, (days.get(key) ?? 0) + 1);
    }
  }
  if ((days.get("retention") ?? 0) > 0) return "retention";
  let best: MasteryDimension = "retention";
  let bestDays = 0;
  for (const [key, count] of days) {
    if (count > bestDays) {
      best = key;
      bestDays = count;
    }
  }
  return best;
}

/**
 * Mastery over time, with a second axis drawn against it when there is any.
 *
 * The two share one scale on purpose: both are 0 to 1, and the gap between them is
 * the interesting quantity. Retention below overall means the learner is passing new
 * material while forgetting old material, which is the exact shape a review mode
 * exists to fix, and it is invisible on a single-line chart.
 *
 * Days with no evidence for an axis are gaps rather than zeros, and `connectNulls`
 * is off so the line breaks instead of drawing a slope through a day that measured
 * nothing.
 */
export function MasteryTrend({
  points,
  dimension,
}: {
  points: HistoryOut["points"];
  /** The axis to draw against overall. Chosen from the evidence when omitted. */
  dimension?: MasteryDimension;
}) {
  const axis = useMemo(() => dimension ?? pickDimension(points), [dimension, points]);
  const rows = useMemo(
    () =>
      points.map((point) => {
        const entry = point.dimensions?.[axis];
        return {
          date: point.date,
          overall: point.overall,
          axis: entry?.measured ? entry.score : null,
        };
      }),
    [points, axis],
  );

  const axisDays = rows.filter((row) => row.axis !== null).length;
  const hasAxis = axisDays > 0;
  const moved = rows.some((row) => row.overall > 0);

  if (rows.length < 2 || !moved) {
    return (
      <p className="py-6 text-center text-2xs text-faint">
        Not enough history yet. Each day you practise adds a point, and the curve is replayed from evidence rather than
        stored, so it fills in as soon as there is something to plot.
      </p>
    );
  }

  return (
    <div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {/* The left margin used to be negative to tuck the axis in, which cut the
              tick labels in half: "100" rendered as "i0" and "25" as ".5". The axis
              owns its width instead. */}
          <AreaChart data={rows} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="masteryTrendFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={SERIES_COLORS[0]} stopOpacity={0.35} />
                <stop offset="100%" stopColor={SERIES_COLORS[0]} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={CHART.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              tick={AXIS_TICK}
              stroke={CHART.grid}
              minTickGap={28}
              tickLine={false}
            />
            <YAxis
              domain={[0, 1]}
              tickFormatter={percentTick}
              tick={AXIS_TICK}
              stroke={CHART.grid}
              width={30}
              tickLine={false}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={TOOLTIP_LABEL_STYLE}
              labelFormatter={(value) => shortDate(String(value))}
              formatter={(value) => (typeof value === "number" ? `${Math.round(value * 100)}%` : "no evidence")}
            />
            <Area
              type="monotone"
              dataKey="overall"
              name="Overall"
              stroke={SERIES_COLORS[0]}
              strokeWidth={2}
              fill="url(#masteryTrendFill)"
              isAnimationActive={false}
              connectNulls={false}
            />
            {hasAxis ? (
              <Line
                type="monotone"
                dataKey="axis"
                name={DIMENSION_LABELS[axis]}
                stroke={SERIES_COLORS[3]}
                strokeWidth={1.75}
                strokeDasharray="4 3"
                // A day whose neighbours are both gaps has no segment to draw, so
                // the first measurement on an axis is invisible without a dot. Once
                // there are enough days to form a line the dots are just noise.
                dot={axisDays <= 3 ? { r: 2, strokeWidth: 0, fill: SERIES_COLORS[3] } : false}
                isAnimationActive={false}
                connectNulls={false}
              />
            ) : null}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-2xs text-faint">
        {hasAxis
          ? `Solid is overall mastery, dashed is ${DIMENSION_LABELS[axis].toLowerCase()}.`
          : `Overall mastery. A second axis is drawn as soon as one has evidence on more than one day.`}
      </p>
      <TrendStats rows={rows} />
    </div>
  );
}

/**
 * What the curve is worth saying in numbers.
 *
 * Three facts a shape cannot state: where the peak was, whether the window moved
 * up or down, and on how many of those days there was any evidence at all. The last
 * one matters most: a flat line means something different when it comes from thirty
 * days of nothing than from thirty days of steady work, and the chart alone cannot
 * tell those apart. All three come from the points already fetched, so this costs
 * no request.
 */
function TrendStats({ rows }: { rows: Array<{ date: string; overall: number; axis: number | null }> }) {
  const first = rows[0];
  const last = rows[rows.length - 1];
  if (!first || !last) return null;

  const peak = rows.reduce((best, row) => (row.overall > best.overall ? row : best), first);
  // Percentage points, not percent: a move from 20% to 40% is 20 points, and calling
  // it "+100%" would be a different and wrong claim.
  const change = Math.round((last.overall - first.overall) * 100);
  const measuredDays = rows.filter((row) => row.axis !== null || row.overall > 0).length;

  return (
    <dl className="mt-2.5 grid grid-cols-3 gap-2 border-t border-line pt-2.5">
      <Stat label="Peak" value={`${Math.round(peak.overall * 100)}%`} hint={shortDate(peak.date)} />
      <Stat label="Window" value={change === 0 ? "flat" : `${change > 0 ? "+" : ""}${change} pts`} />
      <Stat label="Days with evidence" value={`${measuredDays}/${rows.length}`} />
    </dl>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-2xs text-faint">{label}</dt>
      <dd className="text-xs font-medium text-ink">
        {value}
        {hint ? <span className="ml-1 text-2xs font-normal text-faint">{hint}</span> : null}
      </dd>
    </div>
  );
}
