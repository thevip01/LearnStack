"use client";

import {
  Binary,
  BookOpen,
  Box,
  Boxes,
  Braces,
  Brain,
  Bug,
  Cloud,
  Code,
  Container,
  Cpu,
  Database,
  FlaskConical,
  Gauge,
  GitBranch,
  Globe,
  Key,
  Layers,
  LineChart,
  Lock,
  type LucideIcon,
  Network,
  Palette,
  Rocket,
  Server,
  ShieldCheck,
  Sigma,
  Table,
  Terminal,
  Users,
  Workflow,
  Wrench,
  Zap,
} from "lucide-react";
import { type LucideGlyph, resolveGlyph } from "@/lib/glyph";
import { cn } from "@/lib/utils";

/**
 * The one place a glyph name becomes something on screen.
 *
 * Typed `Record<LucideGlyph, LucideIcon>`, so a name added to the resolver cannot
 * ship without a component behind it and an icon removed from lucide fails the
 * typecheck rather than rendering nothing.
 */
const LUCIDE: Record<LucideGlyph, LucideIcon> = {
  binary: Binary,
  book: BookOpen,
  box: Box,
  boxes: Boxes,
  brain: Brain,
  braces: Braces,
  bug: Bug,
  chart: LineChart,
  cloud: Cloud,
  code: Code,
  container: Container,
  cpu: Cpu,
  database: Database,
  flask: FlaskConical,
  gauge: Gauge,
  git: GitBranch,
  globe: Globe,
  key: Key,
  layers: Layers,
  lock: Lock,
  network: Network,
  palette: Palette,
  rocket: Rocket,
  server: Server,
  shield: ShieldCheck,
  sigma: Sigma,
  table: Table,
  terminal: Terminal,
  users: Users,
  workflow: Workflow,
  wrench: Wrench,
  zap: Zap,
};

/**
 * Python's mark, built from the theme's two colours rather than traced.
 *
 * The package declares `accent #3776ab` and `accent_soft #ffd43b`, which are
 * Python's own blue and yellow, so two interlocking blocks in those colours read
 * as Python without shipping a copy of anyone's logo. A subject that declares one
 * colour gets a monochrome version of the same shape, which is the point of
 * drawing it from tokens.
 */
function PythonMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <rect x="3" y="2" width="11" height="12" rx="3.4" className="fill-accent" />
      <rect x="10" y="10" width="11" height="12" rx="3.4" className="fill-accent-soft" />
      <circle cx="6.9" cy="5.6" r="1.05" className="fill-canvas" />
      <circle cx="17.1" cy="18.4" r="1.05" className="fill-canvas" />
    </svg>
  );
}

/** The JS and TS squares: a filled tile with the two letters, which is the mark. */
function LetterMark({ letters, className }: { letters: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <rect x="2" y="2" width="20" height="20" rx="4" className="fill-accent" />
      <text
        x="12.5"
        y="17"
        textAnchor="middle"
        className="fill-canvas font-sans"
        style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "-0.5px" }}
      >
        {letters}
      </text>
    </svg>
  );
}

const SIZES = {
  xs: { box: "size-5 rounded", art: "size-3.5", text: "text-[0.5625rem]" },
  sm: { box: "size-6 rounded-md", art: "size-4", text: "text-2xs" },
  md: { box: "size-8 rounded-lg", art: "size-[1.15rem]", text: "text-xs" },
  lg: { box: "size-10 rounded-lg", art: "size-6", text: "text-sm" },
} as const;

/**
 * A subject, domain or module's identity as a small tile.
 *
 * The tile itself is always drawn, in the accent gradient, even when the fallback
 * monogram is what fills it. That is deliberate: the shelf reads as a set of
 * things with identities rather than as a list where some rows happen to have a
 * picture, and a package that names no icon still gets its own colour.
 *
 * Purely decorative, `aria-hidden` throughout. Every card that carries one also
 * carries the title as text, so a screen reader gains nothing from "Py".
 */
export function GlyphTile({
  icon,
  title,
  size = "md",
  className,
}: {
  icon: string | null | undefined;
  title: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const glyph = resolveGlyph(icon, title);
  const sizing = SIZES[size];
  const shell = cn(
    "grid shrink-0 place-items-center border border-accent/25 bg-gradient-to-br from-accent/15 to-accent-soft/25 text-accent",
    sizing.box,
    className,
  );

  if (glyph.kind === "brand") {
    return (
      <span className={shell} aria-hidden>
        {glyph.mark === "python" ? (
          <PythonMark className={sizing.art} />
        ) : (
          <LetterMark letters={glyph.mark === "javascript" ? "JS" : "TS"} className={sizing.art} />
        )}
      </span>
    );
  }

  if (glyph.kind === "lucide") {
    const Icon = LUCIDE[glyph.name];
    return (
      <span className={shell} aria-hidden>
        <Icon className={sizing.art} strokeWidth={1.75} />
      </span>
    );
  }

  return (
    <span className={shell} aria-hidden>
      <span className={cn("font-semibold leading-none tracking-tight", sizing.text)}>{glyph.text}</span>
    </span>
  );
}
