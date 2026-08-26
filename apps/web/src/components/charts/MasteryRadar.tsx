"use client";

import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { AXIS_TICK, CHART, SERIES_COLORS } from "@/lib/chartTheme";
import { DASH, DIMENSION_LABELS } from "@/lib/format";
import { MASTERY_DIMENSIONS, type DimensionMap } from "@/lib/types";

/**
 * The six mastery axes as a shape rather than as six unrelated bars.
 *
 * The shape is the point. Six bars answer "how am I doing on production" one at a
 * time; the polygon answers "what kind of learner am I so far", and a spike on
 * concept with nothing on lab is visible in one glance instead of six.
 *
 * An unmeasured axis is `null`, not `0`. Recharts then leaves that vertex out and
 * the polygon reads as open, which is the truthful drawing: plotting zero would
 * claim the learner failed an axis they have never been tested on. The axes with no
 * evidence are also named underneath, because an open polygon says "something is
 * missing here" without saying what.
 */
export function MasteryRadar({ dimensions }: { dimensions: DimensionMap }) {
  const rows = MASTERY_DIMENSIONS.map((dimension) => {
    const entry = dimensions[dimension];
    return {
      dimension,
      label: DIMENSION_LABELS[dimension],
      score: entry?.measured ? entry.score : null,
    };
  });

  const unmeasured = rows.filter((row) => row.score === null);
  const measuredCount = rows.length - unmeasured.length;

  if (measuredCount === 0) {
    return (
      <p className="py-6 text-center text-2xs text-faint">
        {DASH} nothing measured yet. Submit one attempt and the shape appears.
      </p>
    );
  }

  return (
    <div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={rows} outerRadius="70%" margin={{ top: 6, right: 6, bottom: 6, left: 6 }}>
            <PolarGrid stroke={CHART.grid} />
            <PolarAngleAxis dataKey="label" tick={{ ...AXIS_TICK, fill: CHART.labelFill }} />
            {/* The rings are the scale. Numbering them drew "50" and "100" rotated
                across the polygon at whatever angle recharts picked, and the exact
                values are already in the bars underneath. */}
            <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} tickLine={false} />
            <Radar
              dataKey="score"
              stroke={SERIES_COLORS[0]}
              fill={SERIES_COLORS[0]}
              fillOpacity={0.24}
              strokeWidth={2}
              // A polygon with one vertex has no area and no edges, so the first
              // measured axis would otherwise draw nothing at all. The dots make
              // one measurement visible and cost nothing once the shape closes.
              dot={{ r: 2.5, fill: SERIES_COLORS[0], strokeWidth: 0 }}
              isAnimationActive={false}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
      {unmeasured.length > 0 ? (
        <p className="mt-1 text-center text-2xs text-faint">
          {DASH} no evidence yet on{" "}
          {unmeasured.length > 3
            ? `${unmeasured.length} of the ${rows.length} axes`
            : unmeasured.map((row) => row.label.toLowerCase()).join(", ")}
        </p>
      ) : null}
    </div>
  );
}
