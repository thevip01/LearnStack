import type { CSSProperties } from "react";
import type { ThemeSpec } from "./types";

/**
 * ThemeSpec -> CSS custom properties.
 *
 * Panels never name a colour. They use the Tailwind `accent` token, which reads
 * `--os-accent`, which is written here from the subject's own theme. That is why
 * AWS and Python can look different without a single subject-specific style rule.
 */

const DEFAULT_ACCENT = "#6366f1";

export function hexToTriplet(hex: string | null | undefined): string | null {
  if (!hex) return null;
  const match = /^#([0-9a-fA-F]{6})$/.exec(hex.trim());
  if (!match?.[1]) return null;
  const int = Number.parseInt(match[1], 16);
  return `${(int >> 16) & 255} ${(int >> 8) & 255} ${int & 255}`;
}

/** Mixes an accent toward the canvas so a soft variant exists even when unset. */
function softenTriplet(triplet: string, amount = 0.62): string {
  const parts = triplet.split(" ").map((value) => Number.parseInt(value, 10));
  return parts.map((value) => Math.round(value * (1 - amount) + 148 * amount * 0.35)).join(" ");
}

export function themeCssVars(theme: ThemeSpec | null | undefined): CSSProperties {
  const accent = hexToTriplet(theme?.accent) ?? hexToTriplet(DEFAULT_ACCENT) ?? "99 102 241";
  const accentSoft = hexToTriplet(theme?.accent_soft ?? null) ?? softenTriplet(accent);
  const compact = theme?.density === "compact";

  // A plain object cast: these are custom properties, which CSSProperties does
  // not type, and inlining them is what scopes a theme to one runtime subtree.
  return {
    "--os-accent": accent,
    "--os-accent-soft": accentSoft,
    "--os-pad": compact ? "0.5rem" : "0.75rem",
    "--os-pad-sm": compact ? "0.25rem" : "0.5rem",
    "--os-row-h": compact ? "1.5rem" : "1.75rem",
    ...(theme?.mono_font ? { "--os-font-mono": theme.mono_font } : {}),
  } as CSSProperties;
}

/** Accent-tinted ring/border helpers for panels that need an emphasis surface. */
export const ACCENT_SURFACE = "border-accent/40 bg-accent/10 text-accent";
