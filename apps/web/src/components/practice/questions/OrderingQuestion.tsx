"use client";

import { ChevronDown, ChevronUp, GripVertical } from "lucide-react";
import { useRef } from "react";
import { InlineMarkdown } from "@/components/content/Markdown";
import { Button } from "@/components/ui/Button";
import type { SafeOrderingQuestion } from "@/lib/types";
import { cn, moveItem } from "@/lib/utils";

/**
 * Ordering supports both pointer drag and keyboard reordering. The buttons are
 * not a fallback for the drag: they are the primary path, because a drag-only
 * control is unusable with a screen reader and this question type is graded.
 */
export function OrderingQuestion({
  question,
  value,
  onChange,
  disabled,
}: {
  question: SafeOrderingQuestion;
  value: string[] | undefined;
  onChange: (next: string[]) => void;
  disabled: boolean;
}) {
  const order = value ?? question.items.map((item) => item.id);
  const dragIndex = useRef<number | null>(null);
  const byId = new Map(question.items.map((item) => [item.id, item]));

  function move(from: number, to: number) {
    if (disabled || to < 0 || to >= order.length) return;
    onChange(moveItem(order, from, to));
  }

  return (
    <ol className="space-y-1.5" aria-label="Drag or use the arrow buttons to order these items">
      {order.map((id, index) => {
        const item = byId.get(id);
        if (!item) return null;
        return (
          <li
            key={id}
            draggable={!disabled}
            onDragStart={() => {
              dragIndex.current = index;
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              if (dragIndex.current !== null) move(dragIndex.current, index);
              dragIndex.current = null;
            }}
            className={cn(
              "flex items-center gap-2 rounded border border-line bg-raised/40 px-2 py-1.5 text-xs",
              !disabled && "hover:border-line-strong",
            )}
          >
            <GripVertical aria-hidden className="size-3.5 shrink-0 text-faint" />
            <span aria-hidden className="w-4 shrink-0 font-mono text-2xs text-faint">
              {index + 1}
            </span>
            <span className="min-w-0 flex-1">
              <InlineMarkdown>{item.md}</InlineMarkdown>
            </span>
            <span className="flex shrink-0 gap-0.5">
              <Button
                variant="ghost"
                size="xs"
                disabled={disabled || index === 0}
                onClick={() => move(index, index - 1)}
                aria-label={`Move "${item.md}" up`}
              >
                <ChevronUp className="size-3" aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="xs"
                disabled={disabled || index === order.length - 1}
                onClick={() => move(index, index + 1)}
                aria-label={`Move "${item.md}" down`}
              >
                <ChevronDown className="size-3" aria-hidden />
              </Button>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
