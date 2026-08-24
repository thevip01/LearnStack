import type { DimensionScore, MasteryDimension, MasteryState } from "./types";

/** An unmeasured dimension renders as this, never as 0%. See mastery.py. */
export const DASH = "—";

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * The single rule that protects a learner who has done the reading and none of
 * the labs: no evidence means no number, not a failing grade.
 */
export function formatDimension(score: DimensionScore | null | undefined, digits = 0): string {
  if (!score || !score.measured) return DASH;
  return formatPercent(score.score, digits);
}

export function formatScore(score: number | null | undefined, digits = 0): string {
  return formatPercent(score, digits);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return DASH;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return DASH;
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} m`;
}

const RELATIVE_STEPS: Array<[limit: number, divisor: number, unit: Intl.RelativeTimeFormatUnit]> = [
  [60_000, 1000, "second"],
  [3_600_000, 60_000, "minute"],
  [86_400_000, 3_600_000, "hour"],
  [604_800_000, 86_400_000, "day"],
  [2_592_000_000, 604_800_000, "week"],
  [31_536_000_000, 2_592_000_000, "month"],
];

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return DASH;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return DASH;
  const delta = parsed - now;
  const magnitude = Math.abs(delta);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [limit, divisor, unit] of RELATIVE_STEPS) {
    if (magnitude < limit) return formatter.format(Math.round(delta / divisor), unit);
  }
  return formatter.format(Math.round(delta / 31_536_000_000), "year");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return DASH;
  return parsed.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

export const DIMENSION_LABELS: Record<MasteryDimension, string> = {
  concept: "Concept",
  practice: "Practice",
  lab: "Lab",
  debugging: "Debugging",
  production: "Production",
  retention: "Retention",
};

export const MASTERY_STATE_LABELS: Record<MasteryState, string> = {
  untouched: "Untouched",
  partially_measured: "Partly measured",
  developing: "Developing",
  mastered: "Mastered",
  at_risk: "At risk",
};

/**
 * Status tone plus a glyph. Colour alone is never the signal, so every caller
 * renders the glyph or the label beside it.
 */
export function masteryStateTone(state: string): { className: string; glyph: string } {
  switch (state) {
    case "mastered":
      return { className: "text-ok border-ok/40 bg-ok/10", glyph: "✔" };
    case "developing":
      return { className: "text-info border-info/40 bg-info/10", glyph: "▲" };
    case "at_risk":
      return { className: "text-danger border-danger/40 bg-danger/10", glyph: "!" };
    case "partially_measured":
      return { className: "text-warn border-warn/40 bg-warn/10", glyph: "◐" };
    default:
      return { className: "text-faint border-line bg-raised", glyph: "◦" };
  }
}

export function difficultyLabel(difficulty: number | null | undefined): string {
  if (difficulty === null || difficulty === undefined) return DASH;
  return `${difficulty}/10`;
}

/**
 * Mirrored from learnos_schema/mastery.py so the hint ladder can state the cost
 * before a learner spends it. If these drift, the schema is authoritative: the
 * UI only ever previews the penalty, the API applies it.
 */
export const HINT_PENALTY_PER_LEVEL = 0.15;
export const HINT_PENALTY_FLOOR = 0.4;

export function hintScoreMultiplier(hintsUsed: number, dimension: MasteryDimension): number {
  // Hints are free while learning a definition and costly on the doing axes.
  if (hintsUsed <= 0 || dimension === "concept") return 1;
  return Math.max(HINT_PENALTY_FLOOR, 1 - HINT_PENALTY_PER_LEVEL * hintsUsed);
}

/** Percentage-point cost of taking one more hint, given how many are already spent. */
export function nextHintCost(hintsUsed: number, dimension: MasteryDimension): number {
  return hintScoreMultiplier(hintsUsed, dimension) - hintScoreMultiplier(hintsUsed + 1, dimension);
}

export function truncateMiddle(value: string, max = 48): string {
  if (value.length <= max) return value;
  const half = Math.floor((max - 1) / 2);
  return `${value.slice(0, half)}…${value.slice(value.length - half)}`;
}

export function titleCase(value: string): string {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
