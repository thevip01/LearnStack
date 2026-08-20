"use client";

import { InlineMarkdown } from "@/components/content/Markdown";
import { OPTION_ACTIVE, OPTION_BASE, OPTION_IDLE } from "@/components/practice/questions/QuestionFrame";
import type { SafeMCQQuestion, SafeMultiSelectQuestion } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ChoiceQuestion({
  question,
  value,
  onChange,
  disabled,
}: {
  question: SafeMCQQuestion | SafeMultiSelectQuestion;
  value: string | string[] | undefined;
  onChange: (next: string | string[]) => void;
  disabled: boolean;
}) {
  const multiple = question.type === "multi_select";
  const selected = multiple ? ((value as string[] | undefined) ?? []) : value ? [value as string] : [];

  function toggle(optionId: string) {
    if (disabled) return;
    if (!multiple) {
      onChange(optionId);
      return;
    }
    onChange(selected.includes(optionId) ? selected.filter((id) => id !== optionId) : [...selected, optionId]);
  }

  return (
    <div role={multiple ? "group" : "radiogroup"} aria-label={multiple ? "Select all that apply" : "Select one"} className="space-y-1.5">
      {multiple ? <p className="text-2xs text-faint">Select all that apply.</p> : null}
      {question.options.map((option) => {
        const active = selected.includes(option.id);
        return (
          <label
            key={option.id}
            className={cn(OPTION_BASE, active ? OPTION_ACTIVE : OPTION_IDLE, disabled && "cursor-default opacity-80")}
          >
            <input
              type={multiple ? "checkbox" : "radio"}
              name={question.id}
              checked={active}
              disabled={disabled}
              onChange={() => toggle(option.id)}
              className="mt-0.5 accent-[rgb(var(--os-accent))]"
            />
            <span className="min-w-0">
              <span aria-hidden className="mr-1.5 font-mono text-2xs text-faint">
                {option.id}
              </span>
              <InlineMarkdown>{option.md}</InlineMarkdown>
            </span>
          </label>
        );
      })}
    </div>
  );
}
