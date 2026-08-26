/**
 * What to draw for a subject, a domain or a module.
 *
 * Four places in the schema carry an `icon` string (`ThemeSpec`, `DomainRef`,
 * `Module`, `NavigationItem`) and until now nothing in the app read any of them,
 * so every shelf card looked the same and Python's package might as well not have
 * said "python". This turns that string into one of three things, in order:
 *
 *   brand     a mark we draw ourselves, for the handful of technologies where a
 *             generic icon would be a downgrade
 *   lucide    a named icon from the set the rest of the app already uses
 *   monogram  initials from the title, tinted with the subject's own accent
 *
 * The third tier is the important one. A package can name any icon it likes and
 * the worst case is a tidy two-letter tile in the right colour, never a broken
 * image and never a hole in the layout. That is also why a URL is refused rather
 * than loaded: a remote logo means a third-party request on every card and a
 * different kind of empty box when it 404s.
 *
 * This module stays free of JSX so the mapping can be tested directly, and so the
 * set of names lives in one place instead of being spread across components.
 */

export const BRAND_MARKS = ["python", "javascript", "typescript"] as const;
export type BrandMark = (typeof BRAND_MARKS)[number];

/**
 * Names that mean the same thing as a brand mark. Kept small on purpose: an alias
 * is a claim that two names are the same technology, not that they look similar.
 */
const BRAND_ALIASES: Record<string, BrandMark> = {
  py: "python",
  python: "python",
  python3: "python",
  js: "javascript",
  javascript: "javascript",
  ecmascript: "javascript",
  node: "javascript",
  nodejs: "javascript",
  ts: "typescript",
  typescript: "typescript",
};

/**
 * The lucide icons a package may ask for by name. Adding a key here is not enough:
 * `GlyphTile` holds a `Record<LucideGlyph, LucideIcon>`, so tsc refuses to build
 * until the new name has a component behind it.
 */
export const LUCIDE_GLYPHS = [
  "binary",
  "book",
  "box",
  "boxes",
  "brain",
  "braces",
  "bug",
  "chart",
  "cloud",
  "code",
  "container",
  "cpu",
  "database",
  "flask",
  "gauge",
  "git",
  "globe",
  "key",
  "layers",
  "lock",
  "network",
  "palette",
  "rocket",
  "server",
  "shield",
  "sigma",
  "table",
  "terminal",
  "users",
  "workflow",
  "wrench",
  "zap",
] as const;
export type LucideGlyph = (typeof LUCIDE_GLYPHS)[number];

/** Names a package is likely to write that mean one of the icons above. */
const LUCIDE_ALIASES: Record<string, LucideGlyph> = {
  ai: "brain",
  algorithm: "sigma",
  api: "network",
  architecture: "workflow",
  aws: "cloud",
  azure: "cloud",
  bash: "terminal",
  bitwise: "binary",
  chart: "chart",
  charts: "chart",
  class: "boxes",
  cli: "terminal",
  cloud: "cloud",
  concurrency: "zap",
  container: "container",
  data: "table",
  dataset: "table",
  design: "palette",
  devops: "workflow",
  docker: "container",
  finance: "chart",
  function: "braces",
  functions: "braces",
  gcp: "cloud",
  graph: "chart",
  hardware: "cpu",
  http: "globe",
  infra: "server",
  k8s: "boxes",
  kubernetes: "boxes",
  lab: "flask",
  linux: "terminal",
  math: "sigma",
  ml: "brain",
  module: "box",
  performance: "gauge",
  postgres: "database",
  postgresql: "database",
  security: "shield",
  shell: "terminal",
  sql: "database",
  sqlite: "database",
  statistics: "chart",
  testing: "flask",
  tool: "wrench",
  tooling: "wrench",
  web: "globe",
};

export type Glyph =
  | { kind: "brand"; mark: BrandMark }
  | { kind: "lucide"; name: LucideGlyph }
  | { kind: "monogram"; text: string };

const LUCIDE_SET = new Set<string>(LUCIDE_GLYPHS);

/** Words that carry no identity, so they never win a monogram slot. */
const NOISE = new Set(["a", "an", "and", "for", "in", "of", "on", "the", "to", "with"]);

/**
 * Initials for a title, at most two characters.
 *
 * Two words give their first letters ("Modern Python" -> "MP"), one word gives its
 * first two ("Python" -> "Py"), which reads as a word rather than as an acronym.
 */
export function monogram(title: string): string {
  const words = title.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const strong = words.filter((word) => !NOISE.has(word.toLowerCase()));
  const chosen = strong.length > 0 ? strong : words;
  const first = chosen[0];
  if (!first) return "?";
  const second = chosen[1];
  if (second) return `${first[0]?.toUpperCase() ?? ""}${second[0]?.toUpperCase() ?? ""}`;
  return `${first[0]?.toUpperCase() ?? ""}${first[1]?.toLowerCase() ?? ""}`;
}

/** True for anything that names a file or an address rather than an icon. */
function isLocator(value: string): boolean {
  return value.includes("/") || /\.(svg|png|jpe?g|webp|gif|ico)$/i.test(value);
}

/**
 * `icon` is whatever the package wrote, `title` is the fallback's raw material.
 *
 * Unknown names fall through to the monogram rather than to a generic file icon,
 * because a wrong-but-plausible icon is harder to notice than initials are.
 */
export function resolveGlyph(icon: string | null | undefined, title: string): Glyph {
  const raw = (icon ?? "").trim();
  if (raw && !isLocator(raw)) {
    // Dots go too, so a package writing "node.js" lands on the same key as "nodejs".
    const key = raw.toLowerCase().replace(/[\s_.-]+/g, "");
    const brand = BRAND_ALIASES[key];
    if (brand) return { kind: "brand", mark: brand };
    if (LUCIDE_SET.has(key)) return { kind: "lucide", name: key as LucideGlyph };
    const aliased = LUCIDE_ALIASES[key];
    if (aliased) return { kind: "lucide", name: aliased };
  }
  return { kind: "monogram", text: monogram(title) };
}
