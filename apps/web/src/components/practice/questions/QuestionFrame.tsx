"use client";

import { Markdown } from "@/components/content/Markdown";
import { SourceChips } from "@/components/content/SourceChips";
import { Badge } from "@/components/ui/Badge";
import { DIMENSION_LABELS, difficultyLabel } from "@/lib/format";
import type { QuestionResult, SafeQuestion } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Shared chrome for every question type: stem, meta, and post-grading feedback. */
export function QuestionFrame({
  question,
  index,
  result,
  children,
}: {
  question: SafeQuestion;
  index: number;
  result?: QuestionResult;
  children: React.ReactNode;
}) {
  const graded = result !== undefined;
  return (
    <li
      id={`question-${question.id}`}
      className={cn(
        "rounded-panel border bg-surface p-pad",
        graded ? (result.correct ? "border-ok/40" : "border-danger/40") : "border-line",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span aria-hidden className="font-mono text-2xs text-faint">
            {String(index + 1).padStart(2, "0")}
          </span>
          <div className="min-w-0">
            <Markdown>{question.stem_md}</Markdown>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {graded ? (
            <Badge tone={result.correct ? "ok" : "danger"} glyph={result.correct ? "✔" : "✘"}>
              {result.correct ? "Correct" : "Incorrect"}
            </Badge>
          ) : null}
          <span className="text-2xs text-faint">
            {DIMENSION_LABELS[question.dimension]} · {difficultyLabel(question.difficulty)}
          </span>
        </div>
      </div>

      <div className="mt-2">{children}</div>

      {graded && (result.expected !== null || result.explanation_md) ? (
        <div className="mt-3 space-y-2 rounded border border-line bg-raised/40 p-2">
          {result.expected !== null && result.expected !== undefined ? (
            <div className="text-2xs">
              <span className="text-faint">Expected: </span>
              <span className="font-mono text-ink">
                {typeof result.expected === "string" ? result.expected : JSON.stringify(result.expected)}
              </span>
            </div>
          ) : null}
          {/* Explanations are authored and arrive with the grade. Never composed here. */}
          {result.explanation_md ? <Markdown className="text-2xs">{result.explanation_md}</Markdown> : null}
        </div>
      ) : null}

      <SourceChips sources={question.sources} />
    </li>
  );
}

export const OPTION_BASE =
  "flex w-full cursor-pointer items-start gap-2 rounded border px-2 py-1.5 text-left text-xs transition-colors";
export const OPTION_IDLE = "border-line bg-raised/40 hover:border-line-strong hover:bg-raised";
export const OPTION_ACTIVE = "border-accent bg-accent/10 text-ink";
