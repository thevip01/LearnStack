"use client";

import type { SafeShortAnswerQuestion } from "@/lib/types";

export function ShortAnswerQuestion({
  question,
  value,
  onChange,
  disabled,
}: {
  question: SafeShortAnswerQuestion;
  value: string | undefined;
  onChange: (next: string) => void;
  disabled: boolean;
}) {
  return (
    <textarea
      aria-label={`Answer for question ${question.id}`}
      value={value ?? ""}
      disabled={disabled}
      rows={3}
      spellCheck={false}
      onChange={(event) => onChange(event.target.value)}
      placeholder="Type your answer"
      className="w-full resize-y rounded border border-line bg-canvas px-2 py-1.5 font-mono text-[0.8125rem] text-ink placeholder:text-faint focus:border-accent"
    />
  );
}
