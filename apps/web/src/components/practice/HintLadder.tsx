"use client";

import { Lightbulb, TriangleAlert } from "lucide-react";
import { Markdown } from "@/components/content/Markdown";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { useToast } from "@/components/ui/Toast";
import { DIMENSION_LABELS, formatPercent, nextHintCost } from "@/lib/format";
import { useRequestHint } from "@/lib/practice";
import type { MasteryDimension } from "@/lib/types";

/**
 * Progressive hints, with the price on the button.
 *
 * The cost is shown *before* the hint is revealed because that is the whole point
 * of the ladder: spending a hint is a decision, not an accident. The multiplier
 * mirrored in lib/format is a preview only — the API applies the real penalty.
 */
export function HintLadder({
  taskId,
  hintCount,
  dimension,
  warnBeforeReveal = true,
}: {
  taskId: string | null;
  hintCount: number;
  dimension: MasteryDimension;
  warnBeforeReveal?: boolean;
}) {
  const { hints, request, pending, error } = useRequestHint(taskId);
  const toast = useToast();

  if (hintCount === 0) {
    return (
      <EmptyState
        title="No hints for this task"
        description="The author did not write a hint ladder here, so nothing is being withheld."
      />
    );
  }

  const used = hints.length;
  const remaining = Math.max(hintCount - used, 0);
  const cost = nextHintCost(used, dimension);
  const nextLevel = used + 1;
  // The API marks the solution-revealing level on the hint itself, which arrives
  // only after the reveal. The last rung is the one worth warning about.
  const lastRung = nextLevel >= hintCount;
  const alreadyRevealed = hints.some((hint) => hint.reveals_solution);

  async function take() {
    try {
      await request();
    } catch (cause) {
      toast.push({
        tone: "error",
        title: "Hint unavailable",
        message: cause instanceof Error ? cause.message : "the practice service rejected the request",
      });
    }
  }

  return (
    <div className="space-y-2 p-pad">
      <div className="flex items-center gap-2 text-2xs text-faint">
        <Lightbulb className="size-3" aria-hidden />
        {used} of {hintCount} taken · {DIMENSION_LABELS[dimension]} dimension
      </div>

      <ol className="space-y-2">
        {hints.map((hint) => (
          <li key={hint.level} className="rounded-panel border border-line bg-surface p-pad">
            <div className="mb-1 flex items-center gap-2">
              <Badge tone={hint.reveals_solution ? "warn" : "neutral"}>Hint {hint.level}</Badge>
              {hint.reveals_solution ? <span className="text-2xs text-warn">Includes the solution</span> : null}
            </div>
            <Markdown className="text-xs">{hint.md}</Markdown>
          </li>
        ))}
      </ol>

      {remaining > 0 ? (
        <div className="rounded-panel border border-line bg-raised/40 p-pad">
          {warnBeforeReveal && lastRung && !alreadyRevealed ? (
            <p className="mb-2 flex items-start gap-1.5 text-2xs text-warn">
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              This is the last rung of the ladder. On most tasks it gives the answer away.
            </p>
          ) : null}
          <Button variant="outline" size="sm" onClick={take} loading={pending} disabled={!taskId}>
            Reveal hint {nextLevel}
            <span className="text-faint">
              {cost > 0 ? `· costs ${formatPercent(cost, 0)} of the score` : "· free on this dimension"}
            </span>
          </Button>
          <p className="mt-1.5 text-2xs text-faint">
            {remaining} hint{remaining === 1 ? "" : "s"} left.{" "}
            {cost > 0
              ? "Hints discount the doing dimensions; the penalty is applied when you submit."
              : "Concept-dimension hints carry no penalty."}
          </p>
        </div>
      ) : (
        <p className="text-2xs text-faint">The whole ladder has been read.</p>
      )}

      {error ? <p className="text-2xs text-danger">{error instanceof Error ? error.message : "hint failed"}</p> : null}
    </div>
  );
}
