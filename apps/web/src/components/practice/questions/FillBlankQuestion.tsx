"use client";

import { useMemo } from "react";
import type { SafeFillBlankQuestion } from "@/lib/types";

/** Splits `... {{1}} ... {{2}} ...` into text and blank markers, order preserved. */
function segments(template: string): Array<{ kind: "text"; value: string } | { kind: "blank"; index: number }> {
  const parts = template.split(/\{\{(\d+)\}\}/g);
  return parts.map((part, index) =>
    index % 2 === 1 ? { kind: "blank" as const, index: Number.parseInt(part, 10) - 1 } : { kind: "text" as const, value: part },
  );
}

export function FillBlankQuestion({
  question,
  value,
  onChange,
  disabled,
}: {
  question: SafeFillBlankQuestion;
  value: string[] | undefined;
  onChange: (next: string[]) => void;
  disabled: boolean;
}) {
  const parsed = useMemo(() => segments(question.template), [question.template]);
  const blanks = parsed.filter((part) => part.kind === "blank").length;
  const answers = value ?? Array.from({ length: blanks }, () => "");

  function setBlank(index: number, next: string) {
    const copy = answers.slice();
    while (copy.length <= index) copy.push("");
    copy[index] = next;
    onChange(copy);
  }

  return (
    <div className="rounded border border-line bg-raised/40 p-2 font-mono text-[0.8125rem] leading-7 text-ink/90">
      {parsed.map((part, index) =>
        part.kind === "text" ? (
          <span key={index} className="whitespace-pre-wrap">
            {part.value}
          </span>
        ) : (
          <input
            key={index}
            type="text"
            aria-label={`Blank ${part.index + 1}`}
            value={answers[part.index] ?? ""}
            disabled={disabled}
            spellCheck={false}
            autoComplete="off"
            onChange={(event) => setBlank(part.index, event.target.value)}
            className="mx-1 w-32 rounded border border-accent/50 bg-canvas px-1.5 py-0.5 text-ink placeholder:text-faint focus:border-accent"
            placeholder={`blank ${part.index + 1}`}
          />
        ),
      )}
      {question.case_sensitive ? <div className="mt-1 text-2xs text-warn">Case sensitive.</div> : null}
    </div>
  );
}
