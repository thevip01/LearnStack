"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { InlineMarkdown } from "@/components/content/Markdown";
import { OPTION_ACTIVE, OPTION_BASE, OPTION_IDLE } from "@/components/practice/questions/QuestionFrame";
import type { SafeMatchingQuestion } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Click-to-pair: pick a left item, then a right item. Both columns are buttons,
 * so the whole interaction works from the keyboard, and an existing pair can be
 * cleared without re-selecting it.
 */
export function MatchingQuestion({
  question,
  value,
  onChange,
  disabled,
}: {
  question: SafeMatchingQuestion;
  value: Record<string, string> | undefined;
  onChange: (next: Record<string, string>) => void;
  disabled: boolean;
}) {
  const pairs = value ?? {};
  const [pendingLeft, setPendingLeft] = useState<string | null>(null);
  const rightById = new Map(question.right.map((item) => [item.id, item]));
  const takenRight = new Set(Object.values(pairs));

  function chooseLeft(id: string) {
    if (disabled) return;
    setPendingLeft((current) => (current === id ? null : id));
  }

  function chooseRight(rightId: string) {
    if (disabled || !pendingLeft) return;
    const next: Record<string, string> = { ...pairs };
    // A right item can only serve one pair; taking it releases its old owner.
    for (const [leftId, assigned] of Object.entries(next)) {
      if (assigned === rightId) delete next[leftId];
    }
    next[pendingLeft] = rightId;
    onChange(next);
    setPendingLeft(null);
  }

  function clear(leftId: string) {
    if (disabled) return;
    const next = { ...pairs };
    delete next[leftId];
    onChange(next);
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div>
        <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-faint">Items</div>
        <ul className="space-y-1.5">
          {question.left.map((item) => {
            const matched = pairs[item.id];
            const active = pendingLeft === item.id;
            return (
              <li key={item.id}>
                <div
                  className={cn(
                    OPTION_BASE,
                    active ? OPTION_ACTIVE : matched ? "border-ok/40 bg-ok/5" : OPTION_IDLE,
                    "items-center justify-between",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => chooseLeft(item.id)}
                    disabled={disabled}
                    aria-pressed={active}
                    className="min-w-0 flex-1 text-left"
                  >
                    <InlineMarkdown>{item.md}</InlineMarkdown>
                    {matched ? (
                      <span className="mt-0.5 block truncate text-2xs text-ok">
                        → {rightById.get(matched)?.md ?? matched}
                      </span>
                    ) : null}
                  </button>
                  {matched ? (
                    <button
                      type="button"
                      onClick={() => clear(item.id)}
                      disabled={disabled}
                      aria-label={`Clear match for ${item.md}`}
                      className="shrink-0 text-faint hover:text-danger"
                    >
                      <X className="size-3" aria-hidden />
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      <div>
        <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-faint">
          {pendingLeft ? "Now pick its match" : "Matches"}
        </div>
        <ul className="space-y-1.5">
          {question.right.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => chooseRight(item.id)}
                disabled={disabled || !pendingLeft}
                className={cn(
                  OPTION_BASE,
                  takenRight.has(item.id) ? "border-line bg-raised/20 text-muted" : OPTION_IDLE,
                  pendingLeft && !disabled ? "hover:border-accent" : "cursor-default",
                )}
              >
                <InlineMarkdown>{item.md}</InlineMarkdown>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
