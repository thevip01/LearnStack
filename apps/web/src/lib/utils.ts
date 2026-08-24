import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * `Panel.config` is an untyped pass-through from the subject package. These
 * readers are the only way panels are allowed to look inside it: a malformed
 * config degrades to the panel's default instead of throwing mid-render.
 */
export function cfgString(config: Record<string, unknown>, key: string, fallback: string): string;
export function cfgString(config: Record<string, unknown>, key: string): string | null;
export function cfgString(
  config: Record<string, unknown>,
  key: string,
  fallback?: string,
): string | null {
  const value = config[key];
  // `null` rather than `undefined` for "the layout did not set this", because that
  // is what the wire types use for an absent value and these results get handed
  // straight to props typed from them.
  return typeof value === "string" && value.length > 0 ? value : (fallback ?? null);
}

/**
 * Look a key up in a string record, keeping the key and value together.
 *
 * `noUncheckedIndexedAccess` types every index read as `T | undefined`, which is
 * accurate: an artifact map has no content under a name the run never emitted.
 * Returning the pair or `null` makes callers handle that once, at the lookup,
 * instead of asserting it away at each use.
 */
export function recordEntry(
  record: Record<string, string>,
  key: string | null | undefined,
): { name: string; content: string } | null {
  if (!key) return null;
  const content = record[key];
  return content === undefined ? null : { name: key, content };
}

export function cfgNumber(config: Record<string, unknown>, key: string, fallback: number): number {
  const value = config[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function cfgBool(config: Record<string, unknown>, key: string, fallback = false): boolean {
  const value = config[key];
  return typeof value === "boolean" ? value : fallback;
}

export function cfgStringArray(config: Record<string, unknown>, key: string): string[] {
  const value = config[key];
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

export function cfgRecords(config: Record<string, unknown>, key: string): Array<Record<string, unknown>> {
  const value = config[key];
  if (!Array.isArray(value)) return [];
  return value.filter(
    (entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null && !Array.isArray(entry),
  );
}

/** Stable id for anything that needs one and has no server-assigned id yet. */
export function localId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  const next = items.slice();
  if (from < 0 || to < 0 || from >= next.length || to >= next.length) return next;
  const [moved] = next.splice(from, 1);
  if (moved === undefined) return next;
  next.splice(to, 0, moved);
  return next;
}
