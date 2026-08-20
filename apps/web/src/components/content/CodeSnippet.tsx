"use client";

import { Check, Copy } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

/**
 * Static code display with line numbers and authored line highlights.
 *
 * Deliberately not syntax highlighted: Monaco is already in the bundle for the
 * editor and loading a second highlighter for lesson snippets costs more than it
 * returns. `highlight_lines` from the CodeBlock is what draws the eye instead.
 */
export function CodeSnippet({
  code,
  language,
  highlightLines = [],
  caption,
  actions,
  maxHeight = "24rem",
  showLineNumbers = true,
}: {
  code: string;
  language?: string | null;
  highlightLines?: number[];
  caption?: string | null;
  actions?: ReactNode;
  maxHeight?: string;
  showLineNumbers?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const lines = code.replace(/\n$/, "").split("\n");
  const highlighted = new Set(highlightLines);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is permission-gated; the snippet stays selectable either way.
    }
  }

  return (
    <figure className="overflow-hidden rounded-panel border border-line bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-line bg-raised/60 px-2 py-1">
        <span className="font-mono text-2xs uppercase tracking-wide text-faint">{language ?? "text"}</span>
        <div className="flex items-center gap-1">
          {actions}
          <Button variant="ghost" size="xs" onClick={copy} aria-label="Copy code">
            {copied ? <Check className="size-3" aria-hidden /> : <Copy className="size-3" aria-hidden />}
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
      <div className="overflow-auto" style={{ maxHeight }}>
        <pre className="min-w-full font-mono text-[0.8125rem] leading-5">
          <code>
            {lines.map((line, index) => {
              const lineNumber = index + 1;
              return (
                <span
                  key={lineNumber}
                  className={cn(
                    "grid grid-cols-[3ch_1fr] gap-3 px-2",
                    highlighted.has(lineNumber) && "border-l-2 border-accent bg-accent/10 pl-[calc(0.5rem-2px)]",
                  )}
                >
                  {showLineNumbers ? (
                    <span aria-hidden className="select-none text-right text-faint">
                      {lineNumber}
                    </span>
                  ) : (
                    <span aria-hidden />
                  )}
                  <span className="whitespace-pre text-ink/90">{line || " "}</span>
                </span>
              );
            })}
          </code>
        </pre>
      </div>
      {caption ? (
        <figcaption className="border-t border-line px-2 py-1 text-2xs text-muted">{caption}</figcaption>
      ) : null}
    </figure>
  );
}
