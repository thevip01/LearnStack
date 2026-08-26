/**
 * Chart styling, in one place, because recharts wants values and not classes.
 *
 * Every colour token in this app is stored as an rgb *triplet* in a custom
 * property so Tailwind's `/opacity` modifiers work. That has a sharp edge for
 * anything passed to recharts as a plain string: `var(--os-line)` resolves to
 * "38 44 58", which is not a colour, so the declaration is dropped and the fallback
 * inside `var(..., #2a2f3a)` never fires, because a fallback only applies when the
 * property is *undefined*. Charts drawn that way come out with black axes on a dark
 * panel. The triplet has to be wrapped: `rgb(var(--os-line))`.
 *
 * Keeping the wrapping here means one definition of "chart grey" and no chance of
 * a panel quietly reintroducing the same mistake.
 */

const rgb = (token: string, alpha?: number): string =>
  alpha === undefined ? `rgb(var(${token}))` : `rgb(var(${token}) / ${alpha})`;

export const CHART = {
  grid: rgb("--os-line"),
  axis: rgb("--os-line-strong"),
  tickFill: rgb("--os-faint"),
  labelFill: rgb("--os-muted"),
  surface: rgb("--os-surface"),
} as const;

/** Series colours, in the order a chart should reach for them. */
export const SERIES_COLORS = [
  rgb("--os-accent"),
  rgb("--os-info"),
  rgb("--os-ok"),
  rgb("--os-warn"),
  rgb("--os-danger"),
  rgb("--os-accent-soft"),
] as const;

export const AXIS_TICK = { fontSize: 10, fill: CHART.tickFill } as const;

export const TOOLTIP_STYLE = {
  background: CHART.surface,
  border: `1px solid ${CHART.grid}`,
  borderRadius: 8,
  fontSize: 12,
  padding: "6px 8px",
} as const;

export const TOOLTIP_LABEL_STYLE = { color: CHART.labelFill, fontSize: 11 } as const;

/** `2026-08-26` -> `08/26`, which is all the room an axis tick has. */
export function shortDate(iso: string): string {
  const parts = iso.split("-");
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : iso;
}

export const percentTick = (value: number): string => `${Math.round(value * 100)}`;
