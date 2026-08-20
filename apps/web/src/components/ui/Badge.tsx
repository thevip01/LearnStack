"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "accent" | "ok" | "warn" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "border-line bg-raised text-muted",
  accent: "border-accent/40 bg-accent/10 text-accent",
  ok: "border-ok/40 bg-ok/10 text-ok",
  warn: "border-warn/40 bg-warn/10 text-warn",
  danger: "border-danger/40 bg-danger/10 text-danger",
  info: "border-info/40 bg-info/10 text-info",
};

export function Badge({
  children,
  tone = "neutral",
  glyph,
  className,
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  /** A shape or letter so status never depends on colour alone. */
  glyph?: string;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium leading-4",
        TONES[tone],
        className,
      )}
    >
      {glyph ? <span aria-hidden>{glyph}</span> : null}
      {children}
    </span>
  );
}
